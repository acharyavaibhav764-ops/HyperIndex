import inspect
from typing import Any
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import Chunker, Embeddings, Parser, Retriever, Uploader
from core.hasher import calculate_sha256
from db.models import Document, DocumentVersion
from schemas.document import DocumentIngestItem, DocumentIngestResponse


class IngestionService:
    """
    Class to run the ingestion pipeline across object storage, SQL metadata,
    and vector embeddings.

    Attributes:
        uploader
        parser 
        chunker
        embeddings
        retriever
        db
    
    Methods:
        ingest_files()
    """

    def __init__(
        self,
        uploader: Uploader,
        parser: Parser,
        chunker: Chunker,
        embeddings: Embeddings,
        retriever: Retriever,
        db: Session | None = None,
    ):
        self.uploader = uploader
        self.parser = parser
        self.chunker = chunker
        self.embeddings = embeddings
        self.retriever = retriever
        self.db = db

    def _read_file_bytes(self, file: Any) -> bytes:
        """Safely read raw bytes from UploadFile, FakeFile, or mock objects."""
        if hasattr(file, "file") and hasattr(file.file, "read"):
            content = file.file.read()
            file.file.seek(0)
            if isinstance(content, (bytes, bytearray)):
                return bytes(content)
        if hasattr(file, "read") and not inspect.iscoroutinefunction(file.read):
            try:
                content = file.read()
                if hasattr(file, "seek"):
                    file.seek(0)
                if isinstance(content, (bytes, bytearray)):
                    return bytes(content)
            except Exception:
                pass
        return b""

    def ingest_files(
        self, files: list[UploadFile], product_id: str = "default"
    ) -> DocumentIngestResponse:
        """Handles uploading, parsing, chunking, embedding, versioning and duplicate detection."""

        if not files:
            raise ValueError("At least one file is required")

        ingested_items: list[DocumentIngestItem] = []

        for file in files:
            content = self._read_file_bytes(file)
            file_hash = calculate_sha256(content)

            # Check duplicate detection if database session is active
            if self.db is not None:
                existing_version = self.db.scalar(
                    select(DocumentVersion)
                    .join(Document)
                    .where(
                        DocumentVersion.sha256 == file_hash,
                        Document.product_id == product_id,
                    )
                )
                
                if existing_version is not None:
                    existing_document = self.db.get(Document, existing_version.document_id)
                    ingested_items.append(
                        DocumentIngestItem(
                            document_id=existing_version.document_id,
                            product_id=existing_document.product_id if existing_document else product_id,
                            version_id=existing_version.version_id,
                            version_message=(
                                f"Duplicate file: this is already version "
                                f"{existing_version.version_number}"
                            ),
                            filename=getattr(file, "filename", None) or existing_version.filename,
                            size_bytes=len(content),
                            collection=self.retriever.collection_name,
                            total_chunks=0,
                            status="duplicate",
                        )
                    )
                    continue

            # Upload files to object storage
            uploaded_docs = self.uploader.upload_files([file])
            if not uploaded_docs:
                continue
            item = uploaded_docs[0]
            doc_id = item["document_id"]
            filename = item["filename"]
            size_bytes = item["size_bytes"]

            # Download and parse text pages
            raw_content, _ = self.uploader.download_file(doc_id)
            pages = self.parser.parse(raw_content, filename)

            # Chunk text and attach metadata
            chunks, metadatas, chunk_ids = self.chunker.split(pages, doc_id, filename)

            # Generate vector embeddings
            vectors = self.embeddings.embed(chunks)

            # Persist to ChromaDB
            self.retriever.upsert(
                ids=chunk_ids,
                documents=chunks,
                metadatas=metadatas,
                embeddings=vectors,
            )

            version_id = str(uuid4())
            if self.db is not None:
                document = Document(
                    document_id=doc_id,
                    product_id=product_id,
                    title=filename,
                    current_version_id=version_id,
                )
                version = DocumentVersion(
                    version_id=version_id,
                    document_id=doc_id,
                    version_number=1,
                    filename=filename,
                    sha256=file_hash,
                    normalized_hash=None,
                    object_key=doc_id,
                    status="indexed",
                )
                self.db.add(document)
                self.db.add(version)
                self.db.commit()

            # Append to list of ingested items
            ingested_items.append(
                DocumentIngestItem(
                    document_id=doc_id,
                    product_id=product_id,
                    version_id=version_id,
                    version_message="You are uploading version 1",
                    filename=filename,
                    size_bytes=size_bytes,
                    collection=self.retriever.collection_name,
                    total_chunks=len(chunks),
                    status="indexed",
                )
            )

        return DocumentIngestResponse(
            message="Documents processed successfully",
            count=len(ingested_items),
            documents=ingested_items,
        )
