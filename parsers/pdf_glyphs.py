"""v5.9.2 / v5.9.3: map Wingdings / Symbol private-use glyphs to real text.

Why: Honeywell manuals draw ticks, arrows and circled call-out numbers with the Wingdings font.
Both PyMuPDF4LLM and Docling return those glyphs as private-use code points (U+F0xx), e.g. a
feature-table tick is U+F0FC. They render as blanks / boxes, are useless to an embedding model,
and were never touched by v5.9 / v5.9.1 (which only looked for tick *images*).

Pure Python, no third-party imports.
"""
from __future__ import annotations

import re

_PUA_RE = re.compile("[\ue000-\uf8ff]")

_TICKS = frozenset({"\uf0fc", "\uf0fe"})   # Wingdings 0xFC check, 0xFE ballot box with check
_CROSSES = frozenset({"\uf0fb", "\uf0fd"})  # Wingdings 0xFB cross, 0xFD ballot box with x

# Running-text replacements. Wingdings 0x81..0x8A are the circled numbers 1..10.
_TEXT_MAP: dict[str, str] = {
    "\uf0fc": "\u2713", "\uf0fe": "\u2713",
    "\uf0fb": "\u2717", "\uf0fd": "\u2717",
    "\uf0e8": "\u2192",                                   # Wingdings 0xE8 arrow
    "\uf0b7": "\u2022", "\uf0a7": "\u2022", "\uf06c": "\u2022",   # bullets
    "\uf076": "\u2022", "\uf0d8": "\u2022",
}
_TEXT_MAP.update({chr(0xF081 + i): chr(0x2460 + i) for i in range(10)})   # F081.. -> 1..10 in circles

_FULLWIDTH_RE = re.compile("[\uff01-\uff5e]")   # v5.9.3: fullwidth ( ) : etc. from East-Asian-style templates

_CELL_NOISE_RE = re.compile(r"(\*\*|<br\s*/?>|\s)")


def _cell_core(cell: str) -> str:
    return _CELL_NOISE_RE.sub("", cell)


def _fix_table_line(line: str) -> str:
    parts = line.split("|")
    for i, cell in enumerate(parts):
        core = _cell_core(cell)
        if not core:
            continue
        chars = set(core)
        if chars <= _TICKS:
            parts[i] = " Yes "
        elif chars <= _CROSSES:
            parts[i] = " No "
    return "|".join(parts)


def _ascii(text: str) -> str:
    return _FULLWIDTH_RE.sub(lambda m: chr(ord(m.group()) - 0xFEE0), text)


def normalize_glyphs(md: str) -> str:
    """Page markdown: a table cell that is only a tick -> 'Yes' (cross -> 'No'); every other
    private-use glyph is mapped through _TEXT_MAP, unknown ones are dropped."""
    if not md:
        return md
    md = _ascii(md)
    if not _PUA_RE.search(md):
        return md
    out = []
    for line in md.split("\n"):
        if line.lstrip().startswith("|"):
            line = _fix_table_line(line)
        out.append(_PUA_RE.sub(lambda m: _TEXT_MAP.get(m.group(), ""), line))
    return "\n".join(out)


def strip_glyphs(text: str) -> str:
    """Raw PyMuPDF page text (used only for the coverage comparison): drop private-use glyphs
    so they are not reported as 'missing words'."""
    return _PUA_RE.sub("", _ascii(text)) if text else text
