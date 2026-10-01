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

v5.3 notes
----------
_smolvlm_page() now calls _inject_picture_descriptions() before
export_to_markdown(), applying the same token-cleanup and [Figure description]
tagging that _picture_descriptions_only() already applied on the table+image
path — closing the asymmetry where raw SmolVLM completion tokens (e.g.
"<end_of_utteranc") leaked into image-only chunk text.
_flatten_document() rebuilds the merged document as a flat structure where
every text item is a direct child of body, bypassing add_document()'s
cross-page nesting which caused HybridChunker's heading context to freeze
(items' parent refs stayed anchored to stale per-page sub-tree roots) and
orphaned items to land at the document tail. This unified fix resolves both
Issue 2 (heading freeze) and Issue 4 (tail ordering) in one step.

v5.5 notes
----------
Two root causes confirmed by the Diagnostic A/B evidence collected in v5.4:

A. **Heading freeze**: pymupdf4llm re-runs its font-size→markdown-hashes
   heuristic independently per page, so a sub-section heading that happens to
   be the largest font on its page is emitted as '# ' → TitleItem (level 0
   in HierarchicalChunker).  Level 0 is never cleared by any SectionHeader
   (level >= 1) until the next TitleItem arrives — producing the observed
   freeze.  Diagnostic A missed this because it only printed SECTION_HEADER.
   Fix: _repair_pdf_headings() now converts every TITLE item to a
   SectionHeaderItem with a deterministic level derived from numbering depth.

B. **Tail orphans**: core/chunker.py's "Gap B" loop was appending
   heading-only synthetic chunks at the END of the list regardless of their
   page provenance.  Diagnostic B confirmed doc.texts order was always
   correct (orphans at correct flat-list indices) — the bug was purely in
   the append-vs-insert decision.  Fix: insert at the position after all
   earlier-page chunks instead of always appending.

v5.6 notes
----------
_extract_misplaced_number() handles headings whose section number pymupdf4llm
extracted out of position ("Greasing 6.4 the Groove", "Strength & Skill
Routine 5.7") instead of leading ("6.4 Greasing the Groove") -- v5.5's
_heading_level() only ever looked at the first word, so these fell back to a
flat level 1 and stopped clearing the heading stack correctly.
The empty-text branch of _repair_pdf_headings()'s main loop no longer
skips empty-text SECTION_HEADER/TITLE items outright (v5.5's `if not
stripped: continue` silently left them at whatever level the per-page
parser gave them, including level 0); they are now emptied into harmless
TEXT items like any other dropped fragment.
_split_embedded_headings() is a post-repair pass for heading text that
never became its own DocItem: some heading text is *duplicated* verbatim as
literal "### **text**" markdown syntax glued onto the tail of the preceding
paragraph (marko never parses it as an ATX heading because it is not the
first thing on its line) -- confirmed against a real-PDF run that every
such fragment duplicates a heading that already exists correctly elsewhere,
so the fix deletes the noise rather than creating a second heading. A
narrower, separate heuristic in the same pass promotes a leading run of
ALL-CAPS words in an ordinary paragraph ("10 CRUCIAL TRAINING PRINCIPLES...")
that pymupdf4llm never '#'-detected at all, since it was not the single
largest font on its page.
Not attempted in v5.6 (see docs/v5_6_plan.md for why): CTA/bullet text
mis-detected as a heading with no decidable textual marker (e.g. "Become a
Master of Your Own Bodyweight"), table column-scrambling and duplicated
Advanced/Beginner circuit tables, OCR text corruption, and the "Apply The 8
80/20 Rule 66" heading (its real "9.9" numbering is not recoverable from the
extracted text at all -- this is upstream data loss, not a formatting bug).
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
from .docling_parser import (
    _build_text_layer_converter,
    _build_vlm_converter,
    _inject_picture_descriptions,
)
from . import pdf_cleanup, pdf_structure  # v5.7

logger = logging.getLogger(__name__)

# Matches standard technical-doc numbered headings: "7.6 Specificity", "9.4.2 Proteins"
# Groups: one or more digit-dot segments followed by a non-whitespace word.
_NUMBERED_HEADING_RE = re.compile(r"^\d+(\.\d+){0,3}\s+\S")

# v5.5: stricter pattern used ONLY to promote body text to a heading.  Docling's MD
# backend labels plain paragraphs TEXT (not PARAGRAPH), so promotion must accept TEXT;
# but the loose regex above would then turn "3 sets of 10 reps" into a heading.
# Require a dotted number ("7.3", "9.4.2") followed by a capitalised word.
_PROMOTABLE_HEADING_RE = re.compile(r"^\d+\.\d+(\.\d+){0,2}\s+[A-Z]")

# v5.6 Fix A: a dotted section number ANYWHERE in a heading string, used to find
# one that pymupdf4llm extracted out of position (not as the leading token).
_SECTION_NUMBER_TOKEN_RE = re.compile(r"\d+\.\d+(?:\.\d+){0,2}")

# v5.6 Fix C: a markdown ATX-heading fragment ("### **text**") glued onto the
# tail of a paragraph because it wasn't the first thing on its own line, so
# marko's block parser never split it into a real heading node.
_EMBEDDED_MD_HEADING_RE = re.compile(
    r"(?:\n|^|\s{2,})\s*#{1,6}\s*\*{0,2}(?P<htext>[^\n*]+?)\*{0,2}\s*\Z"
)

# v5.6 Fix D: a leading run of 2-7 ALL-CAPS/number tokens immediately followed
# by normal-case prose -- a chapter-style heading pymupdf4llm never '#'-detected
# because it wasn't the single largest font on its page. Narrow and heuristic;
# supports optional markdown bold on the heading itself.
_LEADING_ALLCAPS_RE = re.compile(
    r"^\*{0,2}(?P<caps>[A-Z0-9][A-Z0-9&/]*(?:\s+[A-Z0-9][A-Z0-9&/]*){1,6})\*{0,2}\s+(?=[A-Z][a-z])"
)


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

    # Pass 2 — demote boilerplate, normalise heading type/level, promote numbered paragraphs
    for i, item in enumerate(doc.texts):
        stripped = (item.text or "").strip()

        # v5.6 Fix B: an empty-text heading item is not a demotion candidate (it
        # matches nothing in `boilerplate`) and isn't a real heading either --
        # v5.5 skipped it via the blanket "if not stripped: continue" below, so
        # it kept whatever level the per-page parser gave it, including level 0
        # (HierarchicalChunker's document-title slot), where it would silently
        # reset any heading in progress the next time the traversal reached it.
        # Emptying it into a plain TextItem makes it inert instead: the doc
        # serializer emits empty text for it, so HierarchicalChunker's own
        # `if not ser_res.text: continue` drops it from chunk output entirely.
        if item.label in (DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE) and not stripped:
            dump = item.model_dump()
            dump["label"] = DocItemLabel.TEXT
            text_fields = TextItem.model_fields.keys()
            doc.texts[i] = TextItem(**{k: v for k, v in dump.items() if k in text_fields})
            continue

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

        # v5.5 Fix A: normalise EVERY heading to a SectionHeaderItem with a
        # deterministic level.  pymupdf4llm is called once per page, so its
        # font-size → '#'/'##'/'###' mapping is recomputed per page: a sub-section
        # heading that is the largest font on its page becomes '# ' → TitleItem,
        # which HierarchicalChunker treats as level 0 and never clears until the
        # next TitleItem (the "5.5 Mobility" freeze).  Numbered headings get their
        # level from numbering depth ("7" → 1, "7.3" → 2, "7.3.1" → 3).
        if item.label in (DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE):
            current = getattr(item, "level", None)
            # v5.6 Fix A: the section number pymupdf4llm found is sometimes not
            # the heading's leading token ("Greasing 6.4 the Groove", "Strength
            # & Skill Routine 5.7") -- _heading_level() only ever looks at the
            # first word, so these fell back to a flat level 1. Relocate the
            # number to the front and derive level from it before that fallback.
            relocated = _extract_misplaced_number(stripped)
            if relocated is not None:
                new_text, level = relocated
                doc.texts[i] = _as_section_header(item, level, text=new_text)
            else:
                level = _heading_level(stripped, current)
                if item.label == DocItemLabel.TITLE or current != level:
                    doc.texts[i] = _as_section_header(item, level)
            continue

        # Promote numbered paragraphs/text items to section headers.
        # v5.5: accept TEXT label (docling's MD parser labels paragraphs TEXT,
        # not PARAGRAPH — the old PARAGRAPH-only check was dead code against
        # the markdown-converted path).  Use stricter _PROMOTABLE_HEADING_RE
        # so "3 sets of 10 reps" is never promoted.
        if (
            item.label in (DocItemLabel.PARAGRAPH, DocItemLabel.TEXT)
            and len(stripped) < 80
            and not stripped.endswith(("." , ",", ";", ":"))
            and _PROMOTABLE_HEADING_RE.match(stripped)
        ):
            doc.texts[i] = _as_section_header(item, _heading_level(stripped, None))

    # v5.6 Fix C + Fix D — heading text that never became its own DocItem.
    _split_embedded_headings(doc)


def _heading_level(text: str, current: int | None) -> int:
    """Return the chunker heading level (>=1) for a heading.

    Numbered headings derive level from numbering depth:
      - "7" → 1 (no dots)
      - "7.3" → 2 (one dot)
      - "7.3.1" → 3 (two dots)

    Unnumbered headings keep their existing SectionHeader level, defaulting
    to 1.  Level 0 is never returned — that is the document-title slot in
    HierarchicalChunker and is only cleared by another TitleItem.

    Args:
        text:    Stripped heading text.
        current: Existing ``level`` attribute value, or None if absent.

    Returns:
        int: Level >= 1.
    """
    if _NUMBERED_HEADING_RE.match(text):
        return text.split()[0].count(".") + 1
    return max(current or 1, 1)


def _as_section_header(item, level: int, text: str | None = None) -> SectionHeaderItem:
    """Rebuild any text-like item as a SectionHeaderItem at ``level``.

    Preserves self_ref, parent, prov and text so the item stays correctly
    wired into the document tree — only label and level change.

    Args:
        item:  Original TextItem / SectionHeaderItem / TitleItem.
        level: Target heading level (>= 1).
        text:  If given, replaces the item's text (v5.6 Fix A: relocating a
               misplaced section number rewrites the string, not just the level).

    Returns:
        SectionHeaderItem: Drop-in replacement with corrected label/level.
    """
    dump = item.model_dump()
    dump["label"] = DocItemLabel.SECTION_HEADER
    dump["level"] = level
    if text is not None:
        dump["text"] = text
    fields = SectionHeaderItem.model_fields.keys()
    return SectionHeaderItem(**{k: v for k, v in dump.items() if k in fields})


def _extract_misplaced_number(text: str) -> tuple[str, int] | None:
    """Find a dotted section number embedded in a heading string and move it to the front.

    pymupdf4llm's per-page heading detection uses raw text-block reading order.
    When a section number is typeset as a separate design element positioned
    near a heading -- rather than literally being the heading's first word --
    it ends up interleaved into the extracted string at whatever position the
    page's reading order put it: "Greasing 6.4 the Groove", "Circuit t Training
    6.5", "Strength & Skill Routine 5.7". _heading_level() only ever inspects
    the first word, so these all fell back to a flat, undifferentiated level 1.

    Deliberately conservative: only acts when exactly one dotted-number token
    is found and it is not already leading (ignoring markdown formatting or
    punctuation before the number). Zero or multiple candidates are
    ambiguous and are left for a human / a future pass rather than guessed at.
    A single *un-dotted* trailing number (e.g. a stray page-number digit) never
    matches _SECTION_NUMBER_TOKEN_RE at all, so it is never touched here --
    see docs/v5_6_plan.md for the "Apply The 8 80/20 Rule 66" case this misses.

    Args:
        text: Stripped heading text.

    Returns:
        ``(new_text, level)`` with the number relocated to the front, or
        ``None`` if the text doesn't contain exactly one relocatable number.
    """
    matches = list(_SECTION_NUMBER_TOKEN_RE.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    if not any(c.isalnum() for c in text[: match.start()]):
        return None  # already leading; nothing to relocate
    number = match.group(0)
    remainder = (text[: match.start()] + " " + text[match.end() :]).strip()
    remainder = re.sub(r"\s{2,}", " ", remainder)
    if not remainder:
        return None
    return f"{number} {remainder}", number.count(".") + 1


def _split_embedded_headings(doc: DoclingDocument) -> None:
    """Handle heading text that pymupdf4llm never turned into its own DocItem.

    Two unrelated phenomena share a symptom (heading-shaped text stuck inside
    an ordinary PARAGRAPH/TEXT item) but need opposite fixes:

    **Fix C — duplicate noise, delete it.** Some pages' markdown repeats a
    heading's text a second time as a literal "### **text**" fragment glued
    onto the tail of the *preceding* paragraph. marko's block parser only
    recognises an ATX heading when '#' starts its own line, so this fragment
    never became a heading node -- but the *real* heading, correctly typed,
    already exists elsewhere in the document (confirmed for every instance
    found in the real-PDF run this was built against; see docs/v5_6_plan.md).
    Creating a second heading node for it would just duplicate the heading
    path, so this strips the fragment instead of promoting it.

    **Fix D — genuinely missing heading, promote it.** A handful of
    chapter-style headings are never '#'-detected at all, because they are
    not the single largest font on their page (e.g. a large decorative
    numeral sits beside modest-sized bold chapter text). These survive only
    as **bold** text at the start of an ordinary paragraph, with no
    corresponding heading item anywhere in the document. A narrow pattern --
    a leading run of ALL-CAPS/number tokens immediately followed by
    normal-case prose -- is promoted into a real SectionHeaderItem via
    doc.insert_heading(), which correctly reorders doc.body.children without
    disturbing any existing item's self_ref (self_ref is positional in
    docling-core; a naive doc.texts.insert() would silently invalidate every
    ref after the insertion point).

    Args:
        doc: Fully-merged DoclingDocument.
    """
    heading_texts = {
        (item.text or "").strip()
        for item in doc.texts
        if item.label in (DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE)
        and (item.text or "").strip()
    }

    for item in list(doc.texts):
        if item.label not in (DocItemLabel.PARAGRAPH, DocItemLabel.TEXT):
            continue
        text = item.text or ""

        # Fix C: strip a trailing "### **text**" fragment that duplicates a
        # heading that already exists as its own item elsewhere.
        dup_match = _EMBEDDED_MD_HEADING_RE.search(text)
        if dup_match and dup_match.group("htext").strip() in heading_texts:
            text = text[: dup_match.start()].rstrip()
            item.text = text

        # Fix D: promote a leading ALL-CAPS run pymupdf4llm never '#'-detected.
        stripped = text.strip()
        caps_match = _LEADING_ALLCAPS_RE.match(stripped)
        if caps_match and len(caps_match.group("caps")) >= 8:
            heading_text = caps_match.group("caps")
            if heading_text not in heading_texts:
                item.text = stripped[caps_match.end() :].strip()
                if stripped.startswith("**") and item.text.endswith("**") and not item.text.startswith("**"):
                    item.text = item.text[:-2].strip()
                doc.insert_heading(
                    sibling=item,
                    text=heading_text,
                    level=1,
                    prov=item.prov[0] if item.prov else None,
                    after=False,
                )
                heading_texts.add(heading_text)


def _flatten_document(doc: DoclingDocument) -> DoclingDocument:
    """v5.3 candidate — reverted in v5.4. Do not call.

    Only walked ``doc.texts``; ``doc.tables`` was never touched, so every table
    in the document was silently dropped on the real PDF smoke test.  It also
    produced zero measurable change to the heading freeze or tail-ordering bugs
    it was written to fix (confirmed by direct before/after chunk comparison
    against v5.2 output).  Even a corrected version that also handled tables
    would not have been worth the complexity without evidence that reparenting
    is actually the mechanism behind either bug.

    Kept here for reference; do not re-enable without new evidence.

    Args:
        doc: Fully-merged DoclingDocument (not used — function is unreachable).

    Returns:
        DoclingDocument: Flat document (not reached in any active code path).
    """
    flat = DoclingDocument(name=doc.name)
    for item in doc.texts:
        new_item = flat.add_text(
            label=item.label,
            text=item.text or "",
            parent=flat.body,
        )
        new_item.prov = item.prov  # carry page provenance over verbatim
    return flat


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
        # v5.7: OCR-free converters for pages that carry a text layer, and the
        # document vocabulary used by the text repair passes.
        self._text_layer_converter: DocumentConverter | None = None
        self._vlm_converter_text: DocumentConverter | None = None
        self._vocab = None
        self._ocr_pages: set[int] = set()

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

        # v5.7: vocabulary from the PDF's own text layer + which pages have one.
        page_texts = [p.get_text() for p in pdf]
        self._vocab = pdf_cleanup.build_vocab(page_texts)
        self._ocr_pages = {
            i for i, t in enumerate(page_texts)
            if settings.pdf_ocr_on_text_pages or len(t.strip()) < settings.pdf_text_layer_min_chars
        }

        for page in pdf:
            routes = self._triage_page(page)
            logger.debug("Page %d → routes=%s", page.number, routes)
            use_ocr = page.number in self._ocr_pages

            if routes == ["text"]:
                # Fast path: no tables or images — plain PyMuPDF4LLM extraction
                page_markdowns.append(self._page_markdown(pdf, page.number, use_ocr))
                continue

            # Heavy path: at least one of table / image
            single_bytes = self._single_page_bytes(pdf, page.number)
            parts: list[str] = []

            if "table" in routes:
                parts.append(self._docling_page(single_bytes, filename, page.number, use_ocr))

            if "image" in routes:
                if "table" in routes:
                    # Table content already captured above; add only picture captions
                    # to avoid duplicating the body text.
                    parts.append(
                        self._picture_descriptions_only(single_bytes, filename, page.number, use_ocr)
                    )
                else:
                    parts.append(self._smolvlm_page(single_bytes, filename, page.number, use_ocr))

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

    @staticmethod
    def _page_markdown(pdf: "fitz.Document", page_no: int, use_ocr: bool) -> str:
        """v5.7: pymupdf4llm markdown for one page, without running footers or OCR.

        ``header=False, footer=False`` drops the page-furniture blocks; ``use_ocr=False``
        keeps pymupdf4llm from re-OCRing a page that already has a text layer.  Older
        pymupdf4llm builds reject unknown keyword arguments, so we degrade gracefully.
        """
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

    def _docling_full(self, file_bytes: bytes, filename: str, use_ocr: bool = True) -> DoclingDocument:
        """Full-document Docling conversion.

        Used as the fallback path when enable_pdf_page_router is False,
        and as the per-page table extraction tier in the triage path.

        Args:
            file_bytes: Raw PDF bytes.
            filename:   Original filename for DocumentStream naming.

        Returns:
            DoclingDocument: Converted document.
        """
        if use_ocr:
            if self._docling_converter is None:
                self._docling_converter = DocumentConverter()
            converter = self._docling_converter
        else:                                    # v5.7: trust the text layer
            if self._text_layer_converter is None:
                self._text_layer_converter = _build_text_layer_converter()
            converter = self._text_layer_converter
        stream = DocumentStream(name=filename, stream=BytesIO(file_bytes))
        result = converter.convert(stream)
        return result.document

    def _vlm_for(self, use_ocr: bool) -> DocumentConverter:
        """v5.7: cached VLM converter, OCR-free when the page has a text layer."""
        if use_ocr:
            if self._vlm_converter is None:
                self._vlm_converter = _build_vlm_converter()
            return self._vlm_converter
        if self._vlm_converter_text is None:
            self._vlm_converter_text = _build_vlm_converter(do_ocr=False)
        return self._vlm_converter_text

    def _docling_page(self, file_bytes: bytes, filename: str, page_no: int, use_ocr: bool = True) -> str:
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
        doc = self._docling_full(file_bytes, filename, use_ocr)
        return doc.export_to_markdown()

    def _smolvlm_page(self, file_bytes: bytes, filename: str, page_no: int, use_ocr: bool = True) -> str:
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
            stream = DocumentStream(name=filename, stream=BytesIO(file_bytes))
            doc = self._vlm_for(use_ocr).convert(stream).document
            # v5.3 Fix 1: run the same cleanup+tagging pass used by
            # _picture_descriptions_only() — strips dangling SmolVLM completion
            # tokens (e.g. "<end_of_utteranc") and prefixes descriptions with
            # "[Figure description]" for consistent downstream filtering.
            _inject_picture_descriptions(doc)
            return doc.export_to_markdown()
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
        self, file_bytes: bytes, filename: str, page_no: int, use_ocr: bool = True
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
            stream = DocumentStream(name=filename, stream=BytesIO(file_bytes))
            doc = self._vlm_for(use_ocr).convert(stream).document
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
        item (text, table, picture) before it is merged into the combined
        document.  This ensures core/chunker.py's _split_docling() sees
        non-empty prov lists and populates ``page`` / ``page_numbers`` in
        chunk metadata correctly.

        Note: prov is stamped on ALL item types via ``page_doc.iterate_items()``
        (not just ``page_doc.texts``) to avoid table and picture items keeping
        their default page_no=1 (the single-page PDF's internal page number)
        which caused them to appear as orphaned tail chunks in the output.

        Args:
            page_markdowns: List of markdown strings, one per page (1-indexed).
            filename:       Original PDF filename (used to derive MD stream names).

        Returns:
            DoclingDocument: Merged structured document ready for chunking.
        """
        combined = DoclingDocument(name=filename.rsplit(".", 1)[0])
        converter = DocumentConverter(allowed_formats=[InputFormat.MD])

        # v5.7: strip running footers, then clean each page's markdown (markup, glued
        # words, picture-text debris, table normalisation) before Docling parses it.
        if settings.pdf_v57_cleanup:
            page_markdowns = pdf_cleanup.strip_running_lines(page_markdowns)
            page_markdowns = [
                pdf_cleanup.clean_page_markdown(md, self._vocab) for md in page_markdowns
            ]

        for page_no, md in enumerate(page_markdowns, start=1):  # 1-indexed for humans
            stream = DocumentStream(
                name=f"page_{page_no}.md",
                stream=BytesIO(md.encode("utf-8")),
            )
            page_doc = converter.convert(stream).document
            # v5.3 Fix: stamp prov on ALL item types (texts + tables + pictures),
            # not just page_doc.texts — table items kept their default prov
            # page_no=1 (docling's internal single-page numbering) which caused
            # them to appear as orphaned tail chunks after the correct-page chunks.
            prov = ProvenanceItem(
                page_no=page_no,
                bbox=BoundingBox(l=0, t=0, r=0, b=0),
                charspan=(0, 0),
            )
            for item, _ in page_doc.iterate_items():
                if hasattr(item, 'prov'):
                    item.prov = [prov]
            combined.add_document(page_doc)

        # v5.2 Fix 2: repair heading labels corrupted by per-page independent parsing
        _repair_pdf_headings(combined)

        # v5.7: document-level structure repair (pseudo-headings, captions, levels).
        if settings.pdf_v57_cleanup:
            pdf_structure.repair_pdf_structure(combined, self._vocab)

        # v5.4 Diagnostic A+B — gated behind PDF_DEBUG_HEADING_DUMP=1 (default off).
        # Diagnostic A: print level of each SECTION_HEADER to settle the heading-level
        #   hypothesis (promoted headings may all share a wrong default level, causing
        #   HybridChunker to not advance heading context across them).
        # Diagnostic B: print flat-list index of known orphan items to determine whether
        #   the ordering bug is in add_document()'s append order or in downstream
        #   tree-traversal by HybridChunker / export_to_markdown().
        if settings.pdf_debug_heading_dump:
            for item in combined.texts:
                if item.label in (DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE):
                    text_preview = (item.text or "")[:40]
                    level = getattr(item, "level", "<TITLE=level0>")
                    page_no = item.prov[0].page_no if item.prov else None
                    print(  # noqa: T201 — intentional debug output, gated by flag
                        f"HEADING page={page_no} label={item.label.value} "
                        f"level={level!r} text={text_preview!r}"
                    )
            total = len(combined.texts)
            orphan_markers = ("Advanced Circuit", "CONTENTS", "FULUOURIMEY", "Animal Protein")
            for idx, item in enumerate(combined.texts):
                text_preview = (item.text or "")[:30]
                if any(marker in text_preview for marker in orphan_markers):
                    page_no = item.prov[0].page_no if item.prov else None
                    print(  # noqa: T201 — intentional debug output, gated by flag
                        f"ORPHAN-CHECK index={idx}/{total} page={page_no} text={text_preview!r}"
                    )

        # v5.3 _flatten_document() was reverted in v5.4 — it silently dropped
        # doc.tables and produced no measurable improvement to either bug.
        return combined
