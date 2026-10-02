import logging
from io import BytesIO

import fitz
from docling.document_converter import DocumentConverter
from docling_core.types.doc import DoclingDocument
from docling_core.types.io import DocumentStream

from config import settings
from .base import BaseParser

logger = logging.getLogger(__name__)


class PdfPageRouter(BaseParser):
    """
    PDF per-page triage router class - Identifies presence of text/image/table in each page of the pdf

    Attributes:
        _docling_converter - Instance of DocumentConverter from docling

    Methods:
        can_handle()
        parse()
        _triage_page()
        _docling_full()
    """

    SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".pdf"})

    def __init__(self) -> None:
        self._docling_converter: DocumentConverter | None = None

    def can_handle(self, ext: str) -> bool:
        """Return True for .pdf"""

        return ext.lower() in self.SUPPORTED_EXTENSIONS

    def parse(self, file_bytes: bytes, filename: str, **kwargs) -> DoclingDocument:
            """Parse a PDF by routing each page to the optimal extraction backend."""

            if not settings.enable_pdf_page_router:
                logger.debug("PDF page router disabled — using full-document Docling conversion.")
                return self._docling_full(file_bytes, filename)

            # Triage each page of the pdf
            pdf = fitz.open(stream=file_bytes, filetype="pdf")
            for page in pdf:
                routes = self._triage_page(page)
                logger.debug("Page %d → routes=%s", page.number, routes)
            pdf.close()
    
            return self._docling_full(file_bytes, filename)

    def _triage_page(self, page: fitz.Page) -> list[str]:
        """Classify a single PDF page into one or more routing categories."""

        routes: list[str] = []

        # Tables
        if len(page.find_tables().tables) > 0:
            routes.append("table")

        # Images
        has_image = len(page.get_images()) > 0
        text_len = len(page.get_text())

        if has_image and text_len < settings.pdf_min_text_chars_for_text_route:
            routes.append("image")

        return routes or ["text"]

    def _docling_full(
        self, file_bytes: bytes, filename: str, use_ocr: bool = True
    ) -> DoclingDocument:
        """Full-document parsing using DocumentConverter"""

        if self._docling_converter is None:
            self._docling_converter = DocumentConverter()
        
        converter = self._docling_converter
        stream = DocumentStream(name=filename, stream=BytesIO(file_bytes))
        result = converter.convert(stream)

        return result.document
    
