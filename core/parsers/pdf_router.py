"""
core/parsers/pdf_router.py — PdfPageRouter for .pdf files.

Implements per-page triage for PDF documents, routing each page to the
optimal extraction backend:

  - PyMuPDF4LLM : text-heavy pages (fast markdown extraction)
  - Docling      : table-bearing pages (structural extraction)
  - SmolVLM      : image/diagram-heavy pages (via Docling VLM pipeline)

Phase 1:
  - Class definition: PdfPageRouter(BaseParser)
  - can_handle(): Handles .pdf
  - _single_page_bytes(): Extracts single-page PDF bytes in-memory using fitz
  - _triage_page(): Inspects page character count, table count, and image count
  - Fallback to _docling_full when settings.enable_pdf_page_router is False
"""
import logging
from io import BytesIO

import fitz  # PyMuPDF
from docling.document_converter import DocumentConverter
from docling_core.types.doc import DoclingDocument
from docling_core.types.io import DocumentStream

from config import settings
from .base import BaseParser

logger = logging.getLogger(__name__)


class PdfPageRouter(BaseParser):
    """
    v5.1 PDF per-page triage router.

    Each page is independently classified via _triage_page(), which returns a
    list of routes. Pages with only "text" go to PyMuPDF4LLM. Pages with
    "table" go to Docling for structural extraction. Pages with "image" go to
    SmolVLM. Pages with both "table" and "image" run Docling for table content
    and _picture_descriptions_only() for figure captions — merged so neither
    is dropped.

    Falls back to full-document Docling conversion when
    settings.enable_pdf_page_router is False.

    Attributes:
        SUPPORTED_EXTENSIONS: Frozenset of lowercase dot-prefixed extensions.
    """

    SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".pdf"})

    def __init__(self) -> None:
        self._docling_converter: DocumentConverter | None = None
        self._vlm_converter: DocumentConverter | None = None
        self._text_layer_converter: DocumentConverter | None = None
        self._vlm_converter_text: DocumentConverter | None = None
        self._vocab = None
        self._ocr_pages: set[int] = set()

    # ------------------------------------------------------------------
    # BaseParser interface
    # ------------------------------------------------------------------

    def can_handle(self, ext: str) -> bool:
        """Return True for .pdf"""

        return ext.lower() in self.SUPPORTED_EXTENSIONS

    def parse(self, file_bytes: bytes, filename: str, **kwargs) -> DoclingDocument:
            """Parse a PDF by routing each page to the optimal extraction backend."""

            if not settings.enable_pdf_page_router:
                logger.debug("PDF page router disabled — using full-document Docling conversion.")
                return self._docling_full(file_bytes, filename)
    
            pdf = fitz.open(stream=file_bytes, filetype="pdf")
            for page in pdf:
                routes = self._triage_page(page)
                logger.debug("Page %d → routes=%s", page.number, routes)
            pdf.close()
    
            # In Phase 1 skeleton, full-document fallback is used after per-page triage.
            # Phase 2 onward wires the per-page extraction backends and page merge.
            return self._docling_full(file_bytes, filename)

    # ------------------------------------------------------------------
    # Single-page extraction helper
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

    def _triage_page(self, page: fitz.Page) -> list[str]:
        """Classify a single PDF page into one or more routing categories.

        Returns a list so a page can simultaneously be ``'table'`` and
        ``'image'``. A page with only text returns ``['text']``.

        Args:
            page: A ``fitz.Page`` object from an open ``fitz.Document``.

        Returns:
            list[str]: Non-empty list containing any of ``'text'``,
                       ``'table'``, ``'image'``.
        """
        routes: list[str] = []

        # Table detection — Docling gives the best structural extraction
        if len(page.find_tables().tables) > 0:
            routes.append("table")

        # Image / low-text detection
        # Compare against an absolute character count rather than a ratio
        # against page area.
        has_image = len(page.get_images()) > 0
        text_len = len(page.get_text())

        if has_image and text_len < settings.pdf_min_text_chars_for_text_route:
            routes.append("image")

        # Default: fast PyMuPDF4LLM extraction
        return routes or ["text"]

    # ------------------------------------------------------------------
    # Docling full document fallback
    # ------------------------------------------------------------------

    def _docling_full(
        self, file_bytes: bytes, filename: str, use_ocr: bool = True
    ) -> DoclingDocument:
        """Full-document Docling conversion.

        Used as the fallback path when enable_pdf_page_router is False,
        and as the baseline fallback in the triage path.

        Args:
            file_bytes: Raw PDF bytes.
            filename:   Original filename for DocumentStream naming.
            use_ocr:    Whether to perform OCR if needed.

        Returns:
            DoclingDocument: Converted document.
        """
        if self._docling_converter is None:
            self._docling_converter = DocumentConverter()
        converter = self._docling_converter
        stream = DocumentStream(name=filename, stream=BytesIO(file_bytes))
        result = converter.convert(stream)
        return result.document
    
