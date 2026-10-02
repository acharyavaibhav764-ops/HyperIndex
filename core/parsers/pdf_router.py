import logging
from io import BytesIO

import fitz
import pymupdf4llm
from docling.datamodel.base_models import InputFormat
from docling.document_converter import DocumentConverter
from docling_core.types.doc import BoundingBox, DoclingDocument, ProvenanceItem
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

        pdf = fitz.open(stream=file_bytes, filetype="pdf")
        page_markdowns: list[str] = []

        for page in pdf:
            routes = self._triage_page(page)
            logger.debug("Page %d → routes=%s", page.number, routes)

            page_markdowns.append(self._page_markdown(pdf, page.number))

        pdf.close()
        return self._merge_pages(page_markdowns, filename)

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

    @staticmethod
    def _page_markdown(pdf: fitz.Document, page_no: int, use_ocr: bool = False) -> str:
        """pymupdf4llm markdown for one page, without running footers or OCR."""

        attempts = (
            {"header": False, "footer": False, "use_ocr": use_ocr},
            {"header": False, "footer": False},
            {},
        )

        for kw in attempts:
            try:
                return pymupdf4llm.to_markdown(pdf, pages=[page_no], **kw)
            except TypeError:
                continue
        return pymupdf4llm.to_markdown(pdf, pages=[page_no])

    def _merge_pages(self, page_markdowns: list[str], filename: str) -> DoclingDocument:
        """Combine per-page markdown strings into a single DoclingDocument with page provenance stamped."""

        combined = DoclingDocument(name=filename.rsplit(".", 1)[0])
        converter = DocumentConverter(allowed_formats=[InputFormat.MD])

        for page_no, md in enumerate(page_markdowns, start=1):
            stream = DocumentStream(
                name=f"page_{page_no}.md",
                stream=BytesIO(md.encode("utf-8")),
            )
            page_doc = converter.convert(stream).document
            prov = ProvenanceItem(
                page_no=page_no,
                bbox=BoundingBox(l=0, t=0, r=0, b=0),
                charspan=(0, 0),
            )
            for item, _ in page_doc.iterate_items():
                if hasattr(item, "prov"):
                    item.prov = [prov]
            combined.add_document(page_doc)

        return combined

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

