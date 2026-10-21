import io
import logging

import fitz  # PyMuPDF
from docling.datamodel.base_models import InputFormat
from docling.document_converter import DocumentConverter
from docling_core.types.doc import DoclingDocument
from docling_core.types.io import DocumentStream

from ..base import BaseParser
from .backends import (
    DoclingTableBackend,
    PyMuPdfBackend,
    VlmPictureBackend,
    merge_pages_to_docling,
    single_page_bytes,
)
from .postprocess import PdfPostProcessor
from .transforms.cellmarks import scan_legend
from .transforms.cleanup import build_vocab
from .triage import PageRoute, PageTriager

logger = logging.getLogger(__name__)


class PdfParser(BaseParser):
    """
    Parse PDF documents into a DoclingDocument using a per-page triage architecture.

    Text-heavy pages are processed via PyMuPDF4LLM for fast markdown generation.
    Table pages are routed through Docling for high-fidelity table structures.
    Image/diagram pages are routed through SmolVLM for visual descriptions.
    """

    SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".pdf"})

    def __init__(self) -> None:
        """Initialize parser and lazy backends."""

        self.triager = PageTriager()
        self.pymupdf_backend = PyMuPdfBackend()
        self.docling_backend = DoclingTableBackend()
        self.vlm_backend = VlmPictureBackend()
        self.post_processor = PdfPostProcessor()

    def can_handle(self, ext: str) -> bool:
        """Return True if this parser supports the given file extension."""

        return ext.lower() in self.SUPPORTED_EXTENSIONS

    def parse(self, file_bytes: bytes, filename: str, **kwargs) -> DoclingDocument:
        """Convert raw PDF file bytes into a DoclingDocument using per-page triage."""
        
        try:
            pdf = fitz.open(stream=file_bytes, filetype="pdf")
        except Exception as exc:
            logger.warning("Failed to open PDF with PyMuPDF: %s; falling back to Docling vanilla", exc)
            stream = DocumentStream(name=filename, stream=io.BytesIO(file_bytes))
            fallback_conv = DocumentConverter(allowed_formats=[InputFormat.PDF])
            return fallback_conv.convert(stream).document

        page_markdowns: list[str] = []

        try:
            # Upfront document extraction and analysis
            page_texts = [p.get_text() for p in pdf]
            raw_texts = page_texts
            vocab = build_vocab(page_texts)
            ocr_pages = {i for i, t in enumerate(page_texts) if len(t.strip()) < 40}
            tick_legend = scan_legend(page_texts)

            # Per-page triage and backend dispatch
            for page_idx, page in enumerate(pdf):
                routes = self.triager.triage_page(page)
                use_ocr = page_idx in ocr_pages

                # Dual Table + Image route
                if PageRoute.TABLE in routes and PageRoute.IMAGE in routes:
                    p_bytes = single_page_bytes(pdf, page_idx)
                    table_md = self.docling_backend.extract_page_markdown(
                        p_bytes, filename, use_ocr=use_ocr, legend=tick_legend, page_no=page_idx + 1
                    )
                    fig_captions = self.vlm_backend.extract_picture_descriptions_only(p_bytes, filename, use_ocr=use_ocr)
                    combined_md = f"{table_md}\n\n{fig_captions}".strip() if fig_captions else table_md
                    page_markdowns.append(combined_md)

                # Table-only route
                elif PageRoute.TABLE in routes:
                    p_bytes = single_page_bytes(pdf, page_idx)
                    md = self.docling_backend.extract_page_markdown(
                        p_bytes, filename, use_ocr=use_ocr, legend=tick_legend, page_no=page_idx + 1
                    )
                    page_markdowns.append(md)

                # Image-only route
                elif PageRoute.IMAGE in routes:
                    p_bytes = single_page_bytes(pdf, page_idx)
                    md = self.vlm_backend.extract_page_markdown(
                        p_bytes, filename, use_ocr=use_ocr, legend=tick_legend, page_no=page_idx + 1
                    )
                    page_markdowns.append(md)

                # Default: Text-heavy route via PyMuPDF4LLM
                else:
                    md = self.pymupdf_backend.extract_page_markdown(pdf, page_idx, use_ocr=use_ocr)
                    page_markdowns.append(md)

            # Markdown transformations (glyphs, running lines, vocabulary cleanup, coverage)
            processed_markdowns = self.post_processor.process_markdowns(
                page_markdowns, raw_texts=raw_texts, vocab=vocab
            )

            # Merge per-page markdowns into unified DoclingDocument
            combined_doc = merge_pages_to_docling(processed_markdowns, filename)

            # Document-level transformations (headings, captions, echoes, blacklist, visual cellmarks)
            return self.post_processor.process_document(combined_doc, pdf=pdf, vocab=vocab)

        finally:
            pdf.close()
