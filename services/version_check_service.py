"""
Version-check service: dry-run duplicate / version detection.

No files are uploaded to MinIO, indexed in Qdrant, or embedded.
Fast format-aware text extractors (python-docx for DOCX, pypdf for PDF, text decoders)
are used to extract text and compute the 84-slot MinHash sketch, which is then compared
against the stored MinHash sketches of existing active versions in SQL.
"""
from __future__ import annotations

import io
import logging
from typing import Any

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.dedup import MinHashDeduplicator
from core.uploader import build_storage_path, make_family_id
from db.models import Document
from schemas.check import DocumentCheckItem, DocumentCheckResponse
from utils.hasher import calculate_sha256

logger = logging.getLogger(__name__)


class VersionCheckService:
    """
    Classify uploaded files as exact duplicates, new versions, or new
    documents — without touching MinIO, Qdrant, or running heavy ML models.

    Attributes:
        db:            SQLAlchemy session (read-only within this service).
        deduplicator:  MinHashDeduplicator shared with IngestionService.

    Methods:
        check_files()
    """

    def __init__(
        self,
        db: Session,
        deduplicator: MinHashDeduplicator | None = None,
    ) -> None:
        self.db = db
        self.deduplicator = deduplicator or MinHashDeduplicator()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_bytes(file: Any) -> bytes:
        """Read raw bytes from an UploadFile or file-like object."""
        if hasattr(file, "file") and hasattr(file.file, "read"):
            data = file.file.read()
            file.file.seek(0)
            return bytes(data) if isinstance(data, (bytes, bytearray)) else b""
        if hasattr(file, "read"):
            try:
                data = file.read()
                if hasattr(file, "seek"):
                    file.seek(0)
                return bytes(data) if isinstance(data, (bytes, bytearray)) else b""
            except Exception:
                pass
        return b""

    @staticmethod
    def _extract_text_fast(content: bytes, filename: str) -> str:
        """
        Fast, format-aware text extraction for dry-run checks.
        Extracts clean text from Word, PDF, or text files in milliseconds.
        """
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

        # Microsoft Word (.docx)
        if ext == "docx":
            try:
                import docx
                doc = docx.Document(io.BytesIO(content))
                parts = [p.text for p in doc.paragraphs if p.text]
                for t in doc.tables:
                    for r in t.rows:
                        for c in r.cells:
                            if c.text:
                                parts.append(c.text)
                return "\n".join(parts)
            except Exception as e:
                logger.warning("Fast docx extraction failed for %s: %s", filename, e)

        # PDF documents (.pdf)
        if ext == "pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(io.BytesIO(content))
                pages_text = [p.extract_text() or "" for p in reader.pages]
                return "\n".join(pages_text)
            except Exception as e:
                logger.warning("Fast pdf extraction failed for %s: %s", filename, e)

        # Plain text / Markdown (.txt, .md, etc.)
        for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
            try:
                return content.decode(enc)
            except Exception:
                pass

        return content.decode("utf-8", errors="replace")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_files(
        self,
        files: list[UploadFile],
        product_id: str,
    ) -> DocumentCheckResponse:
        """
        Classify each file without storing anything.

        Returns:
            DocumentCheckResponse with one DocumentCheckItem per file.
        """
        results: list[DocumentCheckItem] = []

        # Pre-fetch all is_latest docs for this product once (single DB round-trip)
        latest_docs: list[Document] = self.db.scalars(
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

        for file in files:
            filename = getattr(file, "filename", None) or "unknown"
            content = self._read_bytes(file)
            size_bytes = len(content)
            file_hash = calculate_sha256(content)

            # --------------------------------------------------------------
            # TIER 1: Exact match — search globally (all products, all versions)
            # --------------------------------------------------------------
            existing_doc: Document | None = self.db.scalar(
                select(Document).where(Document.sha256 == file_hash)
            )

            if existing_doc is not None:
                results.append(
                    DocumentCheckItem(
                        filename=filename,
                        size_bytes=size_bytes,
                        sha256=file_hash,
                        status="exact_duplicate",
                        matched_document_id=existing_doc.document_id,
                        matched_filename=existing_doc.filename,
                        matched_product_id=existing_doc.product_id,
                        matched_doc_family_id=existing_doc.doc_family_id,
                        matched_version=existing_doc.version,
                        would_be_version=None,
                        similarity_score=None,
                        storage_path_preview=None,
                    )
                )
                continue

            # --------------------------------------------------------------
            # TIER 2: Near-duplicate — MinHash against product's latest docs
            # --------------------------------------------------------------
            text = self._extract_text_fast(content, filename)
            new_sketch = self.deduplicator.compute_sketch(text)
            best_id, best_score = self.deduplicator.best_match(new_sketch, candidates)

            if best_id and best_score >= self.deduplicator.threshold:
                matched: Document = next(d for d in latest_docs if d.document_id == best_id)
                next_version = matched.version + 1
                preview_path = build_storage_path(
                    product_id, matched.doc_family_id, next_version, filename
                )
                results.append(
                    DocumentCheckItem(
                        filename=filename,
                        size_bytes=size_bytes,
                        sha256=file_hash,
                        status="new_version",
                        matched_document_id=matched.document_id,
                        matched_filename=matched.filename,
                        matched_product_id=matched.product_id,
                        matched_doc_family_id=matched.doc_family_id,
                        matched_version=matched.version,
                        would_be_version=next_version,
                        similarity_score=round(best_score, 4),
                        storage_path_preview=preview_path,
                    )
                )
                continue

            # --------------------------------------------------------------
            # No match — brand new document family
            # --------------------------------------------------------------
            new_family_id = make_family_id(filename)
            preview_path = build_storage_path(product_id, new_family_id, 1, filename)
            results.append(
                DocumentCheckItem(
                    filename=filename,
                    size_bytes=size_bytes,
                    sha256=file_hash,
                    status="new_document",
                    matched_document_id=None,
                    matched_filename=None,
                    matched_product_id=None,
                    matched_doc_family_id=None,
                    matched_version=None,
                    would_be_version=1,
                    similarity_score=None,
                    storage_path_preview=preview_path,
                )
            )

        return DocumentCheckResponse(
            product_id=product_id,
            count=len(results),
            results=results,
        )
