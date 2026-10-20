from __future__ import annotations

import logging
import re
from docling_core.types.doc import (
    DocItemLabel,
    DoclingDocument,
    SectionHeaderItem,
    TextItem,
)

logger = logging.getLogger(__name__)

# Matches standard dotted numbered section headings: "7.6 Specificity", "9.4.2 Proteins"
_NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+){0,3})\s+\S")

# Buttons / Call to action lines erroneously classified as headings by font size
_BUTTON_RE = re.compile(
    r"^(?:get|start|more|transform|buy|shop|learn|join|download|order|sign|click)\b",
    re.IGNORECASE,
)

# Table of Contents line patterns with dot leaders (e.g. "Installation ... 14")
_TOC_LINE_RE = re.compile(r"\.{3,}\s*\d+$")


def _heading_level(text: str) -> int:
    """Derive deterministic section level from dotted numbering depth (e.g. '7.3' -> 2)."""
    
    match = _NUMBERED_HEADING_RE.match(text)
    if match:
        dots = match.group(1).count(".")
        return min(dots + 1, 6)
    return 1


def repair_headings(doc: DoclingDocument) -> None:
    """
    Repair heading labels and levels to fix the 'heading freeze' bug in HybridChunker:
    1. Converts any TitleItem (level 0) on page > 1 into a SectionHeaderItem.
    2. Assigns deterministic heading levels derived from numbered section depth.
    3. Demotes call-to-action buttons misidentified as headings.
    """
    
    for i, item in enumerate(doc.texts):
        label = item.label
        text = (item.text or "").strip()

        if not text:
            continue

        page_no = item.prov[0].page_no if getattr(item, "prov", None) else 1

        # 1. Demote button / call-to-action pseudo-headings
        if label in (DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE):
            if _BUTTON_RE.search(text) and len(text) < 50:
                dump = item.model_dump()
                dump["label"] = DocItemLabel.TEXT
                dump.pop("level", None)  # TextItem does not have a level attribute
                doc.texts[i] = TextItem(**dump)
                continue

        # 2. Fix Heading Freeze:
        # A TitleItem (level 0) on page > 1 freezes HybridChunker context.
        # Normalize TitleItems and SectionHeaderItems to have proper levels.
        if label == DocItemLabel.TITLE and page_no > 1:
            level = _heading_level(text)
            dump = item.model_dump()
            dump["label"] = DocItemLabel.SECTION_HEADER
            dump["level"] = level
            doc.texts[i] = SectionHeaderItem(**dump)

        elif label == DocItemLabel.SECTION_HEADER:
            # Relevel based on dotted numbers if present
            if _NUMBERED_HEADING_RE.match(text):
                level = _heading_level(text)
                if getattr(item, "level", None) != level:
                    dump = item.model_dump()
                    dump["level"] = level
                    doc.texts[i] = SectionHeaderItem(**dump)


def tag_toc_structures(doc: DoclingDocument) -> None:
    """
    Detect Table of Contents structures and tag items with [TOC] marker
    to allow downstream filtering.
    """
    
    for item in doc.texts:
        text = (item.text or "").strip()
        if _TOC_LINE_RE.search(text):
            if not text.startswith("[TOC]"):
                item.text = f"[TOC] {text}"

