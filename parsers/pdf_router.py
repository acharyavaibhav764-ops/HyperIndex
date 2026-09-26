"""
parsers/pdf_router.py — PdfPageRouter for .pdf files.

Implements per-page triage for PDF documents, routing each page to the
optimal extraction backend:

  - PyMuPDF4LLM : text-heavy pages (fast markdown extraction)
  - Docling      : table-bearing pages (structural extraction)
  - SmolVLM      : image/diagram-heavy pages (via Docling VLM pipeline)

Triage heuristics (all tunable via config):
  - Tables  : page.find_tables().tables is non-empty → "table"
  - Images  : page.get_images() is non-empty AND text_ratio < threshold → "image"
  - Default : "text"

When settings.enable_pdf_page_router is False (default), parse() falls
back to full-document Docling conversion — identical to PdfStubParser
behaviour. This makes the v5 router a drop-in replacement with zero
risk during initial rollout.

v5 scope note
-------------
_docling_page() and _smolvlm_page() currently process the full document
rather than a single page because Docling 2.x does not yet expose a
page-scoped export API. True per-page isolation is planned for v5.1.
DeepSeek-OCR2 integration is deferred to v6.
"""
import logging
from io import BytesIO

import fitz  # PyMuPDF
import pymupdf4llm
from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import InputFormat
from docling_core.types.doc import DoclingDocument
from docling_core.types.io import DocumentStream

from config import settings
from .base import BaseParser
from .docling_parser import _build_vlm_converter

logger = logging.getLogger(__name__)


class PdfPageRouter(BaseParser):
    """
    v5 PDF per-page triage router.

    Each page is independently classified as text-heavy, table-bearing, or
    image-dominant.  The classification drives routing to PyMuPDF4LLM,
    Docling, or SmolVLM respectively.

    Falls back to full-document Docling conversion when
    settings.enable_pdf_page_router is False.

    Attributes:
        SUPPORTED_EXTENSIONS: Frozenset of lowercase dot-prefixed extensions.
    """

    SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".pdf"})

    def __init__(self) -> None:
        self._docling_converter: DocumentConverter | None = None
        self._vlm_converter: DocumentConverter | None = None

    # ------------------------------------------------------------------
    # BaseParser interface
    # ------------------------------------------------------------------

    def can_handle(self, ext: str) -> bool:
        """Return True for .pdf extension.

        Args:
            ext: Lowercase, dot-prefixed extension, e.g. ``'.pdf'``.
        """
        return ext.lower() in self.SUPPORTED_EXTENSIONS

    def parse(self, file_bytes: bytes, filename: str, **kwargs) -> DoclingDocument:
        """Parse a PDF by routing each page to the optimal extraction backend.

        When ``settings.enable_pdf_page_router`` is False, falls back to
        full-document Docling conversion (stub-compatible path).

        Args:
            file_bytes: Raw binary content of the PDF file.
            filename:   Original filename used for DocumentStream naming.
            **kwargs:   Unused; reserved for future options.

        Returns:
            DoclingDocument: Structured document ready for chunking.
        """
        if not settings.enable_pdf_page_router:
            # Fallback path: identical to PdfStubParser behaviour
            logger.debug("PDF page router disabled — using full-document Docling conversion.")
            return self._docling_full(file_bytes, filename)

        pdf = fitz.open(stream=file_bytes, filetype="pdf")
        page_markdowns: list[str] = []

        for page in pdf:
            route = self._triage_page(page)
            logger.debug("Page %d → route=%s", page.number, route)

            if route == "text":
                md = pymupdf4llm.to_markdown(pdf, pages=[page.number])
                page_markdowns.append(md)
            elif route == "table":
                # Extract just this page so _docling_page does not process the full doc
                single_bytes = self._single_page_bytes(pdf, page.number)
                md = self._docling_page(single_bytes, filename, page.number)
                page_markdowns.append(md)
            else:  # "image"
                # Extract just this page so _smolvlm_page does not process the full doc
                single_bytes = self._single_page_bytes(pdf, page.number)
                md = self._smolvlm_page(single_bytes, filename, page.number)
                page_markdowns.append(md)

        pdf.close()
        return self._merge_pages(page_markdowns, filename)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _single_page_bytes(pdf: fitz.Document, page_no: int) -> bytes:
        """Extract a single page from an open fitz.Document as standalone PDF bytes.

        Args:
            pdf:     Open fitz.Document (full PDF).
            page_no: Zero-indexed page number to extract.

        Returns:
            bytes: A valid single-page PDF containing only the requested page.
        """
        single = fitz.open()
        single.insert_pdf(pdf, from_page=page_no, to_page=page_no)
        data = single.tobytes()
        single.close()
        return data

    # ------------------------------------------------------------------
    # Triage
    # ------------------------------------------------------------------

    def _triage_page(self, page: fitz.Page) -> str:
        """Classify a single PDF page into a routing category.

        Args:
            page: A ``fitz.Page`` object from an open ``fitz.Document``.

        Returns:
            str: One of ``'text'``, ``'table'``, or ``'image'``.
        """
        # Table detection takes priority — Docling gives the best table output
        if len(page.find_tables().tables) > 0:
            return "table"

        # Image / low-text pages go to SmolVLM
        has_image = len(page.get_images()) > 0
        area = page.rect.width * page.rect.height
        text_len = len(page.get_text())
        text_ratio = text_len / area if area > 0 else 0.0

        if has_image and text_ratio < settings.pdf_text_ratio_threshold:
            return "image"

        # Default: fast PyMuPDF4LLM extraction
        return "text"

    # ------------------------------------------------------------------
    # Per-tier extractors
    # ------------------------------------------------------------------

    def _docling_full(self, file_bytes: bytes, filename: str) -> DoclingDocument:
        """Full-document Docling conversion.

        Used as the fallback path when enable_pdf_page_router is False,
        and as the per-page table extraction tier in the triage path.

        Args:
            file_bytes: Raw PDF bytes.
            filename:   Original filename for DocumentStream naming.

        Returns:
            DoclingDocument: Converted document.
        """
        if self._docling_converter is None:
            self._docling_converter = DocumentConverter()
        stream = DocumentStream(name=filename, stream=BytesIO(file_bytes))
        result = self._docling_converter.convert(stream)
        return result.document

    def _docling_page(self, file_bytes: bytes, filename: str, page_no: int) -> str:
        """Extract a table-bearing page via Docling and return its markdown.

        v5 scope note: exports the full document, not just page_no.
        True page-scoped export is deferred to v5.1 pending Docling API support.

        Args:
            file_bytes: Raw PDF bytes.
            filename:   Original filename.
            page_no:    Zero-indexed page number (informational only for now).

        Returns:
            str: Markdown string for the page's content.
        """
        doc = self._docling_full(file_bytes, filename)
        return doc.export_to_markdown()

    def _smolvlm_page(self, file_bytes: bytes, filename: str, page_no: int) -> str:
        """Describe an image-heavy page using SmolVLM via Docling VLM pipeline.

        Reuses ``_build_vlm_converter()`` from docling_parser — the same
        SmolVLM-256M-Instruct preset already used for DOCX/PPTX picture description.

        Falls back to PyMuPDF4LLM text extraction if VLM conversion fails.

        v5 scope note: processes the full document, not just page_no.
        True per-page image rendering + inference is deferred to v5.1.

        Args:
            file_bytes: Raw PDF bytes.
            filename:   Original filename.
            page_no:    Zero-indexed page number (informational only for now).

        Returns:
            str: Markdown string with figure descriptions injected.
        """
        try:
            if self._vlm_converter is None:
                self._vlm_converter = _build_vlm_converter()
            stream = DocumentStream(name=filename, stream=BytesIO(file_bytes))
            result = self._vlm_converter.convert(stream)
            return result.document.export_to_markdown()
        except Exception as exc:
            logger.warning(
                "SmolVLM failed for page %d of %s: %s. Falling back to PyMuPDF4LLM.",
                page_no, filename, exc,
            )
            pdf = fitz.open(stream=file_bytes, filetype="pdf")
            md = pymupdf4llm.to_markdown(pdf, pages=[page_no])
            pdf.close()
            return md

    # ------------------------------------------------------------------
    # Result assembly
    # ------------------------------------------------------------------

    def _merge_pages(self, page_markdowns: list[str], filename: str) -> DoclingDocument:
        """Combine per-page markdown strings into a single DoclingDocument.

        Page markdowns are joined with a horizontal-rule separator then
        converted back to a DoclingDocument via Docling's Markdown pipeline.

        Args:
            page_markdowns: List of markdown strings, one per page.
            filename:       Original PDF filename (used to derive MD stream name).

        Returns:
            DoclingDocument: Merged structured document ready for chunking.
        """
        combined_md = "\n\n---\n\n".join(page_markdowns)
        md_filename = filename.rsplit(".", 1)[0] + ".md"

        converter = DocumentConverter(
            allowed_formats=[InputFormat.MD],
        )
        stream = DocumentStream(
            name=md_filename,
            stream=BytesIO(combined_md.encode("utf-8")),
        )
        result = converter.convert(stream)
        return result.document
