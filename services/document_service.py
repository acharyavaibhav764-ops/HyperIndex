import logging
from datetime import datetime
from fastapi import HTTPException, status
from qdrant_client import models
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.retriever import Retriever
from core.uploader import Uploader
from db.models.document import Document
from schemas.document import (
    ChunkDescription,
    DeleteDocumentResponse,
    DocumentDescription,
    GetDocumentChunksResponse,
    GetDocumentsResponse,
)

logger = logging.getLogger(__name__)


class DocumentService:
    """
    Coordinates document lifecycle operations across SQLite, Qdrant, and MinIO.
    
    Attributes:
        db: SQLAlchemy session for metadata & deduplication tracking
        retriever: Retriever providing access to Qdrant client
        uploader: Uploader providing access to MinIO S3 client

    Methods:
        list_documents()
        get_document()
        get_document_chunks()
        update_document_metadata()
        delete_document()
    """

    def __init__(
        self,
        db: Session,
        retriever: Retriever,
        uploader: Uploader,
    ) -> None:
        
        self.db = db
        self.retriever = retriever
        self.uploader = uploader

    @staticmethod
    def _make_document_filter(document_id: str) -> models.Filter:
        return models.Filter(must=[
            models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))
        ])

    def _count_chunks(self, document_id: str) -> int:
        return self.retriever.client.count(
            collection_name=self.retriever.collection_name,
            count_filter=self._make_document_filter(document_id),
            exact=True,
        ).count

    def list_documents(
        self,
        product_id: str | None = None,
        name_search: str | None = None,
        status: str | None = None,
        uploaded_after: datetime | None = None,
        uploaded_before: datetime | None = None,
        limit: int = 50,
        skip: int = 0,
    ) -> GetDocumentsResponse:
        """Query SQLite with filters and return GetDocumentsResponse having all matching document descriptions"""

        query = select(Document)

        if product_id:
            query = query.where(Document.product_id == product_id)
        if name_search:
            query = query.where(Document.filename.ilike(f"%{name_search}%"))
        if uploaded_after:
            query = query.where(Document.created_at >= uploaded_after)
        if uploaded_before:
            query = query.where(Document.created_at <= uploaded_before)

        # Fetch records within pagination limits
        records = self.db.scalars(
            query.order_by(Document.created_at.desc()).offset(skip).limit(limit) # Newest first
        ).all()

        # Compile document descriptions
        documents = []
        for doc in records:

            # Query Qdrant for live chunk count
            total_chunks = self._count_chunks(doc.document_id)

            documents.append(
                DocumentDescription(
                    document_id=doc.document_id,
                    filename=doc.filename,
                    product_id=doc.product_id,
                    size_bytes=doc.size_bytes,
                    sha256=doc.sha256,
                    total_chunks=total_chunks,
                    status="indexed",
                    created_at=doc.created_at,
                )
            )

        # Count total matching records
        total_count = self.db.scalar(
            select(func.count()).select_from(query.subquery())
        ) or 0

        return GetDocumentsResponse(
            total_count=total_count,
            limit=limit,
            skip=skip,
            documents=documents,
        )

    def get_document(self, document_id: str) -> DocumentDescription:
        """Fetch single document metadata from SQLite and Qdrant and return a DocumentDescription as response"""

        # Find document having required document_id in SQLite
        doc = self.db.scalar(select(Document).where(Document.document_id == document_id))
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document with ID '{document_id}' not found",
            )

        # Find document having required document_id in Qdrant
        total_chunks = self._count_chunks(document_id)

        return DocumentDescription(
            document_id=doc.document_id,
            filename=doc.filename,
            product_id=doc.product_id,
            size_bytes=doc.size_bytes,
            sha256=doc.sha256,
            total_chunks=total_chunks,
            status="indexed",
            created_at=doc.created_at,
        )

    def get_document_chunks(
        self,
        document_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> GetDocumentChunksResponse:
        """Inspect text chunks and metadatas from Qdrant"""

        # Find document having required document_id in SQLite
        doc = self.db.scalar(select(Document).where(Document.document_id == document_id))
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document with ID '{document_id}' not found",
            )

        if limit < 1 or offset < 0:
            raise ValueError("Chunk limit must be positive and offset must be non-negative")

        total_chunks = self._count_chunks(document_id)
        records = []
        cursor = None
        remaining = offset
        
        # Qdrant uses point-ID cursors; the API offset counts skipped chunks.
        if offset < total_chunks:
            while remaining:
                skipped, cursor = self.retriever.client.scroll(
                    collection_name=self.retriever.collection_name,
                    scroll_filter=self._make_document_filter(document_id),
                    limit=min(remaining, 256),
                    offset=cursor,
                    with_payload=False,
                    with_vectors=False,
                )
                remaining -= len(skipped)
                if not skipped or cursor is None:
                    break
            if offset == 0 or (remaining == 0 and cursor is not None):
                records, _ = self.retriever.client.scroll(
                    collection_name=self.retriever.collection_name,
                    scroll_filter=self._make_document_filter(document_id),
                    limit=limit,
                    offset=cursor,
                    with_payload=True,
                    with_vectors=False,
                )

        # Compile chunk descriptions
        chunk_items = []
        for record in records:
            meta_dict = dict(record.payload or {})
            text = meta_dict.pop("text", "")
            chunk_items.append(
                ChunkDescription(
                    chunk_id=meta_dict.get("chunk_id", str(record.id)),
                    chunk_index=meta_dict.get("chunk_index", 0),
                    page=meta_dict.get("page", 1),
                    text=text or "",
                    metadata=meta_dict,
                )
            )

        return GetDocumentChunksResponse(
            document_id=document_id,
            filename=doc.filename,
            total_chunks=total_chunks,
            chunks=chunk_items,
        )

    def update_document_metadata(
        self,
        document_id: str,
        product_id: str,
    ) -> DocumentDescription:
        """Update product_id of document having required document_id in SQLite and Qdrant"""

        # Find document having required document_id in SQLite
        doc = self.db.scalar(select(Document).where(Document.document_id == document_id))
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document with ID '{document_id}' not found",
            )

        # Update product_id in SQLite
        doc.product_id = product_id
        self.db.commit()
        self.db.refresh(doc)

        # Update product_id in every chunk of the document
        self.retriever.client.set_payload(
            collection_name=self.retriever.collection_name,
            payload={"product_id": product_id},
            points=self._make_document_filter(document_id),
            wait=True,
        )
        total_chunks = self._count_chunks(document_id)

        return DocumentDescription(
            document_id=doc.document_id,
            filename=doc.filename,
            product_id=doc.product_id,
            size_bytes=doc.size_bytes,
            sha256=doc.sha256,
            total_chunks=total_chunks,
            status="indexed",
            created_at=doc.created_at,
        )

    def delete_document(self, document_id: str) -> DeleteDocumentResponse:
        """Delete document from Qdrant, SQLite and MinIO"""

        # Find document having required document_id
        doc = self.db.scalar(select(Document).where(Document.document_id == document_id))
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document with ID '{document_id}' not found",
            )

        # Remove vectors from Qdrant
        deleted_chunks_count = self._count_chunks(document_id)
        if deleted_chunks_count > 0:
            self.retriever.client.delete(
                collection_name=self.retriever.collection_name,
                points_selector=models.FilterSelector(filter=self._make_document_filter(document_id)),
                wait=True,
            )
            logger.info("Purged %d vectors from Qdrant for doc_id=%s", deleted_chunks_count, document_id)

        # Delete relational record from SQLite
        self.db.delete(doc)
        self.db.commit()
        logger.info("Deleted SQLite metadata record for doc_id=%s", document_id)

        # Remove raw binary from MinIO
        storage_removed = True
        try:
            self.uploader.client.delete_object(
                Bucket=self.uploader.bucket_name,
                Key=document_id,
            )
            logger.info("Deleted MinIO binary object for doc_id=%s", document_id)
        except Exception as err:
            storage_removed = False
            logger.warning("Failed to delete MinIO object for doc_id=%s: %s", document_id, err)

        return DeleteDocumentResponse(
            document_id=document_id,
            status="deleted",
            deleted_chunks=deleted_chunks_count,
            database_removed=True,
            storage_removed=storage_removed,
        )
