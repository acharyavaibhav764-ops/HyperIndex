"""
parsers/pdf_router.py — PdfPageRouter for .pdf files.

Implements per-page triage for PDF documents, routing each page to the
optimal extraction backend:

  - PyMuPDF4LLM : text-heavy pages (fast markdown extraction)
  - Docling      : table-bearing pages (structural extraction)
  - SmolVLM      : image/diagram-heavy pages (via Docling VLM pipeline)

Triage heuristics (all tunable via config):
  - Tables  : page.find_tables().tables is non-empty → "table" in routes
  - Images  : page.get_images() non-empty AND text_len < pdf_min_text_chars_for_text_route → "image" in routes
  - Both    : a page can carry both "table" and "image"; table md + picture
              captions are merged so neither is dropped
  - Default : ["text"]

When settings.enable_pdf_page_router is False (default), parse() falls
back to full-document Docling conversion — identical to PdfStubParser
behaviour. This makes the v5 router a drop-in replacement with zero
risk during initial rollout.

v5.1 notes
----------
_docling_page() and _smolvlm_page() now operate on single-page PDF bytes
produced by _single_page_bytes(), ensuring true per-page isolation.
Page provenance (page_no) is stamped in _merge_pages() via ProvenanceItem
so that core/chunker.py correctly populates `page` and `page_numbers` in
chunk metadata.
_triage_page() now returns a list[str] so a page can simultaneously be
"table" AND "image": Docling provides the table structure, while
_picture_descriptions_only() appends figure captions from SmolVLM without
duplicating body text. DeepSeek-OCR2 integration is deferred to v6.

v5.2 notes
----------
_build_vlm_converter() now uses PdfPipelineOptions for the PDF format entry
(fix for ConvertPipelineOptions not having generate_page_images; v5.1 Fix 4a
had the right idea but wrong options class). _smolvlm_page() /
_picture_descriptions_only() now honour settings.enable_picture_description
via _build_vlm_converter() early-return. _repair_pdf_headings() is a new
post-merge pass that demotes repeating boilerplate (running headers/footers)
and promotes numbered paragraphs to SECTION_HEADER, fixing the heading-freeze
observed in the real-pipeline run documented in docs/v5_2_plan.md.
"""
import logging
import re
from io import BytesIO

import fitz  # PyMuPDF
import pymupdf4llm
from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import InputFormat
from docling_core.types.doc import (
    DoclingDocument,
    BoundingBox,
    ProvenanceItem,
    DocItemLabel,
    TextItem,
    SectionHeaderItem,
)
from docling_core.types.io import DocumentStream

from config import settings
from .base import BaseParser
from .docling_parser import _build_vlm_converter, _inject_picture_descriptions

logger = logging.getLogger(__name__)

# Matches standard technical-doc numbered headings: "7.6 Specificity", "9.4.2 Proteins"
# Groups: one or more digit-dot segments followed by a non-whitespace word.
_NUMBERED_HEADING_RE = re.compile(r"^\d+(\.\d+){0,3}\s+\S")


def _repair_pdf_headings(
    doc: DoclingDocument,
    min_page_repeats: int | None = None,
) -> None:
    """Fix heading fidelity lost by _merge_pages()'s per-page independent parsing.

    Two passes run against the fully-merged document (requires all pages present
    to detect cross-page repetition):

    1. **Boilerplate demotion** — any text string that appears verbatim on
       ``>= min_page_repeats`` distinct pages is a running header/footer, not a
       real heading.  If a per-page heuristic mistagged it as SECTION_HEADER or
       TITLE it is replaced with a PARAGRAPH TextItem so it never enters
       ``chunk.meta.headings``.

    2. **Numbered heading promotion** — any PARAGRAPH whose text matches the
       standard ``N.N[.N[.N]] <word>`` technical-doc pattern is promoted to
       SECTION_HEADER so HybridChunker's heading path advances rather than
       freezing on the last lucky per-page promotion.

    Uses the model_dump()-swap technique already used in
    ``_promote_pptx_pseudo_headings()`` for the sibling PPTX problem.

    Args:
        doc:              Fully-merged DoclingDocument (modified in place).
        min_page_repeats: Override for the boilerplate threshold; defaults to
                          ``settings.pdf_boilerplate_min_page_repeats`` (3).
    """
    threshold = min_page_repeats if min_page_repeats is not None \
        else settings.pdf_boilerplate_min_page_repeats

    # Pass 1 — collect page counts per unique text string
    pages_seen_on: dict[str, set[int]] = {}
    for item in doc.texts:
        stripped = (item.text or "").strip()
        page_no = item.prov[0].page_no if getattr(item, "prov", None) else None
        if stripped and page_no is not None:
            pages_seen_on.setdefault(stripped, set()).add(page_no)

    boilerplate: set[str] = {
        t for t, pages in pages_seen_on.items() if len(pages) >= threshold
    }

    # Pass 2 — demote boilerplate, promote numbered headings
    for i, item in enumerate(doc.texts):
        stripped = (item.text or "").strip()
        if not stripped:
            continue

        # Demote boilerplate that slipped through as a heading
        if (
            item.label in (DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE)
            and stripped in boilerplate
        ):
            dump = item.model_dump()
            dump["label"] = DocItemLabel.PARAGRAPH
            # SectionHeaderItem.model_dump() includes 'level' which TextItem rejects;
            # filter to only the fields TextItem accepts before constructing.
            text_fields = TextItem.model_fields.keys()
            doc.texts[i] = TextItem(**{k: v for k, v in dump.items() if k in text_fields})
            continue

        # Promote numbered paragraphs to section headers
        if (
            item.label == DocItemLabel.PARAGRAPH
            and len(stripped) < 100
            and _NUMBERED_HEADING_RE.match(stripped)
        ):
            dump = item.model_dump()
            dump["label"] = DocItemLabel.SECTION_HEADER
            doc.texts[i] = SectionHeaderItem(**dump)


class PdfPageRouter(BaseParser):
    """
    v5.1 PDF per-page triage router.

    Each page is independently classified via _triage_page(), which returns a
    list of routes.  Pages with only "text" go to PyMuPDF4LLM.  Pages with
    "table" go to Docling for structural extraction.  Pages with "image" go to
    SmolVLM.  Pages with both "table" and "image" run Docling for table content
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
            routes = self._triage_page(page)
            logger.debug("Page %d → routes=%s", page.number, routes)

            if routes == ["text"]:
                # Fast path: no tables or images — plain PyMuPDF4LLM extraction
                page_markdowns.append(pymupdf4llm.to_markdown(pdf, pages=[page.number]))
                continue

            # Heavy path: at least one of table / image
            single_bytes = self._single_page_bytes(pdf, page.number)
            parts: list[str] = []

            if "table" in routes:
                parts.append(self._docling_page(single_bytes, filename, page.number))

            if "image" in routes:
                if "table" in routes:
                    # Table content already captured above; add only picture captions
                    # to avoid duplicating the body text.
                    parts.append(
                        self._picture_descriptions_only(single_bytes, filename, page.number)
                    )
                else:
                    parts.append(self._smolvlm_page(single_bytes, filename, page.number))

            page_markdowns.append("\n\n".join(p for p in parts if p))

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

    def _triage_page(self, page: fitz.Page) -> list[str]:
        """Classify a single PDF page into one or more routing categories.

        Returns a list so a page can simultaneously be ``'table'`` and
        ``'image'``.  A page with only text returns ``['text']``.

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
        # against page area.  The old ratio required ~25,000 chars on A4 to
        # reach the 0.05 threshold — far beyond any realistic page — so nearly
        # every image-bearing page incorrectly routed to SmolVLM.
        has_image = len(page.get_images()) > 0
        text_len = len(page.get_text())

        if has_image and text_len < settings.pdf_min_text_chars_for_text_route:
            routes.append("image")

        # Default: fast PyMuPDF4LLM extraction
        return routes or ["text"]

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

        Receives single-page PDF bytes produced by _single_page_bytes(), so
        Docling processes only the requested page.  Page provenance is stamped
        downstream in _merge_pages() using ProvenanceItem.

        Args:
            file_bytes: Raw single-page PDF bytes.
            filename:   Original filename.
            page_no:    Zero-indexed page number (used for logging).

        Returns:
            str: Markdown string for the page's content.
        """
        doc = self._docling_full(file_bytes, filename)
        return doc.export_to_markdown()

    def _smolvlm_page(self, file_bytes: bytes, filename: str, page_no: int) -> str:
        """Describe an image-heavy page using SmolVLM via Docling VLM pipeline.

        Reuses ``_build_vlm_converter()`` from docling_parser — the same
        SmolVLM-256M-Instruct preset already used for DOCX/PPTX picture description.

        Receives single-page PDF bytes produced by _single_page_bytes(), so
        SmolVLM inference runs only on the requested page.  Page provenance is
        stamped downstream in _merge_pages() using ProvenanceItem.

        Falls back to PyMuPDF4LLM text extraction if VLM conversion fails.
        The fallback always uses ``pages=[0]`` because ``file_bytes`` is already
        a single-page PDF from _single_page_bytes().

        Args:
            file_bytes: Raw single-page PDF bytes.
            filename:   Original filename.
            page_no:    Zero-indexed page number (used for logging).

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
            # file_bytes is a single-page PDF; the only valid page index is 0
            md = pymupdf4llm.to_markdown(pdf, pages=[0])
            pdf.close()
            return md

    def _picture_descriptions_only(
        self, file_bytes: bytes, filename: str, page_no: int
    ) -> str:
        """Extract SmolVLM picture-description captions for a page that also has a table.

        Used when _triage_page() returns both ``'table'`` and ``'image'``.  The
        full Docling markdown is already captured by ``_docling_page()``; this
        method adds only the ``[Figure description]`` captions from SmolVLM so
        that neither the table content nor the image description is dropped,
        and the body text is not duplicated.

        Falls back silently — if SmolVLM fails the table content is kept and the
        image description is skipped for this page.

        Args:
            file_bytes: Raw single-page PDF bytes.
            filename:   Original filename.
            page_no:    Zero-indexed page number (used for logging).

        Returns:
            str: Newline-joined ``[Figure description]`` captions, or ``""`` on
                 failure.
        """
        try:
            if self._vlm_converter is None:
                self._vlm_converter = _build_vlm_converter()
            stream = DocumentStream(name=filename, stream=BytesIO(file_bytes))
            doc = self._vlm_converter.convert(stream).document
            _inject_picture_descriptions(doc)
            return "\n\n".join(
                item.text
                for item in doc.texts
                if item.label == DocItemLabel.CAPTION
                and item.text
                and item.text.startswith("[Figure description]")
            )
        except Exception as exc:
            logger.warning(
                "Picture description failed for page %d of %s: %s. "
                "Keeping table content; skipping image description for this page.",
                page_no, filename, exc,
            )
            return ""

    # ------------------------------------------------------------------
    # Result assembly
    # ------------------------------------------------------------------

    def _merge_pages(self, page_markdowns: list[str], filename: str) -> DoclingDocument:
        """Combine per-page markdown strings into a single DoclingDocument.

        Each page markdown is converted independently so that a real
        ProvenanceItem (with the correct page_no) can be stamped on every
        text item before it is merged into the combined document.  This
        ensures core/chunker.py's _split_docling() sees non-empty prov lists
        and populates `page` / `page_numbers` in chunk metadata correctly.

        Args:
            page_markdowns: List of markdown strings, one per page (1-indexed).
            filename:       Original PDF filename (used to derive MD stream names).

        Returns:
            DoclingDocument: Merged structured document ready for chunking.
        """
        combined = DoclingDocument(name=filename.rsplit(".", 1)[0])
        converter = DocumentConverter(allowed_formats=[InputFormat.MD])

        for page_no, md in enumerate(page_markdowns, start=1):  # 1-indexed for humans
            stream = DocumentStream(
                name=f"page_{page_no}.md",
                stream=BytesIO(md.encode("utf-8")),
            )
            page_doc = converter.convert(stream).document
            for item in page_doc.texts:
                item.prov = [
                    ProvenanceItem(
                        page_no=page_no,
                        bbox=BoundingBox(l=0, t=0, r=0, b=0),  # no real coords in markdown
                        charspan=(0, len(item.text or "")),
                    )
                ]
            combined.add_document(page_doc)

        # v5.2 Fix 2: repair heading integrity corrupted by per-page independent parsing
        _repair_pdf_headings(combined)
        return combined
