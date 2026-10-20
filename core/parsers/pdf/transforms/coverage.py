from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

_NORM_RE = re.compile(r"[\s\W]+")
_TOC_LINE_RE = re.compile(r"\.{3,}\s*\d+\s*$")


def _norm(text: str) -> str:
    return _NORM_RE.sub(" ", text.lower()).strip()


def check_page_coverage(
    md: str,
    raw_text: str,
    recall_min: float = 0.85,
) -> str:
    """
    Compare raw PyMuPDF text lines against the extracted markdown. Any genuine,
    meaningful text lines completely absent from markdown are appended in a
    '[Recovered text]' block to prevent silent data loss.
    """
    
    if not raw_text or not raw_text.strip():
        return md

    raw_lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
    if not raw_lines:
        return md

    md_norm = _norm(md)
    missing_lines: list[str] = []

    for line in raw_lines:
        
        # Skip Table of Contents dot leaders
        if _TOC_LINE_RE.search(line):
            continue

        # Skip trivial fragments
        if len(line) < 15:
            continue

        line_norm = _norm(line)
        if not line_norm:
            continue

        # If line does not appear in markdown text
        if line_norm not in md_norm:
            missing_lines.append(line)

    if missing_lines:
        recovered_block = "\n\n[Recovered text]\n" + "\n".join(missing_lines)
        return md + recovered_block

    return md

