from __future__ import annotations

import re

# Private Use Area code points (U+E000 to U+F8FF)
_PUA_RE = re.compile(r"[\ue000-\uf8ff]")

# Honeywell manual Wingdings glyphs for ticks and crosses
_TICKS = frozenset({"\uf0fc", "\uf0fe"})   # Wingdings 0xFC check, 0xFE ballot box with check
_CROSSES = frozenset({"\uf0fb", "\uf0fd"})  # Wingdings 0xFB cross, 0xFD ballot box with x

# Running-text replacements for arrows, bullets, and circled call-out numbers
_TEXT_MAP: dict[str, str] = {
    "\uf0fc": "\u2713", "\uf0fe": "\u2713",  # checkmarks
    "\uf0fb": "\u2717", "\uf0fd": "\u2717",  # crosses
    "\uf0e8": "\u2192",                      # arrow
    "\uf0b7": "\u2022", "\uf0a7": "\u2022",  # bullets
    "\uf06c": "\u2022", "\uf076": "\u2022",
    "\uf0d8": "\u2022",
}
# Map Wingdings 0xF081..0xF08A to circled numbers ①..⑩
_TEXT_MAP.update({chr(0xF081 + i): chr(0x2460 + i) for i in range(10)})

_FULLWIDTH_RE = re.compile(r"[\uff01-\uff5e]")
_CELL_NOISE_RE = re.compile(r"(\*\*|<br\s*/?>|\s)")


def _cell_core(cell: str) -> str:
    return _CELL_NOISE_RE.sub("", cell)


def _fix_table_line(line: str) -> str:
    """Replace single-glyph checkmark/cross table cells with 'Yes' / 'No'."""
    
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
    """Normalize full-width punctuation into ASCII."""
    
    return _FULLWIDTH_RE.sub(lambda m: chr(ord(m.group()) - 0xFEE0), text)


def normalize_glyphs(md: str) -> str:
    """
    Normalize private-use symbol glyphs in markdown text:
    - Table cells containing only a checkmark glyph become 'Yes' (cross -> 'No').
    - Wingdings bullets and arrows are mapped to standard Unicode equivalents.
    - Unmapped private-use code points are stripped.
    """
    
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
    """Drop private-use glyphs entirely from raw text."""
    
    return _PUA_RE.sub("", _ascii(text)) if text else text

