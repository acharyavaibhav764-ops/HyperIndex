"""v5.7 -- DoclingDocument-level structure repair for router-built PDF documents.

Runs after ``pdf_router._repair_pdf_headings`` (which fixes heading *text and depth
from numbering*).  This module fixes what numbering cannot see:

1. ``clean_text_items``      -- markup leaks, glued words, doubled paragraphs, photo noise
2. ``demote_pseudo_headings``-- call-to-action lines, button labels and bullets typed as headings
3. ``bind_captions``         -- 'Day 2' / 'Animal Protein' style labels become the caption of the
                                table right after them instead of headings / stray chunks
4. ``relevel_headings``      -- unnumbered sub-labels nest under the last numbered heading
5. ``dedupe_echoes``         -- a paragraph that only repeats an adjacent heading is blanked

Blanked items keep ``text == ""``: HierarchicalChunker skips empty serialisations.
"""
from __future__ import annotations

import logging
import re
from collections import Counter

from docling_core.types.doc import (
    DocItemLabel,
    DoclingDocument,
    PictureItem,
    SectionHeaderItem,
    TableItem,
    TextItem,
)
from docling_core.types.doc.document import RefItem

from . import cleanup

logger = logging.getLogger(__name__)

_HEADING_LABELS = (DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE)
_BODY_LABELS = (DocItemLabel.TEXT, DocItemLabel.PARAGRAPH)
_SKIP_CLEAN = (DocItemLabel.CODE, DocItemLabel.FORMULA)
_NUMBERED_RE = re.compile(r"^\d+(?:\.\d+){0,3}\.?\s+\S")
_CODE_CONTEXT_RE = re.compile(r"\b(?:use|enter|apply)\s+code\b|\bdi[s]?count\s+code\b", re.I)
_BUTTON_RE = re.compile(r"^(?:[a-z]{1,2}\s+)?(?:get|start|more|transform|buy|shop|learn|join|download|order|sign|click)\b", re.I)
_LEAD_JUNK_RE = re.compile(r"^[a-z]{1,2}\s+(?=[A-Z])")
_SMALL_WORDS = {"a", "an", "the", "of", "in", "on", "to", "for", "and", "or", "at", "by", "with"}
_DAY_RE = re.compile(r"^(Day|Week|Round|Step)\s+(\d+)$")

# v5.9 WP6: template heading blacklist
_HEADING_BLACKLIST = {
    "titelseite", "gb version",
    "(text wird aus lv texte ...)",
}
_HEADING_BLACKLIST_RE = re.compile(
    r"^(?:Fig\.|Abb\.)\s*\d+|^\(TEXT wird aus LV Texte", re.I
)
_PROFILE_RE = re.compile(r"^Profile\s+\d+$", re.I)
_FEATURES_RE = re.compile(r"^(?:Features|Functions):\s*$", re.I)
_NUMBERED_OVERRIDE_RE = re.compile(r"^\d+(\.\d+){1,3}\s+\S")  # e.g. 4.5.5
_DOC_NUMBER_RE = re.compile(r"\b(\d{5,}[A-Z]\d*\.\w+)\b")
_DOC_VERSION_RE = re.compile(r"\bV(\d+(?:\.\d+)?)\b")
_DOC_DATE_RE = re.compile(r"\b(\d{1,2}\.\d{4})\b")


# ----------------------------------------------------------------------------
# tree helpers
# ----------------------------------------------------------------------------

def _idx(item) -> int:
    return int(item.self_ref.rsplit("/", 1)[1])


def _page(item) -> int | None:
    prov = getattr(item, "prov", None)
    return prov[0].page_no if prov else None


def _sequence(doc: DoclingDocument) -> list:
    """Text / table / picture items in reading (tree) order."""
    return [it for it, _ in doc.iterate_items() if isinstance(it, (TextItem, TableItem, PictureItem))]


def _as_text(item, label: DocItemLabel = DocItemLabel.TEXT, text: str | None = None) -> TextItem:
    dump = item.model_dump()
    dump["label"] = label
    if text is not None:
        dump["text"] = text
        dump["orig"] = text
    fields = TextItem.model_fields.keys()
    return TextItem(**{k: v for k, v in dump.items() if k in fields})


def _as_heading(item, level: int, text: str | None = None) -> SectionHeaderItem:
    dump = item.model_dump()
    dump["label"] = DocItemLabel.SECTION_HEADER
    dump["level"] = level
    if text is not None:
        dump["text"] = text
        dump["orig"] = text
    fields = SectionHeaderItem.model_fields.keys()
    return SectionHeaderItem(**{k: v for k, v in dump.items() if k in fields})


def _swap(doc: DoclingDocument, old, new) -> None:
    doc.texts[_idx(old)] = new


def _is_heading(item) -> bool:
    return isinstance(item, TextItem) and item.label in _HEADING_LABELS


def _is_caps(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 4 and all(c.isupper() for c in letters)


# ----------------------------------------------------------------------------
# 1. text items
# ----------------------------------------------------------------------------

def clean_text_items(doc: DoclingDocument, vocab: Counter | None = None) -> None:
    """Normalise every text-like item; blank photo noise and doubled paragraphs."""
    for it in doc.texts:                       # v5.8: HybridChunker re-adds '**' from .formatting
        if getattr(it, "formatting", None) is not None:
            it.formatting = None
    # headings first, so paragraphs can be checked for trailing heading echoes
    for it in list(doc.texts):
        if it.label in _SKIP_CLEAN or not (it.text or "").strip():
            continue
        if it.label in _HEADING_LABELS:
            new = cleanup.normalize_text(it.text, vocab, is_heading=True)
            if new != it.text:
                it.text = new
    heading_texts = [t for t in ((h.text or "").strip() for h in doc.texts if h.label in _HEADING_LABELS) if len(t) >= 6]

    for it in list(doc.texts):
        if it.label in _SKIP_CLEAN or it.label in _HEADING_LABELS or not (it.text or "").strip():
            continue
        raw = it.text
        new = cleanup.normalize_text(raw, vocab)
        new = cleanup.dedupe_doubled_text(new)
        for h in heading_texts:                     # '... end of paragraph 7.1 Consistency'
            if new.endswith(h) and len(new) > len(h) + 20:
                new = new[: -len(h)].rstrip()
                break
        if it.label in _BODY_LABELS and len(new) < 80 and cleanup.is_noise_paragraph(new):
            new = ""
        if new != raw:
            it.text = new

    # headings that became empty are no longer headings
    for it in list(doc.texts):
        if it.label in _HEADING_LABELS and not (it.text or "").strip():
            _swap(doc, it, _as_text(it, DocItemLabel.TEXT, ""))


# ----------------------------------------------------------------------------
# 2. call-to-action lines, buttons and bullets that are not headings
# ----------------------------------------------------------------------------

def _looks_like_cta(text: str) -> bool:
    words = text.split()
    if len(words) >= 3 and text.endswith("!"):
        cap = [w for w in words if w.lower() not in _SMALL_WORDS]
        return sum(w[:1].isupper() for w in cap) / max(len(cap), 1) >= 0.6
    return False


def demote_pseudo_headings(doc: DoclingDocument) -> None:
    """Turn CTA lines, button labels, bullets and sign-offs typed as headings into text."""
    seq = _sequence(doc)
    for pos, it in enumerate(seq):
        if not _is_heading(it):
            continue
        text = (it.text or "").strip()
        if not text or _NUMBERED_RE.match(text) or _is_caps(text):
            continue
        new_text: str | None = None
        if cleanup._LEAD_BULLET_RE.match(text):
            new_text = cleanup._LEAD_BULLET_RE.sub("", text)                   # '> Beginner ...'
        elif text.endswith(","):
            new_text = text                                                     # 'Best,'
        elif re.match(r"(?i)^use\s+code\b", text) or _looks_like_cta(text):
            new_text = text
        elif len(text.split()) <= 8 and _BUTTON_RE.search(text):
            new_text = _LEAD_JUNK_RE.sub("", text)                              # 'r Transform Now'
        else:
            following = []
            for nxt in seq[pos + 1: pos + 9]:
                if _is_heading(nxt) and (_NUMBERED_RE.match((nxt.text or "").strip()) or _is_caps(nxt.text or "")):
                    break
                if isinstance(nxt, TextItem):
                    following.append(nxt.text or "")
            if any(_CODE_CONTEXT_RE.search(t) for t in following):
                new_text = text                                                 # CTA block before a promo code
        if new_text is not None:
            _swap(doc, it, _as_text(it, DocItemLabel.TEXT, new_text))


# ----------------------------------------------------------------------------
# 3. captions
# ----------------------------------------------------------------------------

def _caption_like(item) -> bool:
    if not isinstance(item, TextItem) or item.label not in (*_HEADING_LABELS, *_BODY_LABELS, DocItemLabel.CAPTION):
        return False
    text = (item.text or "").strip()
    return (
        0 < len(text) <= 60
        and len(text.split()) <= 6
        and not text.endswith((".", "?", ":", ",", ";"))
        and not _NUMBERED_RE.match(text)
        and not _is_caps(text)
        and "[Figure description]" not in text
    )


def bind_captions(doc: DoclingDocument) -> None:
    """Attach a short label that sits directly above table(s) as the table's caption.

    ``[cap_a, cap_b, table_a, table_b]`` pairs in order; extra captions stay as they are
    and extra tables stay uncaptioned.  The caption item is re-typed CAPTION, so it leaves
    the heading path, and is referenced from ``table.captions`` so chunk serialisation keeps
    it with the table instead of gluing it to whatever chunk came before.
    """
    seq = _sequence(doc)
    all_bound: list[TextItem] = []
    i = 0
    while i < len(seq):
        if not isinstance(seq[i], TableItem):
            i += 1
            continue
        j = i
        while j < len(seq) and isinstance(seq[j], TableItem) and _page(seq[j]) == _page(seq[i]):
            j += 1
        tables = seq[i:j]
        k = i
        while k > 0 and _caption_like(seq[k - 1]) and _page(seq[k - 1]) == _page(seq[i]) \
                and i - k < len(tables) + 1:
            k -= 1
        caps = seq[k:i]
        if caps:
            n = min(len(caps), len(tables))
            pairs = list(zip(caps[len(caps) - n:], tables[:n])) if len(caps) >= len(tables) \
                else list(zip(caps, tables))
            bound = []
            for cap, tbl in pairs:
                new_cap = _as_text(cap, DocItemLabel.CAPTION)
                _swap(doc, cap, new_cap)
                tbl.captions = [*tbl.captions, RefItem(cref=new_cap.self_ref)]
                bound.append(new_cap)
            all_bound.extend(bound)
        i = j
    by_page: dict[int | None, list[TextItem]] = {}
    for cap in all_bound:                       # v5.8: renumber per page, not per table group
        by_page.setdefault(_page(cap), []).append(cap)
    for caps in by_page.values():
        _renumber_sequence_captions(caps)


def _renumber_sequence_captions(caps: list[TextItem]) -> None:
    """'Day 7', 'Day 2' (OCR read a '1' as '7') -> 'Day 1', 'Day 2'."""
    new = cleanup.renumber_sequence([(c.text or "") for c in caps])
    for c, t in zip(caps, new):
        if t != c.text:
            c.text = t
            c.orig = t


# ----------------------------------------------------------------------------
# 4. heading levels
# ----------------------------------------------------------------------------

def relevel_headings(doc: DoclingDocument) -> None:
    """Give unnumbered headings a level relative to the last numbered heading.

    Numbered headings keep their numbering depth ('7' -> 1, '7.3' -> 2, '9.4.2' -> 3).
    A chapter title is an ALL-CAPS heading that opens its page.  Everything else without
    a number becomes one level deeper than the last numbered heading (>= 2), so
    'Animal Protein' after '9.4.2 Proteins' is level 4 and is closed by '9.4.3 Fats'.
    """
    seq = _sequence(doc)
    last_numbered = 1
    seen_heading = False
    page_first: dict[int | None, int] = {}
    for pos, it in enumerate(seq):
        if isinstance(it, TextItem) and (it.text or "").strip() and _page(it) not in page_first:
            page_first[_page(it)] = pos
        elif not isinstance(it, TextItem):
            page_first.setdefault(_page(it), pos)

    prev_heading_text = None
    for pos, it in enumerate(seq):
        if not _is_heading(it):
            continue
        text = (it.text or "").strip()
        if not text:
            continue
        if text == prev_heading_text:                              # doubled heading
            _swap(doc, it, _as_text(it, DocItemLabel.TEXT, ""))
            continue
        prev_heading_text = text
        if _NUMBERED_RE.match(text):
            level = text.split()[0].rstrip(".").count(".") + 1
            last_numbered = level
        elif not seen_heading:
            level, last_numbered = 1, 1                            # document title
        elif _is_caps(text) and page_first.get(_page(it)) == pos:
            level, last_numbered = 1, 1                            # chapter title
        else:
            level = min(max(last_numbered + 1, 2), 6)
        seen_heading = True
        if getattr(it, "level", None) != level or it.label != DocItemLabel.SECTION_HEADER:
            _swap(doc, it, _as_heading(it, level))


# ----------------------------------------------------------------------------
# 5. echoes
# ----------------------------------------------------------------------------

def dedupe_echoes(doc: DoclingDocument) -> None:
    """Blank a body item that only repeats a neighbouring heading or the previous item."""
    seq = _sequence(doc)

    def norm(t: str) -> str:
        return re.sub(r"\W+", "", t or "").lower()

    for pos, it in enumerate(seq):
        if not isinstance(it, TextItem) or it.label not in _BODY_LABELS or not (it.text or "").strip():
            continue
        me = norm(it.text)
        neighbours = seq[max(0, pos - 3): pos + 4]
        for other in neighbours:
            if other is it or not isinstance(other, TextItem) or _page(other) != _page(it):
                continue
            if norm(other.text) == me and (other.label in _HEADING_LABELS or _idx(other) < _idx(it)):
                it.text = ""
                break


# ----------------------------------------------------------------------------
# entry point
# ----------------------------------------------------------------------------

def repair_heading_numbers(doc: DoclingDocument) -> None:
    """v5.8: '6.5. 1Chest Circuit' -> '6.5.1 Chest Circuit'; '6.2.2' after '6.5.1' -> '6.5.2'."""
    heads = [it for it in _sequence(doc) if _is_heading(it) and (it.text or "").strip()]
    texts = cleanup.repair_heading_sequence([cleanup.fix_heading_number((h.text or "").strip()) for h in heads])
    for h, t in zip(heads, texts):
        if t != h.text:
            h.text = t
            h.orig = t


def blacklist_headings(doc: DoclingDocument) -> None:
    """v5.9 WP6: Blank template headings that should not appear in chunks.

    Converts Titelseite, GB Version, Fig.xy, Abb.xy items to empty text so
    HierarchicalChunker skips them.  Also detects Profile N lines and ensures
    they are labelled as SECTION_HEADER.
    """
    for item in _sequence(doc):
        if not _is_heading(item):
            continue
        text = (item.text or "").strip()
        if not text:
            continue
        if text.lower() in _HEADING_BLACKLIST or _HEADING_BLACKLIST_RE.match(text):
            logger.debug("WP6: blacklisting heading %r", text)
            item.text = ""
            continue
        # Profile N -> ensure SECTION_HEADER label
        if _PROFILE_RE.match(text):
            item.label = DocItemLabel.SECTION_HEADER
        # Numbering regex override: if text starts with N.N.N pattern, enforce level
        if _NUMBERED_OVERRIDE_RE.match(text) and hasattr(item, 'level'):
            depth = text.split()[0].count('.')
            item.level = min(depth + 1, 6)


_DOC_NUMBER_RE = re.compile(r"\b(\d{5,}[A-Z]\d*(?:\.\w+)?)\b")
_DOC_VERSION_RE = re.compile(r"\bV(\d+(?:\.\d+)?)\b")
_DOC_DATE_RE = re.compile(r"\b(\d{1,2}\.\d{4})\b")


def extract_doc_metadata(page_texts: list[str]) -> dict:
    """v5.9 WP6: Extract document number, version, and date from the first pages."""
    try:
        from core.chunk_cleanup import extract_doc_meta
        return extract_doc_meta(page_texts)
    except Exception:
        combined = " ".join(page_texts[:3]) if page_texts else ""
        m_num = _DOC_NUMBER_RE.search(combined)
        m_ver = _DOC_VERSION_RE.search(combined)
        m_date = _DOC_DATE_RE.search(combined)
        return {
            "doc_number": m_num.group(1) if m_num else "",
            "doc_version": m_ver.group(1) if m_ver else "",
            "doc_date": m_date.group(1) if m_date else "",
        }


def repair_pdf_structure(doc: DoclingDocument, vocab: Counter | None = None) -> None:
    """Run every v5.7 document-level pass in dependency order."""
    clean_text_items(doc, vocab)
    repair_heading_numbers(doc)
    demote_pseudo_headings(doc)
    bind_captions(doc)
    relevel_headings(doc)
    dedupe_echoes(doc)
    blacklist_headings(doc)  # v5.9 WP6


# ----------------------------------------------------------------------------
# Cross-Page Heading Normalization & Embedded Heading Splitting
# ----------------------------------------------------------------------------

_SECTION_NUMBER_TOKEN_RE = re.compile(r"\d+\.\d+(?:\.\d+){0,2}")
_PROMOTABLE_HEADING_RE = re.compile(r"^\d+\.\d+(\.\d+){0,2}\s+[A-Z]")
_EMBEDDED_MD_HEADING_RE = re.compile(r"(?<=\S)[ \t]+###\s*\*{0,2}(?P<htext>[^\n*]+)\*{0,2}\s*$")
_LEADING_ALLCAPS_RE = re.compile(r"^\*{0,2}(?P<caps>[A-Z0-9\s/&-]{8,60})\*{0,2}(?:\n|\s{2,}|\s+(?=[a-z]))")
_TOC_LINE_RE = re.compile(r"\.{3,}\s*\d+$")


def _heading_level(text: str, current: int | None = None) -> int:
    """Return the chunker heading level (>=1) for a heading."""
    m = _NUMBERED_RE.match(text)
    if m:
        first = text.split()[0].rstrip(".")
        dots = first.count(".")
        return min(dots + 1, 6)
    if current is not None and current > 0:
        return current
    return 1


def _extract_misplaced_number(text: str) -> tuple[str, int] | None:
    """Relocate section number embedded in heading text."""
    matches = list(_SECTION_NUMBER_TOKEN_RE.finditer(text))
    if not matches:
        return None
    m = matches[0]
    if m.start() == 0:
        return None
    number = m.group(0)
    remainder = (text[: m.start()] + text[m.end() :]).strip()
    remainder = re.sub(r"\s{2,}", " ", remainder)
    if not remainder:
        return None
    return f"{number} {remainder}", number.count(".") + 1


def _split_embedded_headings(doc: DoclingDocument) -> None:
    """Handle heading text that Docling/marko never turned into its own DocItem."""
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

        dup_match = _EMBEDDED_MD_HEADING_RE.search(text)
        if dup_match and dup_match.group("htext").strip() in heading_texts:
            text = text[: dup_match.start()].rstrip()
            item.text = text

        stripped = text.strip()
        caps_match = _LEADING_ALLCAPS_RE.match(stripped)
        if caps_match and len(caps_match.group("caps")) >= 8:
            heading_text = caps_match.group("caps")
            if heading_text not in heading_texts:
                item.text = stripped[caps_match.end() :].strip()
                if stripped.startswith("**") and item.text.endswith("**") and not item.text.startswith("**"):
                    item.text = item.text[:-2].strip()
                try:
                    doc.insert_heading(
                        sibling=item,
                        text=heading_text,
                        level=1,
                        prov=item.prov[0] if getattr(item, "prov", None) else None,
                        after=False,
                    )
                    heading_texts.add(heading_text)
                except Exception:
                    pass


def repair_pdf_headings(doc: DoclingDocument, min_page_repeats: int = 3) -> None:
    """
    Two passes run against the fully-merged document:
    1. Boilerplate demotion: Verbatim text repeating on >= min_page_repeats pages is demoted to PARAGRAPH.
    2. Heading normalization: Fixes heading freeze by converting level 0 TITLE on page > 1 to SectionHeaderItem,
       relocates misplaced section numbers, and promotes numbered paragraphs.
    """
    pages_seen_on: dict[str, set[int]] = {}
    for item in doc.texts:
        stripped = (item.text or "").strip()
        page_no = item.prov[0].page_no if getattr(item, "prov", None) else None
        if stripped and page_no is not None:
            pages_seen_on.setdefault(stripped, set()).add(page_no)

    boilerplate: set[str] = {
        t for t, pages in pages_seen_on.items() if len(pages) >= min_page_repeats
    }

    for i, item in enumerate(doc.texts):
        stripped = (item.text or "").strip()

        # Inactive empty-text headings become plain text
        if item.label in (DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE) and not stripped:
            dump = item.model_dump()
            dump["label"] = DocItemLabel.TEXT
            text_fields = TextItem.model_fields.keys()
            doc.texts[i] = TextItem(**{k: v for k, v in dump.items() if k in text_fields})
            continue

        if not stripped:
            continue

        # Demote boilerplate running lines
        if (
            item.label in (DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE)
            and stripped in boilerplate
        ):
            dump = item.model_dump()
            dump["label"] = DocItemLabel.PARAGRAPH
            text_fields = TextItem.model_fields.keys()
            doc.texts[i] = TextItem(**{k: v for k, v in dump.items() if k in text_fields})
            continue

        # Normalise headings to SectionHeaderItem with deterministic level
        if item.label in (DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE):
            current = getattr(item, "level", None)
            relocated = _extract_misplaced_number(stripped)
            if relocated is not None:
                new_text, level = relocated
                doc.texts[i] = _as_heading(item, level, text=new_text)
            else:
                level = _heading_level(stripped, current)
                page_no = item.prov[0].page_no if getattr(item, "prov", None) else 1
                if item.label == DocItemLabel.TITLE or current != level:
                    # Keep level 0 on page 1 only if it's the doc title
                    if item.label == DocItemLabel.TITLE and page_no > 1:
                        doc.texts[i] = _as_heading(item, level)
                    elif item.label == DocItemLabel.SECTION_HEADER and current != level:
                        doc.texts[i] = _as_heading(item, level)
            continue

        # Promote numbered paragraphs to section headers
        if (
            item.label in (DocItemLabel.PARAGRAPH, DocItemLabel.TEXT)
            and len(stripped) < 80
            and not stripped.endswith((".", ",", ";", ":"))
            and _PROMOTABLE_HEADING_RE.match(stripped)
        ):
            doc.texts[i] = _as_heading(item, _heading_level(stripped, None))

    _split_embedded_headings(doc)


def tag_toc_structures(doc: DoclingDocument) -> None:
    """Tag Table of Contents entries with [TOC] marker."""
    for item in doc.texts:
        text = (item.text or "").strip()
        if _TOC_LINE_RE.search(text):
            if not text.startswith("[TOC]"):
                item.text = f"[TOC] {text}"


# Backward compatibility alias
def repair_headings(doc: DoclingDocument) -> None:
    """Backward-compatible wrapper running heading repairs and structure demotions."""
    repair_pdf_headings(doc)
    demote_pseudo_headings(doc)
