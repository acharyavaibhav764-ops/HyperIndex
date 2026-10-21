import io
import logging
from io import BytesIO
from typing import Any

import fitz  # PyMuPDF
import pymupdf4llm
from docling.datamodel.base_models import InputFormat
from docling.document_converter import DocumentConverter
from docling_core.types.doc import (
    BoundingBox,
    DoclingDocument,
    ProvenanceItem,
)
from docling_core.types.io import DocumentStream

from core import pipeline_config
from ..docling_parser import _build_vlm_converter, _inject_picture_descriptions # Uses VLM methods from docling_parser
from .transforms.cellmarks import inject_marks
from .transforms.cleanup import strip_inline_emphasis
from .transforms.figures import process_pictures

logger = logging.getLogger(__name__)


def single_page_bytes(pdf: fitz.Document, page_no: int) -> bytes:
    """Extract a single page from an open fitz.Document as standalone PDF bytes."""
    
    single = fitz.open()
    single.insert_pdf(pdf, from_page=page_no, to_page=page_no)
    data = single.tobytes()
    single.close()
    return data


def merge_pages_to_docling(
    page_markdowns: list[str],
    filename: str,
) -> DoclingDocument:
    """Merge per-page markdowns into a unified DoclingDocument with proper Provenance (page_no=...)"""

    stem = filename.rsplit(".", 1)[0]
    combined = DoclingDocument(name=stem)
    md_converter = DocumentConverter(allowed_formats=[InputFormat.MD])

    for page_no, md in enumerate(page_markdowns, start=1):  # 1-indexed page provenance
        md = strip_inline_emphasis(md)
        stream = DocumentStream(
            name=f"page_{page_no}.md",
            stream=BytesIO(md.encode("utf-8")),
        )
        page_doc = md_converter.convert(stream).document

        # Stamp provenance on all items (texts, tables, pictures)
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


class PyMuPdfBackend:
    """Fast markdown extraction backend for text-heavy PDF pages."""

    @staticmethod
    def extract_page_markdown(pdf: fitz.Document, page_no: int, use_ocr: bool = True) -> str:
        """Extract markdown for page_no (0-indexed) using PyMuPDF4LLM."""
        
        md = pymupdf4llm.to_markdown(pdf, pages=[page_no])
        return md


class DoclingTableBackend:
    """Accurate table extraction backend for table-bearing PDF pages using DocumentConverter."""

    def __init__(self) -> None:
        self._converter: DocumentConverter | None = None

    def _get_converter(self) -> DocumentConverter:
        if self._converter is None:
            self._converter = DocumentConverter(allowed_formats=[InputFormat.PDF])
        return self._converter

    def extract_page_markdown(
        self,
        page_pdf_bytes: bytes,
        filename: str,
        use_ocr: bool = True,
        legend: dict[str, str] | None = None,
        page_no: int = 1,
    ) -> str:
        """Convert single-page PDF bytes with Docling, inject cellmarks/figures, and export to markdown."""
        
        stream = DocumentStream(name=filename, stream=io.BytesIO(page_pdf_bytes))
        doc = self._get_converter().convert(stream).document

        page_fitz = None
        pdf_single = None
        try:
            pdf_single = fitz.open(stream=page_pdf_bytes, filetype="pdf")
            page_fitz = pdf_single[0]
        except Exception as exc:
            logger.warning("cellmarks: failed to open single page pdf: %s", exc)

        cards = []
        if page_fitz is not None:
            try:
                inject_marks(doc, page_fitz, legend=legend, repeat_min=3)
            except Exception as exc:
                logger.warning("cellmarks: page %d failed: %s", page_no, exc)

            try:
                cards = process_pictures(
                    doc, page_fitz, heading_path=[], page_no=page_no, mode="labels_only"
                )
            except Exception as exc:
                logger.warning("pdf_figures: page %d failed: %s", page_no, exc)

            pdf_single.close()

        md = doc.export_to_markdown()
        if cards:
            card_md = "\n\n".join(c["text"] for c in cards if c.get("text"))
            if card_md:
                md = f"{md}\n\n{card_md}"
        return md


class VlmPictureBackend:
    """Vision-language description backend for image-heavy pages."""

    def __init__(self) -> None:
        self._vlm_converter: DocumentConverter | None = None

    def _get_vlm_converter(self) -> DocumentConverter | None:
        if not pipeline_config.pipeline_settings.enable_picture_description:
            return None
        if self._vlm_converter is None:
            try:
                self._vlm_converter = _build_vlm_converter()
            except Exception as exc:
                logger.warning("Failed to initialize VLM converter: %s", exc)
                return None
        return self._vlm_converter

    def extract_page_markdown(
        self,
        page_pdf_bytes: bytes,
        filename: str,
        use_ocr: bool = True,
        legend: dict[str, str] | None = None,
        page_no: int = 1,
    ) -> str:
        """Run SmolVLM description pipeline on single-page PDF bytes."""
        
        vlm = self._get_vlm_converter()

        # Fall back to Docling table converter           
        if vlm is None:
            stream = DocumentStream(name=filename, stream=io.BytesIO(page_pdf_bytes))
            converter = DocumentConverter(allowed_formats=[InputFormat.PDF])
            doc = converter.convert(stream).document
            try:
                pdf_single = fitz.open(stream=page_pdf_bytes, filetype="pdf")
                inject_marks(doc, pdf_single[0], legend=legend, repeat_min=3)
                pdf_single.close()
            except Exception as exc:
                logger.warning("cellmarks (fallback path): page %d failed: %s", page_no, exc)
            return doc.export_to_markdown()

        try:
            stream = DocumentStream(name=filename, stream=io.BytesIO(page_pdf_bytes))
            doc = vlm.convert(stream).document
            _inject_picture_descriptions(doc)
            try:
                pdf_single = fitz.open(stream=page_pdf_bytes, filetype="pdf")
                inject_marks(doc, pdf_single[0], legend=legend, repeat_min=3)
                pdf_single.close()
            except Exception as exc:
                logger.warning("cellmarks (vlm path): page %d failed: %s", page_no, exc)
            return doc.export_to_markdown()
        except Exception as exc:
            logger.warning("VLM page extraction failed: %s; falling back to PyMuPDF", exc)
            pdf = fitz.open(stream=page_pdf_bytes, filetype="pdf")
            md = pymupdf4llm.to_markdown(pdf, pages=[0])
            pdf.close()
            return md

    def extract_picture_descriptions_only(self, page_pdf_bytes: bytes, filename: str, use_ocr: bool = True) -> str:
        """Extract only the [Figure description] captions from SmolVLM for pages"""

        vlm = self._get_vlm_converter()
        if vlm is None:
            return ""

        try:
            stream = DocumentStream(name=filename, stream=io.BytesIO(page_pdf_bytes))
            doc = vlm.convert(stream).document
            _inject_picture_descriptions(doc)

            # Collect only figure description paragraphs
            captions = [
                item.text
                for item in doc.texts
                if (item.text or "").startswith("[Figure description]")
            ]
            return "\n\n".join(captions)
        except Exception as exc:
            logger.warning("Picture description only extraction failed: %s", exc)
            return ""
