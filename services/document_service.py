import logging
from datetime import datetime
from typing import Any
from fastapi import HTTPException, status
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
    Coordinates document lifecycle operations across SQLite, ChromaDB, and MinIO.
    
    Attributes:
        db: SQLAlchemy session for metadata & deduplication tracking
        retriever: Retriever providing access to ChromaDB collection
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

    def list_documents(
        self,
        product_id: str | None = None,
        name_search: str | None = None,
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

            # Query Chroma for live chunk count
            chroma_res = self.retriever.collection.get(
                where={"document_id": doc.document_id}
            )
            total_chunks = len(chroma_res.get("ids", []))

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
        """Fetch single document metadata from SQLite and ChromaDB and return a DocumentDescription as response"""

        # Find document having required document_id in SQLite
        doc = self.db.scalar(select(Document).where(Document.document_id == document_id))
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document with ID '{document_id}' not found",
            )

        # Find document having required document_id in chroma
        chroma_res = self.retriever.collection.get(
            where={"document_id": document_id}
        )
        total_chunks = len(chroma_res.get("ids", []))

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
        """Inspect text chunks and metadatas from ChromaDB"""

        # Find document having required document_id in SQLite
        doc = self.db.scalar(select(Document).where(Document.document_id == document_id))
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document with ID '{document_id}' not found",
            )

        # Retrive all chunks of document having required document_id for current pagination limits
        chroma_res = self.retriever.collection.get(
            where={"document_id": document_id},
            include=["documents", "metadatas"],
            limit=limit,
            offset=offset,
        )
        ids = chroma_res.get("ids", [])
        docs = chroma_res.get("documents", [])
        metas = chroma_res.get("metadatas", [])

        all_ids = self.retriever.collection.get(
            where={"document_id": document_id}
        ).get("ids", []) # Total chunks across entire document (beyond pagination limits)

        # Compile chunk descriptions
        chunk_items = []
        for chunk_id, text, meta in zip(ids, docs, metas):
            meta_dict = meta or {}
            chunk_items.append(
                ChunkDescription(
                    chunk_id=chunk_id,
                    chunk_index=meta_dict.get("chunk_index", 0),
                    page=meta_dict.get("page", 1),
                    text=text or "",
                    metadata=meta_dict,
                )
            )

        return GetDocumentChunksResponse(
            document_id=document_id,
            filename=doc.filename,
            total_chunks=len(all_ids),
            chunks=chunk_items,
        )

    def update_document_metadata(
        self,
        document_id: str,
        product_id: str,
    ) -> DocumentDescription:
        """Update product_id of document having required document_id in SQLite and Chroma"""

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

        # Update product_id in ChromaDB chunk metadatas

        # Find all chunks where of document having document_id
        chroma_res = self.retriever.collection.get(
            where={"document_id": document_id},
            include=["metadatas"],
        )
        ids = chroma_res.get("ids", [])
        metadatas = chroma_res.get("metadatas", [])

        # Update product_id in every chunk of the document
        if ids and metadatas:
            updated_metas = []
            for m in metadatas:
                merged = dict(m or {})
                merged["product_id"] = product_id
                updated_metas.append(merged)

            self.retriever.collection.update(
                ids=ids,
                metadatas=updated_metas,
            )

        return DocumentDescription(
            document_id=doc.document_id,
            filename=doc.filename,
            product_id=doc.product_id,
            size_bytes=doc.size_bytes,
            sha256=doc.sha256,
            total_chunks=len(ids),
            status="indexed",
            created_at=doc.created_at,
        )

    def delete_document(self, document_id: str) -> DeleteDocumentResponse:
        """Delete document from ChromaDB, SQLite and MinIO"""

        # Find document having required document_id
        doc = self.db.scalar(select(Document).where(Document.document_id == document_id))
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document with ID '{document_id}' not found",
            )

        # Remove vectors from ChromaDB 
        chroma_res = self.retriever.collection.get(where={"document_id": document_id})
        deleted_chunks_count = len(chroma_res.get("ids", []))
        if deleted_chunks_count > 0:
            self.retriever.collection.delete(where={"document_id": document_id})
            logger.info("Purged %d vectors from ChromaDB for doc_id=%s", deleted_chunks_count, document_id)

        # Delete relational record from SQLite
        self.db.delete(doc)
        self.db.commit()
        logger.info("Deleted SQLite metadata record for doc_id=%s", document_id)

        # Remove raw binary from MinIO
        try:
            self.uploader.client.delete_object(
                Bucket=self.uploader.bucket_name,
                Key=document_id,
            )
            logger.info("Deleted MinIO binary object for doc_id=%s", document_id)
        except Exception as err:
            logger.warning("Failed to delete MinIO object for doc_id=%s: %s", document_id, err)

        return DeleteDocumentResponse(
            document_id=document_id,
            status="deleted",
            deleted_chunks=deleted_chunks_count,
            database_removed=True,
            storage_removed=True,
        )

