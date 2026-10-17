"""v5.9 chunk-level sanitiser (extends v5.8). Pure Python — no Docling imports.

v5.8: strip_markup, postprocess_chunks (echo/micro drop).
v5.9 WP1: _collapse_sep_rows, _strip_dot_runs, heading-merge, junk-drop.
v5.9.1:
  WP1: junk test ignores the breadcrumb lines in front of a table; a header-only table
       fragment is carried into the header-less table chunks that follow it.
  WP2: ToC chunks are tagged content_type='toc' and merged into a single compact chunk.
  WP6: section_id() returns 'p28:1.2'; extract_doc_meta() extracts doc_number/version/date
       with fixed regexes (negative-lookbehind prevents over-matching GB0_V2).
"""
from __future__ import annotations

import re
from typing import Any

_ATX = re.compile(r"(?m)(?:^|(?<=[ \t]))(?:#{2,6}|#(?=[ \t]*\*\*))[ \t]*")
_ITALIC = re.compile(r"(?<![*\w])\*(?![\s*])([^*\n]+?)(?<![\s*])\*(?![*\w])")
_INNER_SPACES = re.compile(r"(?<=\S)[ \t]{2,}(?=\S)")
_SEP_ROW_RE = re.compile(r"^\|(\s*:?-{2,}:?\s*\|)+\s*$")   # v5.9 WP1
_DOT_RUN_RE = re.compile(r"\.{4,}")                          # v5.9 WP1
_JUNK_CHUNK_RE = re.compile(r"^[\s|:\-.]*$")                  # v5.9 WP1
# v5.9.4: a table separator row that the line chunker cut in half loses its leading "|"
# ("-------|--------|-------|"), so it no longer counts as a table line.
_SEP_FRAG_RE = re.compile(r"^[\s|:\-]*-[\s|:\-]*$")

# v5.9.1 WP2: ToC detection
_TOC_HEAD_RE = re.compile(r"^(?:table of )?contents?\W*$|^inhalt(?:sverzeichnis)?\W*$", re.I)
_TOC_ROW_RE = re.compile(
    r"\.{3,}\s*\|?\s*\d+\s*\|?\s*$|^\|\s*\d+(?:\.\d+)*\.?\s*\|.*\|\s*\d+\s*\|\s*$"
)

# v5.9.2: reflowed ToC. PyMuPDF4LLM joins the lines of a ToC page and the dot leaders are gone by
# the time detection runs, so the dot-leader test above never fires on continuation pages
# ("... tunnel socket) 9 2.4 Inserting the connection board ... 10 2.5 Installation ... 12").
# Count "section-number title page-number" entries instead.
_TOC_ENTRY_RE = re.compile(
    r"(?<![\w.])\d+(?:\.\d+){0,3}\.?\s+[A-Za-z(][^\n|]{2,90}?\s+\d{1,3}"
    r"(?=\s+\d+(?:\.\d+){0,3}\.?\s+[A-Za-z(]|\s*$)",
    re.M,
)

# v5.9.1 WP6: metadata regexes (fixed: negative-lookbehind prevents over-matching)
_HEAD_NUM_RE = re.compile(r"^\s*(\d+(?:\.\d+)*?)\.?\s")
_DOC_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])(\d{5,}[A-Z]\d*\.[A-Za-z0-9]+)")
_DOC_VERSION_RE = re.compile(r"(?<![A-Za-z0-9])V(\d+(?:\.\d+)?)(?![A-Za-z0-9.])")
_DOC_DATE_RE = re.compile(r"(?<![\d.])(\d{1,2}\.\d{4})(?![\d.])")


def strip_markup(text: str) -> str:
    """Remove leaked '###', '**bold**', '*italic*' and collapse inner runs of spaces."""
    text = _ATX.sub("", text)
    text = text.replace("**", "")
    text = _ITALIC.sub(r"\1", text)
    return _INNER_SPACES.sub(" ", text)


def _collapse_sep_rows(text: str) -> str:
    """v5.9 WP1: Replace wide markdown separator rows with compact |---|---|.

    MarkdownTableSerializer pads the separator to the widest cell width,
    inflating the repeated-header prefix past the 256-token chunk limit.
    """
    lines = text.split("\n")
    out = []
    for line in lines:
        stripped = line.strip()
        if _SEP_ROW_RE.match(stripped):
            cols = max(stripped.count("|") - 1, 1)
            line = "|" + "---|" * cols
        out.append(line)
    return "\n".join(out)


def _is_sep_fragment_chunk(ls: list[str]) -> bool:
    """v5.9.4: breadcrumb heading(s) + a lone separator fragment, nothing else."""
    sep = [x for x in ls if x.strip() and _SEP_FRAG_RE.match(x.strip())]
    rest = [x for x in ls if x.strip() and not _SEP_FRAG_RE.match(x.strip())]
    def breadcrumb(x: str) -> bool:      # a heading, not a sentence of body text
        x = x.strip()
        return not x.startswith("|") and len(x) <= 100 and len(x.split()) <= 14 and not x.endswith(".")

    return bool(sep) and len(rest) <= 3 and all(breadcrumb(x) for x in rest)


def _strip_dot_runs(text: str) -> str:
    """v5.9 WP1: Replace dot-leader sequences of 4+ dots with '...'."""
    return _DOT_RUN_RE.sub("...", text)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", strip_markup(s)).strip().casefold()


def is_micro_label(text: str) -> bool:
    """One short line of <= 3 words with no digits (a running logo such as 'Calisthenics Family')."""
    t = text.strip()
    return "\n" not in t and len(t) < 40 and len(t.split()) <= 3 and not re.search(r"\d", t)


# -------------------------------------------------------------------------
# v5.9.1 WP6: section_id and extract_doc_meta
# -------------------------------------------------------------------------

def section_id(page: int | None, headings: Any) -> str:
    """v5.9.1 WP6: 'p28:1.2' = page + number of the closest numbered heading (else 'p28')."""
    base = f"p{page}" if page is not None else ""
    for h in reversed(list(headings or [])):
        m = _HEAD_NUM_RE.match(str(h))
        if m:
            return f"{base}:{m.group(1)}" if base else m.group(1)
    return base


def extract_doc_meta(page_texts: list[str]) -> dict[str, str]:
    """v5.9.1 WP6: doc_number / doc_version / doc_date from the first three pages ('' if absent)."""
    meta = {"doc_number": "", "doc_version": "", "doc_date": ""}
    for text in page_texts[:3]:
        if not meta["doc_number"] and (m := _DOC_NUMBER_RE.search(text)):
            meta["doc_number"] = m.group(1)
        if not meta["doc_version"] and (m := _DOC_VERSION_RE.search(text)):
            meta["doc_version"] = f"V{m.group(1)}"
        if not meta["doc_date"] and (m := _DOC_DATE_RE.search(text)):
            meta["doc_date"] = m.group(1)
    return meta


# -------------------------------------------------------------------------
# v5.9.1 WP2: ToC tagging and merging helpers
# -------------------------------------------------------------------------

def _table_lines(ls: list[str]) -> list[str]:
    return [x for x in ls if x.strip().startswith("|")]


def _last_heading(meta: dict[str, Any]) -> str:
    hp = meta.get("heading_path")
    if isinstance(hp, (list, tuple)):
        return str(hp[-1]).strip() if hp else ""
    return str(hp or "").split(" > ")[-1].strip()


def _toc_entry_stats(text: str) -> tuple[int, float]:
    """(number of 'N.N Title page' entries, share of the text they cover)."""
    ms = list(_TOC_ENTRY_RE.finditer(text))
    return len(ms), sum(len(m.group()) for m in ms) / max(1, len(text))


def _is_toc_chunk(text: str, meta: dict[str, Any], prev_is_toc: bool = False) -> bool:
    if _TOC_HEAD_RE.match(_last_heading(meta)):
        return True
    lines = [x.strip() for x in text.split("\n") if x.strip() and not _SEP_ROW_RE.match(x.strip())]
    hits = sum(1 for x in lines if _TOC_ROW_RE.search(x))
    if hits >= 2 and hits / len(lines) >= 0.5:
        return True
    # v5.9.2: reflowed ToC rows without dot leaders; a ToC that continues on the next page has
    # no 'Contents' heading, so a chunk right after a ToC chunk needs far less evidence.
    n, cov = _toc_entry_stats(text)
    if (n >= 4 and cov >= 0.55) or (prev_is_toc and n >= 2 and cov >= 0.4):
        return True
    low = text.lower()
    return prev_is_toc and n == 0 and "table of contents" in low and len(text) < 400


def _toc_lines(text: str) -> list[str]:
    out: list[str] = []
    for x in text.split("\n"):
        s = x.replace("[TOC]", "").replace("[Recovered text]", "").strip()
        if not s or _SEP_ROW_RE.match(s) or _TOC_HEAD_RE.match(s) or s.lower().startswith("table of contents"):
            continue
        s = " ".join(c.strip() for c in s.strip("|").split("|") if c.strip())
        s = re.sub(r"\s{2,}", " ", re.sub(r"\.{2,}", " ", s)).strip()
        # v5.9.2: keep real entries only - running headers have no page number, legal prose is long
        if s and (_TOC_ENTRY_RE.search(s) or (len(s) <= 80 and re.search(r"\d", s))):
            out.append(s)
    return out


def _union_pages(a: Any, b: Any) -> Any:
    def as_list(v: Any) -> list[int]:
        if isinstance(v, (list, tuple)):
            return [int(i) for i in v]
        return [int(i) for i in str(v or "").split(",") if i.strip().isdigit()]

    u = sorted(set(as_list(a)) | set(as_list(b)))
    return u if isinstance(a, (list, tuple)) or a is None else ",".join(str(i) for i in u)


def _merge_toc(chunks: list[str], metas: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    """v5.9.1 WP2: collapse every run of consecutive ToC chunks into ONE compact 'toc' chunk."""
    out_c: list[str] = []
    out_m: list[dict[str, Any]] = []
    run: list[str] = []
    run_meta: dict[str, Any] | None = None
    for c, m in zip(chunks, metas):
        if m.get("content_type") == "toc":
            run.extend(_toc_lines(c))
            if run_meta is None:
                run_meta = dict(m)
            else:
                run_meta["page_numbers"] = _union_pages(run_meta.get("page_numbers"), m.get("page_numbers"))
            continue
        if run_meta is not None:
            out_c.append("Table of contents\n" + "\n".join(dict.fromkeys(run)))
            out_m.append(run_meta)
            run, run_meta = [], None
        out_c.append(c)
        out_m.append(m)
    if run_meta is not None:
        out_c.append("Table of contents\n" + "\n".join(dict.fromkeys(run)))
        out_m.append(run_meta)
    return out_c, out_m


# -------------------------------------------------------------------------
# Main entry point
# -------------------------------------------------------------------------

def postprocess_chunks(
    chunks: list[str], metas: list[dict[str, Any]], *, drop_micro: bool = False
) -> tuple[list[str], list[dict[str, Any]]]:
    """Clean chunks: collapse separators, strip dots, drop junk, merge heading-only into next.

    v5.9.1: junk test ignores the breadcrumb lines in front of a table; a header-only table
    fragment is carried into the header-less table chunks that follow it; ToC chunks are tagged
    content_type='toc' (incl. dot-leader recovered text) and merged into a single chunk.
    """
    cleaned: list[str] = []
    for c in chunks:
        c = strip_markup(c).strip()
        c = _collapse_sep_rows(c)
        c = _strip_dot_runs(c)
        cleaned.append(c)

    lines_list = [c.split("\n") for c in cleaned]
    has_table = [bool(_table_lines(x)) for x in lines_list]
    n = len(lines_list)

    pending_heading: str = ""
    table_hdr: list[str] | None = None
    out_chunks: list[str] = []
    out_metas: list[dict[str, Any]] = []

    for i, ls in enumerate(lines_list):
        nxt = {_norm(x) for x in lines_list[i + 1][:3]} if i + 1 < n else set()

        # Drop trailing line that is really the NEXT chunk's heading (v5.8)
        if len(ls) > 1 and nxt:
            last = ls[-1].strip()
            if last and len(last) <= 120 and not last.startswith("|") and _norm(last) in nxt:
                ls = ls[:-1]

        text = "\n".join(ls).strip()
        tl = _table_lines(ls)
        non_tl = [x for x in ls if x.strip() and not x.strip().startswith("|")]

        # Drop separator-only junk, also when a breadcrumb sits in front of it (v5.9.1)
        if _JUNK_CHUNK_RE.match(text) or _is_sep_fragment_chunk(ls) or (
            tl and len(non_tl) <= 3 and all(_JUNK_CHUNK_RE.match(x.strip()) for x in tl)
        ):
            continue

        if drop_micro and is_micro_label(text):
            continue

        norms = {_norm(x) for x in ls if x.strip()}

        if nxt and norms and norms <= nxt:
            pending_heading = text if not pending_heading else pending_heading + "\n" + text
            continue

        # v5.9.1: table header bookkeeping
        if not tl or any(_SEP_ROW_RE.match(x.strip()) for x in tl):
            table_hdr = None
        elif (
            len(tl) == 1 and i + 1 < n and has_table[i + 1]
            and not (i > 0 and has_table[i - 1] and _last_heading(metas[i - 1]) == _last_heading(metas[i]))
        ):
            hdr = tl[0].strip()
            if not hdr.endswith("|"):
                hdr += " |"
            table_hdr = [hdr, "|" + "---|" * max(hdr.count("|") - 1, 1)]
            continue  # header-only fragment: re-attached to the chunks below
        elif table_hdr:
            first = next(j for j, x in enumerate(ls) if x.strip().startswith("|"))
            text = "\n".join(ls[:first] + table_hdr + ls[first:])

        if pending_heading:
            text = pending_heading + "\n" + text
            pending_heading = ""

        out_chunks.append(text)
        out_metas.append(metas[i])

    if pending_heading:
        out_chunks.append(pending_heading)
        if metas:
            out_metas.append(metas[-1])

    # v5.9.1 WP2: tag + merge ToC chunks
    tagged: list[dict[str, Any]] = []
    prev_toc = False
    for c, m in zip(out_chunks, out_metas):
        is_toc = m.get("content_type") == "toc" or _is_toc_chunk(c, m, prev_toc)
        if is_toc and m.get("content_type") != "toc":
            m = {**m, "content_type": "toc"}
        prev_toc = is_toc
        tagged.append(m)
    return _merge_toc(out_chunks, tagged)
