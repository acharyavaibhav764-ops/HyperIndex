"""v5.8 chunk-level sanitiser. Pure Python - no Docling imports, so it is unit-testable anywhere.

HybridChunker re-serialises Docling items as markdown: an item carrying ``formatting`` comes out as
``**text**`` and a stray ``###`` token survives as text.  This pass runs on the final chunk strings
and removes that markup, drops a trailing line that is really the NEXT chunk's heading, and drops
chunks that have become heading-only or are a stray one-line logo.
"""
from __future__ import annotations

import re
from typing import Any

_ATX = re.compile(r"(?m)(?:^|(?<=[ \t]))(?:#{2,6}|#(?=[ \t]*\*\*))[ \t]*")
_ITALIC = re.compile(r"(?<![*\w])\*(?![\s*])([^*\n]+?)(?<![\s*])\*(?![*\w])")
_INNER_SPACES = re.compile(r"(?<=\S)[ \t]{2,}(?=\S)")      # also collapses markdown-table padding


def strip_markup(text: str) -> str:
    """Remove leaked '###', '**bold**', '*italic*' and collapse inner runs of spaces."""
    text = _ATX.sub("", text)
    text = text.replace("**", "")
    text = _ITALIC.sub(r"\1", text)
    return _INNER_SPACES.sub(" ", text)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", strip_markup(s)).strip().casefold()


def is_micro_label(text: str) -> bool:
    """One short line of <= 3 words with no digits (a running logo such as 'Calisthenics Family')."""
    t = text.strip()
    return "\n" not in t and len(t) < 40 and len(t.split()) <= 3 and not re.search(r"\d", t)


def postprocess_chunks(
    chunks: list[str], metas: list[dict[str, Any]], *, drop_micro: bool = False
) -> tuple[list[str], list[dict[str, Any]]]:
    """Clean chunk strings; drop echo-only / micro chunks.  ``chunk_index`` is NOT renumbered here."""
    lines = [strip_markup(c).strip().split("\n") for c in chunks]
    out_chunks: list[str] = []
    out_metas: list[dict[str, Any]] = []
    for i, ls in enumerate(lines):
        nxt = {_norm(x) for x in lines[i + 1][:3]} if i + 1 < len(lines) else set()
        if len(ls) > 1 and nxt:
            last = ls[-1].strip()
            if last and len(last) <= 120 and not last.startswith("|") and _norm(last) in nxt:
                ls = ls[:-1]                       # '... ### **3.2 Basics**' glued to previous chunk
        norms = {_norm(x) for x in ls if x.strip()}
        if nxt and norms and norms <= nxt:         # only headings left, and the next chunk has them
            continue
        text = "\n".join(ls).strip()
        if drop_micro and is_micro_label(text):
            continue                               # e.g. a lone running logo 'Calisthenics Family'
        out_chunks.append(text)
        out_metas.append(metas[i])
    return out_chunks, out_metas
