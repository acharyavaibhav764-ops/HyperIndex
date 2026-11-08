import inspect
import logging
from typing import Any
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import Chunker, Embeddings, ParserRouter, Retriever, Uploader
from core.dedup import MinHashDeduplicator
from core.uploader import build_storage_path, make_family_id
from db.models import Document, Product
from schemas.ingestion import DocumentIngestItem, DocumentIngestResponse
from utils.hasher import calculate_sha256

logger = logging.getLogger(__name__)


class IngestionService:
    """
    Run the ingestion pipeline across object storage, SQL metadata,
    vector embeddings, with two-tier SHA-256 / MinHash versioning.

    Two-Tier deduplication
    ----------------------
    Tier 1 – Global exact match (SHA-256):
        If the raw bytes already exist anywhere in the system the file is
        immediately rejected as a duplicate.  Zero parsing, zero embedding.

    Tier 2 – Product-scoped near-duplicate (MinHash):
        The parsed text is fingerprinted with an 84-slot MinHash sketch.
        Only the ``is_latest = True`` documents belonging to the same
        ``product_id`` are compared.  The highest-scoring candidate above
        the similarity threshold is treated as the previous version:
        its ``is_latest`` flag is cleared in SQLite and Qdrant, and the new
        file is stored as ``version = parent.version + 1`` inside the same
        document family folder in MinIO.

    MinIO hierarchy
    ---------------
    ``products/{product_id}/{doc_family_id}/v{version}/{filename}``

    Attributes:
        uploader
        parser
        chunker
        embeddings
        retriever
        db
        deduplicator

    Methods:
        ingest_files()
    """

    def __init__(
        self,
        uploader: Uploader,
        parser: ParserRouter,
        chunker: Chunker,
        embeddings: Embeddings,
        retriever: Retriever,
        db: Session | None = None,
        deduplicator: MinHashDeduplicator | None = None,
    ):
        self.uploader = uploader
        self.parser = parser
        self.chunker = chunker
        self.embeddings = embeddings
        self.retriever = retriever
        self.db = db
        self.deduplicator = deduplicator or MinHashDeduplicator()

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

    def _full_text_from_doc(self, doc, content: bytes = b"", filename: str = "") -> str:
        """Extract a plain-text string from a DoclingDocument (or fallback) for MinHash."""
        # 1. Try Docling markdown serialization
        try:
            md = doc.export_to_markdown()
            if md and md.strip():
                return md
        except Exception:
            pass

        # 2. Try Docling plain-text serialization
        try:
            txt = doc.export_to_text()
            if txt and txt.strip():
                return txt
        except Exception:
            pass

        # 3. Format-aware fast extractor (python-docx for DOCX, pypdf for PDF)
        if content and filename:
            try:
                from services.version_check_service import VersionCheckService
                fast_txt = VersionCheckService._extract_text_fast(content, filename)
                if fast_txt and fast_txt.strip():
                    return fast_txt
            except Exception:
                pass

        # 4. Fallback: harvest readable text directly from doc.texts and tables
        parts: list[str] = []
        for item in getattr(doc, "texts", []):
            t = (getattr(item, "text", "") or "").strip()
            if t:
                parts.append(t)
        for table in getattr(doc, "tables", []):
            try:
                for cell in table.data.table_cells:
                    t = (getattr(cell, "text", "") or "").strip()
                    if t:
                        parts.append(t)
            except Exception:
                pass
        return "\n".join(parts)

    def _archive_parent_in_qdrant(self, parent_document_id: str) -> None:
        """Mark every Qdrant chunk of the parent document as is_latest=False."""
        from qdrant_client import models as qdrant_models

        try:
            self.retriever.client.set_payload(
                collection_name=self.retriever.collection_name,
                payload={"is_latest": False},
                points=qdrant_models.Filter(
                    must=[
                        qdrant_models.FieldCondition(
                            key="document_id",
                            match=qdrant_models.MatchValue(value=parent_document_id),
                        )
                    ]
                ),
                wait=True,
            )
        except Exception as exc:
            logger.warning(
                "Could not update Qdrant payloads for parent doc_id=%s: %s",
                parent_document_id,
                exc,
            )

    def ingest_files(
        self, files: list[UploadFile], product_id: str = "default"
    ) -> DocumentIngestResponse:
        """
        Handle uploading, parsing, chunking, embedding, and versioned
        deduplication for every file in *files*.

        Returns a DocumentIngestResponse whose items carry full versioning
        metadata (version, doc_family_id, parent_id, storage_path,
        similarity_score).
        """
        if not files:
            raise ValueError("At least one file is required")

        ingested_items: list[DocumentIngestItem] = []

        # Auto-register product if it does not yet exist
        if self.db is not None and product_id:
            existing_prod = self.db.scalar(
                select(Product).where(Product.product_id == product_id)
            )
            if existing_prod is None:
                new_prod = Product(
                    product_id=product_id,
                    name=product_id,
                    description=f"Auto-registered product for {product_id}",
                )
                self.db.add(new_prod)
                self.db.flush()

        for file in files:
            filename = getattr(file, "filename", None) or "unknown"
            content = self._read_file_bytes(file)
            file_hash = calculate_sha256(content)

            # ----------------------------------------------------------
            # TIER 1: Global exact-match check (SHA-256, cross-product)
            # ----------------------------------------------------------
            if self.db is not None:
                existing_doc = self.db.scalar(
                    select(Document).where(Document.sha256 == file_hash)
                )
                if existing_doc is not None:
                    logger.info(
                        "Exact duplicate detected | sha256=%s | existing_doc_id=%s",
                        file_hash[:12],
                        existing_doc.document_id,
                    )
                    ingested_items.append(
                        DocumentIngestItem(
                            document_id=existing_doc.document_id,
                            product_id=existing_doc.product_id,
                            filename=filename,
                            size_bytes=len(content),
                            collection=self.retriever.collection_name,
                            total_chunks=0,
                            status="duplicate",
                            version=existing_doc.version,
                            doc_family_id=existing_doc.doc_family_id,
                            parent_id=existing_doc.parent_id,
                            storage_path=existing_doc.storage_path,
                            similarity_score=None,
                        )
                    )
                    continue

            # ----------------------------------------------------------
            # Parse in-memory (Docling / TextParser — untouched)
            # ----------------------------------------------------------
            doc = self.parser.parse(content, filename)
            full_text = self._full_text_from_doc(doc, content=content, filename=filename)

            # ----------------------------------------------------------
            # TIER 2: Product-scoped near-duplicate check (MinHash)
            # Only compares against is_latest=True docs for this product
            # ----------------------------------------------------------
            new_sketch = self.deduplicator.compute_sketch(full_text)
            parent_doc: Document | None = None
            version = 1
            doc_family_id: str = make_family_id(filename)
            similarity_score: float | None = None

            if self.db is not None:
                latest_docs = self.db.scalars(
                    select(Document).where(
                        Document.product_id == product_id,
                        Document.is_latest == True,  # noqa: E712
                    )
                ).all()

                candidates = [
                    (d.document_id, d.minhash_sketch)
                    for d in latest_docs
                    if d.minhash_sketch
                ]

                best_id, best_score = self.deduplicator.best_match(new_sketch, candidates)

                if best_id and best_score >= self.deduplicator.threshold:
                    parent_doc = next(d for d in latest_docs if d.document_id == best_id)
                    version = parent_doc.version + 1
                    doc_family_id = parent_doc.doc_family_id
                    similarity_score = round(best_score, 4)

                    # Archive the parent in SQLite
                    parent_doc.is_latest = False
                    self.db.flush()

                    # Archive the parent's chunks in Qdrant
                    self._archive_parent_in_qdrant(parent_doc.document_id)

                    logger.info(
                        "New version detected | family=%s | v%d→v%d | score=%.4f",
                        doc_family_id,
                        parent_doc.version,
                        version,
                        best_score,
                    )

            # ----------------------------------------------------------
            # Build hierarchical MinIO key & upload directly from memory
            # ----------------------------------------------------------
            doc_id = str(uuid4())
            storage_path = build_storage_path(product_id, doc_family_id, version, filename)

            self.uploader.upload_file_bytes(
                content=content,
                object_key=storage_path,
                filename=filename,
                content_type=getattr(file, "content_type", None) or "application/octet-stream",
                extra_metadata={
                    "product_id": product_id,
                    "doc_family_id": doc_family_id,
                    "version": str(version),
                    "is_latest": "true",
                    "parent_id": parent_doc.document_id if parent_doc else "",
                },
            )

            # ----------------------------------------------------------
            # Chunk, embed, and upsert to Qdrant
            # ----------------------------------------------------------
            chunks, metadatas, chunk_ids = self.chunker.split(doc, doc_id, filename)

            for meta in metadatas:
                meta["product_id"] = product_id
                meta["doc_family_id"] = doc_family_id
                meta["version"] = version
                meta["is_latest"] = True

            vectors = self.embeddings.embed(chunks)

            self.retriever.upsert(
                ids=chunk_ids,
                documents=chunks,
                metadatas=metadatas,
                embeddings=vectors,
            )

            # ----------------------------------------------------------
            # Persist versioned metadata to SQL
            # ----------------------------------------------------------
            if self.db is not None:
                document = Document(
                    document_id=doc_id,
                    product_id=product_id,
                    filename=filename,
                    sha256=file_hash,
                    size_bytes=len(content),
                    doc_family_id=doc_family_id,
                    version=version,
                    parent_id=parent_doc.document_id if parent_doc else None,
                    is_latest=True,
                    storage_path=storage_path,
                    minhash_sketch=new_sketch,
                )
                self.db.add(document)
                self.db.commit()

            status_label = "new_version" if parent_doc else "indexed"
            ingested_items.append(
                DocumentIngestItem(
                    document_id=doc_id,
                    product_id=product_id,
                    filename=filename,
                    size_bytes=len(content),
                    collection=self.retriever.collection_name,
                    total_chunks=len(chunks),
                    status=status_label,
                    version=version,
                    doc_family_id=doc_family_id,
                    parent_id=parent_doc.document_id if parent_doc else None,
                    storage_path=storage_path,
                    similarity_score=similarity_score,
                )
            )

        return DocumentIngestResponse(
            message="Documents processed successfully",
            count=len(ingested_items),
            documents=ingested_items,
        )
