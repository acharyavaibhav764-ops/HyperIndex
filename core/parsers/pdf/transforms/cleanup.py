"""v5.7+ PDF text/markdown clean-up (pure functions, no Docling imports).

Vocabulary-guided space repair, table normalisation, ToC detection (v5.9 WP2).
Called from pdf_router per page before DoclingDocument conversion.
"""
from __future__ import annotations

import difflib
import math
import re
from collections import Counter
from typing import Iterable

try:
    from config import settings
except Exception:
    settings = None

_WORD_RE = re.compile(r"[A-Za-z]+")
_MIN_PART_COUNT = 1     # every piece of a split word must occur in the document
_PIECE_COST = 3.0       # per-piece penalty: prefer fewer, more frequent pieces
_TWO_LETTER_OK = frozenset("of on in to is it as at be by do if no or so up we an my me he us go".split())

# ----------------------------------------------------------------------------
# Vocabulary
# ----------------------------------------------------------------------------

def build_vocab(texts: Iterable[str]) -> Counter:
    """Lowercase word counts over ``texts`` (typically each page's text layer)."""
    vocab: Counter = Counter()
    for t in texts:
        vocab.update(w.lower() for w in _WORD_RE.findall(t or ""))
    return vocab


def segment_words(token: str, vocab: Counter) -> list[str] | None:
    """Split ``token`` into 2-4 words the document itself uses, or return None.

    Dynamic programme maximising summed log-frequency minus a per-piece cost.
    Pieces need >= 3 letters, except common two-letter function words and a
    leading 'a'.  Returns None when no full segmentation exists.
    """
    low = token.lower()
    n = len(low)
    best: list[tuple[float, list[str]] | None] = [None] * (n + 1)
    best[0] = (0.0, [])
    for end in range(1, n + 1):
        for start in range(max(0, end - 20), end):
            prev = best[start]
            piece = low[start:end]
            if prev is None or vocab.get(piece, 0) < _MIN_PART_COUNT:
                continue
            ok = len(piece) >= 3 or (len(piece) == 2 and piece in _TWO_LETTER_OK) \
                or (piece == "a" and start == 0)
            if not ok:
                continue
            score = prev[0] + math.log(vocab[piece] + 1) - _PIECE_COST
            if best[end] is None or score > best[end][0]:
                best[end] = (score, prev[1] + [piece])
    res = best[n]
    if res is None or not (2 <= len(res[1]) <= 4):
        return None
    return res[1]


def _recase(original: str, pieces: list[str]) -> str:
    if original.isupper() and len(original) > 3:
        return " ".join(p.upper() for p in pieces)
    out = " ".join(pieces)
    return out[:1].upper() + out[1:] if original[:1].isupper() else out


_ALPHA_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{6,}(?![A-Za-z0-9])")


def fix_lost_spaces(text: str, vocab: Counter) -> str:
    """Re-insert spaces in words that OCR/extraction glued together."""
    if not vocab:
        return text

    def repl(m: re.Match) -> str:
        tok = m.group(0)
        if not (tok.islower() or tok.istitle() or tok.isupper()):
            # CamelCase glue ('RingDips', 'BentArm'): split only when every piece is a
            # word this document uses; anything else (hetCOI, iPhone) is left alone.
            if re.fullmatch(r"(?:[A-Z][a-z]+){2,4}", tok) and vocab.get(tok.lower(), 0) == 0:
                parts = re.findall(r"[A-Z][a-z]+", tok)
                if all(vocab.get(w.lower(), 0) > 0 for w in parts):
                    return " ".join(parts)
            return tok
        if vocab.get(tok.lower(), 0) > 0:
            return tok                      # the text layer itself uses this word: never touch it
        pieces = segment_words(tok, vocab)
        return _recase(tok, pieces) if pieces else tok

    return _ALPHA_TOKEN_RE.sub(repl, text)

# ----------------------------------------------------------------------------
# Spaced-out lettering ("T H E  F U L L ...", "R o u n d 1")
# ----------------------------------------------------------------------------

_LETTER_RUN_RE = re.compile(r"(?<![A-Za-z])(?:[A-Za-z] ){3,}[A-Za-z](?![A-Za-z])")


def collapse_letter_spacing(text: str, vocab: Counter | None = None) -> str:
    """'R o u n d' -> 'Round'; long runs are re-split into words via the vocabulary."""
    def repl(m: re.Match) -> str:
        joined = m.group(0).replace(" ", "")
        if len(joined) >= 10 and vocab:
            pieces = segment_words(joined, vocab)
            if pieces:
                return _recase(joined, pieces)
        return joined
    return _LETTER_RUN_RE.sub(repl, text)

# ----------------------------------------------------------------------------
# URLs
# ----------------------------------------------------------------------------

_URL_RE = re.compile(
    r"(?P<scheme>https?):\s*/\s*/\s*"
    r"(?P<body>[A-Za-z0-9][A-Za-z0-9._~%-]*"                     # host
    r"(?:\s*/(?:\s*[a-z0-9][A-Za-z0-9._~%-]*)?"                # '/ path' with stray spaces
    r"|\s+-[a-z0-9][A-Za-z0-9._~%-]*)*)",                       # 'bmr -calculator'
    re.I,
)


def rejoin_urls(text: str) -> str:
    """'https:/ /site.com / meal-plan' -> 'https://site.com/meal-plan'.

    A path segment separated from its '/' by whitespace must start lowercase/digit,
    so a following sentence ('...calculator/ You can') is not swallowed.
    """
    def repl(m: re.Match) -> str:
        body = re.sub(r"\s+", "", m.group("body"))
        trail = ""
        while body and body[-1] in ".,;:":
            trail = body[-1] + trail
            body = body[:-1]
        return f"{m.group('scheme').lower()}://{body}{trail}"
    return _URL_RE.sub(repl, text)

# ----------------------------------------------------------------------------
# Markup, whitespace and known corpus fixes
# ----------------------------------------------------------------------------

_BOLD_HYPHEN_RE = re.compile(r"\*\*\s*(?:<sup>)?\s*\*\*-\*\*\s*(?:</sup>)?\s*\*\*")   # mind**<sup>**-**</sup> **set**
_SUP_TAG_RE = re.compile(r"</?sup>", re.I)
_BOLD_JOIN_RE = re.compile(r"\*\*\s+\*\*")                     # **a** **b** -> **a b**
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_ATX_RE = re.compile(r"(?:(?<=\s)|^)(?:#{2,6}|#(?=\s*\*\*))\s*")   # v5.8: also a trailing '###'
_LEAD_BULLET_RE = re.compile(r"^\s*(?:>|[•·▪■◦])\s+")


def strip_markup(text: str) -> str:
    """Remove leaked markdown ('**', '###', '<br>', picture-text comments)."""
    text = _HTML_COMMENT_RE.sub(" ", text) if "<!--" in text else text
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = _SUP_TAG_RE.sub("", text)
    text = _ATX_RE.sub("", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.S)
    return text.replace("**", "")


def join_soft_breaks(text: str) -> str:
    r"""'15\n-\n30' -> '15-30'; single newlines inside a paragraph -> space."""
    text = re.sub(r"(?<=\w)[ \t]*\n[ \t]*-[ \t]*\n[ \t]*(?=\w)", "-", text)
    text = re.sub(r"(?<=\w)-[ \t]*\n[ \t]*(?=[a-z])", "-", text)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    return re.sub(r"[ \t]{2,}", " ", text)


_PUNCT_SPACE_RE = re.compile(r"\s+([.,;:!?%])(?=\s|$)|\(\s+|\s+\)")


def fix_punct_spacing(text: str) -> str:
    """'Exc . 1' -> 'Exc. 1'; '( per 100 g )' -> '(per 100 g)'."""
    def repl(m: re.Match) -> str:
        s = m.group(0)
        if s.startswith("("):
            return "("
        if s.endswith(")"):
            return ")"
        return m.group(1)
    return _PUNCT_SPACE_RE.sub(repl, text)


# (pattern, replacement).  Corrections for errors baked into this corpus's own
# text layer, which no generic rule can recover.
KNOWN_FIXES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bper\s?[lI1][O0o][O0o]\s?g\b"), "per 100g"),
    (re.compile(r"\bSguat(s?)\b"), r"Squat\1"),
    (re.compile(r"\bFlowever\b"), "However"),
    (re.compile(r"\bTyperwriter\b"), "Typewriter"),
    (re.compile(r"\bDicount\b|\bdicount\b"), "discount"),
    (re.compile(r"\bTHEFULLJOURNEYTIMELINE\b"), "THE FULL JOURNEY TIMELINE"),
]
PROMO_CODES: tuple[str, ...] = ("BEGINNER25", "FULLJOURNEY25", "BURNFAT25")
_CODE_RE = re.compile(r"(?i:\b(code)\b)(\s*[‘'’\"“]?\s*)([A-Za-z][A-Za-z0-9 ]{5,20}?)(?=\s*[‘'’\"”*]|\s+(?i:for|to)\b)")


def fix_promo_codes(text: str, codes: Iterable[str] = PROMO_CODES) -> str:
    """Snap a mangled 'Use Code X' token to the nearest known code (>= 0.7 similar)."""
    codes = tuple(codes)

    def repl(m: re.Match) -> str:
        raw = re.sub(r"\s+", "", m.group(3)).upper()
        if raw in codes:
            return m.group(1) + m.group(2) + raw
        match = difflib.get_close_matches(raw, codes, n=1, cutoff=0.7)
        return m.group(1) + m.group(2) + (match[0] if match else m.group(3))

    return _CODE_RE.sub(repl, text)


def apply_known_fixes(text: str) -> str:
    for pat, rep in KNOWN_FIXES:
        text = pat.sub(rep, text)
    return fix_promo_codes(text)


def dedupe_doubled_text(text: str) -> str:
    """Collapse 'A A\'' (same paragraph extracted twice, once with lost spaces) to one copy.

    Compares letters only, so 'fluidperhour' and 'fluid per hour' count as equal.
    Keeps the copy that has more spaces (the better-extracted one).
    """
    if len(text) < 80:
        return text
    idx_map = [i for i, ch in enumerate(text) if ch.isalnum()]
    compact = "".join(text[i].lower() for i in idx_map)
    head = compact[:24]
    if len(head) < 24:
        return text
    rep = compact.find(head, 24)
    if rep < 0 or not (0.3 * len(compact) <= rep <= 0.7 * len(compact)):
        return text
    a_end, b_start = idx_map[rep - 1] + 1, idx_map[rep]
    a, b = text[:a_end].strip(), text[b_start:].strip()
    ca, cb = compact[:rep], compact[rep:]
    if abs(len(ca) - len(cb)) > 0.15 * max(len(ca), len(cb)):
        return text
    if difflib.SequenceMatcher(None, ca, cb, autojunk=False).ratio() < 0.93:
        return text
    return a if a.count(" ") >= b.count(" ") else b


def normalize_text(text: str, vocab: Counter | None = None, *, is_heading: bool = False) -> str:
    """Full per-text-item normaliser (idempotent)."""
    if not text:
        return text
    text = strip_markup(text)
    text = join_soft_breaks(text) if not is_heading else re.sub(r"\s+", " ", text)
    text = collapse_letter_spacing(text, vocab)
    text = rejoin_urls(text)
    text = fix_punct_spacing(text)
    text = apply_known_fixes(text)
    if vocab:
        text = fix_lost_spaces(text, vocab)
    return re.sub(r"[ \t]{2,}", " ", text).strip()

# ----------------------------------------------------------------------------
# Noise (photo OCR fragments) and running footers
# ----------------------------------------------------------------------------

_JUNK_SYMBOLS = frozenset("^ ~ | _ » « ¦ ■ □".split())


def is_noise_paragraph(par: str) -> bool:
    """True for photo-OCR debris such as '*<br>I<br>is<br>*' or 'ML m &\\n191 ...'.

    Counts characters that sit in alphabetic words of >= 3 letters or in numbers;
    a short paragraph where those are < 60% of all non-space characters is noise.
    'Body of 10.2.' (word + number) is kept, 'ML m & 191 >' is not.
    """
    s = strip_markup(par)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return True
    total = len(s.replace(" ", ""))
    good = sum(len(w) for w in _WORD_RE.findall(s) if len(w) >= 3)
    good += sum(len(n) for n in re.findall(r"\d+", s))
    if total < 80:                                   # v5.8: button debris 'r ^ Start Now L J'
        toks = s.split()
        junk = sum(1 for t in toks if (len(t) == 1 and t.isalpha() and t not in "aAI") or t in _JUNK_SYMBOLS)
        if len(toks) >= 3 and junk / len(toks) >= 0.4:
            return True
    return total > 0 and good / total < 0.6 and total < 80


def _norm_line(line: str) -> str:
    line = re.sub(r"^\s*#{1,6}\s*", "", line)          # '# **footer**' == 'footer'
    key = re.sub(r"\d+(?:\s+\d+)*", "#", strip_markup(line)).strip().lower()   # "2 6" == "26"
    return key.rstrip(" #") if len(key) > 3 else key      # 'guide 4' == 'guide'; bare numbers stay


def strip_running_lines(page_markdowns: list[str], min_share: float = 0.10, min_pages: int = 4) -> list[str]:
    """Drop lines that repeat across many pages (running headers/footers)."""
    seen: dict[str, set[int]] = {}
    verbatim_seen: dict[str, set[int]] = {}
    for i, md in enumerate(page_markdowns):
        non_empty = [ln.strip() for ln in md.splitlines() if ln.strip()]
        for line in md.splitlines():
            s = line.strip()
            if not s or s.startswith("|") or len(s) >= 120:
                continue
            verbatim_seen.setdefault(s.lower(), set()).add(i)
            # Only boundary lines (top/bottom) get normalized with digit wildcards
            is_b = (s in (non_empty[0], non_empty[1], non_empty[-2], non_empty[-1])) if len(non_empty) > 4 else (s in (non_empty[0], non_empty[-1])) if non_empty else False
            if is_b:
                seen.setdefault(_norm_line(line), set()).add(i)
    n = len(page_markdowns)
    threshold = min(min_pages, n) if n >= 2 else min_pages
    boiler = {k for k, v in seen.items() if k and len(v) >= max(threshold, math.ceil(min_share * n))}
    verbatim_boiler = {k for k, v in verbatim_seen.items() if k and len(v) >= max(threshold, math.ceil(min_share * n))}
    if not boiler and not verbatim_boiler:
        return page_markdowns
    out = []
    for md in page_markdowns:
        keep = []
        lines = md.splitlines()
        non_empty = [ln.strip() for ln in lines if ln.strip()]
        for ln in lines:
            s = ln.strip()
            if not s:
                keep.append(ln)
                continue
            if s.startswith("|"):
                keep.append(ln)
                continue
            # Verbatim repeated header/footer
            if s.lower() in verbatim_boiler:
                continue
            # Normalized numbered header/footer on margins
            is_boundary = (s in (non_empty[0], non_empty[1], non_empty[-2], non_empty[-1])) if len(non_empty) > 4 else (s in (non_empty[0], non_empty[-1])) if non_empty else False
            if is_boundary and _norm_line(ln) in boiler:
                continue
            keep.append(ln)
        out.append("\n".join(keep))
    return out


# ----------------------------------------------------------------------------
# Markdown tables
# ----------------------------------------------------------------------------

_SEP_ROW_RE = re.compile(r"^\|?(\s*:?-{2,}:?\s*\|)+\s*:?-*:?\s*$")
_FILLER = {"", ".", "..", "...", "---", "-", "--"}


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _fmt_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _norm_cell(c: str) -> str:
    return re.sub(r"[\s()]", "", c).lower()


def _emit(header: list[str], rows: list[list[str]]) -> str:
    lines = [_fmt_row(header), _fmt_row(["---"] * len(header))]
    lines += [_fmt_row(r + [""] * (len(header) - len(r))) for r in rows]
    return "\n".join(lines)


def _split_side_by_side(header: list[str], rows: list[list[str]]) -> list[tuple[list[str], list[list[str]]]] | None:
    """Detect [A|v|B|v|C|v] layouts (repeating value header) and split into groups."""
    n = len(header)
    nh = [_norm_cell(h) for h in header]
    for p in (2, 3):
        if n % p or n // p < 2:
            continue
        groups = n // p
        value_cols = range(1, p)
        if all(nh[k] and all(nh[k] == nh[k + g * p] for g in range(groups)) for k in value_cols) \
                and len({nh[g * p] for g in range(groups)}) == groups:
            out = []
            for g in range(groups):
                sub = [r[g * p:(g + 1) * p] for r in rows]
                sub = [r for r in sub if any(c.strip() for c in r)]
                out.append((header[g * p:(g + 1) * p], sub))
            return out
    return None


def _split_subheaders(header: list[str], rows: list[list[str]]) -> list[tuple[list[str], list[list[str]]]]:
    """A body row repeating the header's trailing cells starts a new sub-table."""
    tables, cur_h, cur = [], header, []
    ref = [_norm_cell(c) for c in header]
    for r in rows:
        nr = [_norm_cell(c) for c in r] + [""] * (len(ref) - len(r))
        same = [i for i in range(2, len(ref)) if ref[i] and nr[i] == ref[i]]
        if len(ref) >= 3 and len(same) >= max(1, len(ref) - 2) and nr[:2] != ref[:2]:
            tables.append((cur_h, cur))
            cur_h, cur = r, []
        else:
            cur.append(r)
    tables.append((cur_h, cur))
    # 'Round' | '2 (Static)' -> 'Round 2 (Static)' | 'Exercise' in every header
    fixed = []
    for h, rws in tables:
        if len(h) >= 3 and h[0] and h[0].isalpha() and re.match(r"^\d", h[1] or ""):
            h = [f"{h[0]} {h[1]}".strip(), "Exercise"] + h[2:]
        fixed.append((h, rws))
    return fixed


def _clean_cell(c: str, vocab: Counter | None) -> str:
    c = apply_known_fixes(fix_punct_spacing(collapse_letter_spacing(strip_markup(c), vocab))).strip()
    c = re.sub(r"\b([A-Z][a-z]{1,3})\.(?=[A-Z][a-z]|\d)", r"\1. ", c)      # 'Veg.Chopped', 'Exc.1'
    c = re.sub(r"(?<=[a-z])(?=[A-Z]-[a-z])", " ", c)                          # 'HangingL-sit' -> 'Hanging L-sit'
    c = re.sub(r"(?<=[a-z])\((?=[A-Z])", " (", c)                             # 'Nuts(Avg.)'
    c = re.sub(r"(?<=[A-Za-z])\((?=per\b)", " (", c)                          # 'Protein(per 100g)'
    c = re.sub(r"(\d) ?\( ?", r"\1 (", c) if False else c
    if c in _FILLER:
        return ""                                    # '...' placeholder cells carry no data
    return fix_lost_spaces(c, vocab) if vocab else c


_ROMAN_FIRST_COL_RE = re.compile(r"^(I{1,3}|l{1,3})\.?$")


def _fix_toc_rows(rows: list[list[str]]) -> list[list[str]]:
    """'I.'->'1.', 'II'->'11', and '10' + '. Workout Programs' -> '10.' + 'Workout Programs'."""
    out = []
    for r in rows:
        r = list(r)
        if len(r) >= 2:
            first = r[0].strip()
            if _ROMAN_FIRST_COL_RE.match(first):
                r[0] = "1" * len(first.rstrip(".")) + "."
            elif r[1].startswith(". ") and first.isdigit():
                r[0] = first + "."
            if r[1].startswith(". "):
                r[1] = r[1][2:]
        out.append(r)
    return out


def clean_markdown_tables(md: str, vocab: Counter | None = None) -> str:
    """Normalise every pipe table: cell cleanup, side-by-side split, ToC detection."""
    lines = md.split("\n")
    out: list[str] = []
    i = 0
    last_heading = ""
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("#"):
            last_heading = line.strip()
        if not line.lstrip().startswith("|"):
            out.append(line)
            i += 1
            continue
        j = i
        while j < len(lines) and lines[j].lstrip().startswith("|"):
            j += 1
        block = [ln for ln in lines[i:j]]
        i = j
        for sub_no, sub in enumerate(_split_adjacent_tables(block)):
            if sub_no:
                out.append("")
            _emit_clean_table(sub, out, vocab, prev_heading=last_heading)
    return "\n".join(out)


def _split_adjacent_tables(block: list[str]) -> list[list[str]]:
    """Two markdown tables written back to back would be parsed as ONE table (the second
    header becoming a data row).  Cut before every header row that precedes a 2nd+ separator."""
    seps = [k for k, ln in enumerate(block) if _SEP_ROW_RE.match(ln.strip())]
    cuts = [k - 1 for k in seps[1:] if k - 1 > 0]
    if not cuts:
        return [block]
    edges = [0, *cuts, len(block)]
    return [block[a:b] for a, b in zip(edges, edges[1:]) if b > a]


_TOC_FIRST_RE = re.compile(r"^(?P<n>\d{1,2}|(?:[Il1]\s?){1,3})\s*\.?\s+(?P<t>\S.*)$")


def _try_toc(rows: list[list[str]]) -> list[list[str]] | None:
    """'I. Introduction | 4', 'I I. Equipment | 34' ... -> [['1.', 'Introduction', '4'], ...] or None."""
    if len(rows) < 4 or any(len(r) != 2 or not r[1].strip().isdigit() for r in rows):
        return None
    parsed = []
    for r in rows:
        m = _TOC_FIRST_RE.match(r[0].strip())
        if not m:
            return None
        n = m["n"]
        parsed.append((int(n) if n.isdigit() else int("1" * len(re.findall(r"[Il1]", n))), m["t"].strip(), r[1].strip()))
    pages = [int(p[2]) for p in parsed]
    if pages != sorted(pages):
        return None
    sequential = sum(p[0] == i + 1 for i, p in enumerate(parsed)) >= 0.6 * len(parsed)
    return [[f"{(i + 1) if sequential else p[0]}.", p[1], p[2]] for i, p in enumerate(parsed)]


_TOC_HEADING_RE = re.compile(
    r"\b(?:content|contents|table\s+of\s+contents|inhalt)\b", re.I
)
_DOT_LEADER_ROW_RE = re.compile(r"\.{4,}\s*\d+")


def _is_toc_table(header: list[str], rows: list[list[str]], prev_heading: str) -> bool:
    """v5.9 WP2: True when the preceding heading or row content signals a ToC table."""
    if prev_heading and _TOC_HEADING_RE.search(prev_heading):
        return True
    if not rows:
        return False
    dot_rows = sum(
        1 for r in rows
        if any(_DOT_LEADER_ROW_RE.search(c) for c in r)
    )
    return dot_rows / len(rows) >= 0.5


def _compact_toc_chunk(header: list[str], rows: list[list[str]]) -> str:
    """v5.9 WP2: Emit a compact [TOC] block with dot leaders stripped."""
    import re as _re
    _DOTS = _re.compile(r"\.{3,}")
    lines = ["[TOC]"]
    for row in rows:
        clean = [_DOTS.sub("", c).strip() for c in row]
        clean = [c for c in clean if c]
        if clean:
            lines.append("  " + " | ".join(clean))
    return "\n".join(lines)


def _emit_clean_table(block: list[str], out: list[str], vocab: Counter | None, prev_heading: str = "") -> None:
    """Clean one pipe table (``block``) and append its markdown lines to ``out``."""
    if True:
        raw = [_split_row(ln) for ln in block if not _SEP_ROW_RE.match(ln.strip())]
        raw = [[_clean_cell(c, vocab) for c in r] for r in raw]
        raw = [r for r in raw if any(c not in _FILLER for c in r)]
        if not raw:
            return
        width = max(len(r) for r in raw)
        raw = [r + [""] * (width - len(r)) for r in raw]
        header, rows = raw[0], raw[1:]
        toc = _try_toc(raw)
        if toc is not None:                           # v5.8: two-column contents table
            header, rows = ["No.", "Section", "Page"], toc
        elif getattr(settings, "pdf_v59_toc", True) and _is_toc_table(
            header, rows,
            prev_heading=prev_heading or getattr(_emit_clean_table, "_last_heading", ""),
        ):
            # v5.9 WP2: dotted-leader ToC detected -- emit compact toc block
            out.append(_compact_toc_chunk(header, rows))
            return
        elif width >= 3 and re.match(r"^(\d+|I+|l+)\.?$", header[0]) and header[0]:
            # contents table: no real header row -> treat every row as data
            rows = _fix_toc_rows([header] + rows)
            header = ["No.", "Section", "Page"][:width] + [""] * max(0, width - 3)
        groups = _split_side_by_side(header, rows)
        if groups is None:
            groups = _split_subheaders(header, rows)
        for k, (h, r) in enumerate(groups):
            if k:
                out.append("")
            out.append(_emit(h, r))


_PICTURE_TEXT_RE = re.compile(r"<!-- Start of picture text -->(.*?)<!-- End of picture text -->", re.S)


def clean_page_markdown(md: str, vocab: Counter | None = None) -> str:
    """Per-page markdown clean-up run before Docling's markdown backend sees it."""
    if not md:
        return md
    # photo text: keep only when it reads like words (logo text survives, debris goes)
    def _pic(m: re.Match) -> str:
        inner = re.sub(r"<br\s*/?>", " ", m.group(1)).strip()
        # v5.9 WP4: keep instruction-like captions (numbered, imperative, >6 words)
        is_instruction = bool(re.match(
            r"^\d+[.)\s]|^[A-Z][a-z]+ (?:the |a |an )|^Press\b|^Turn\b|^Insert\b|^Remove\b",
            inner,
        )) or len(inner.split()) > 6
        keep = inner and (not is_noise_paragraph(inner) or is_instruction)
        return "\n\n" + inner + "\n\n" if keep else "\n\n"
    md = _PICTURE_TEXT_RE.sub(_pic, md)
    md = _BOLD_HYPHEN_RE.sub("-", md)
    md = _SUP_TAG_RE.sub("", md)
    md = clean_markdown_tables(md, vocab)
    paras = re.split(r"\n{2,}", md)
    kept = []
    for p in paras:
        s = p.strip()
        if not s:
            continue
        first = s.lstrip()
        if first.startswith(("|", "#", "[TOC]")) or first.startswith(("- ", "* ", "> ")) or len(s) >= 80:
            kept.append(p)
        elif not is_noise_paragraph(s):
            kept.append(p)
    kept = [k if (k.lstrip().startswith("|") or k.lstrip().startswith("[TOC]")) else _clean_paragraph(k, vocab) for k in kept]
    return "\n\n".join(kept)


def _clean_paragraph(par: str, vocab: Counter | None) -> str:
    """Markdown-safe fixes for one non-table paragraph (keeps '#', '**' and list markers)."""
    par = rejoin_urls(par)
    par = apply_known_fixes(par)
    par = re.sub(r"(?<=\S)[ \t]+###\s*\*{0,2}[^\n*]+\*{0,2}\s*$", "", par)   # glued duplicate heading
    return fix_lost_spaces(par, vocab) if vocab else par


# ----------------------------------------------------------------------------
# v5.8: heading numbers and sequence labels (pure string functions)
# ----------------------------------------------------------------------------
_BROKEN_NUM_RE = re.compile(r"^(?P<a>\d+(?:\.\d+)+)\.\s*(?P<b>\d+)\s*(?=[A-Za-z])")
_NUM_HEAD_RE = re.compile(r"^(\d+(?:\.\d+)+)(\s+\S.*)$")
_SEQ_LABEL_RE = re.compile(r"^(Day|Week|Round|Step)\s+(\d+)$")


def fix_heading_number(text: str) -> str:
    """'6.5. 1Chest Circuit' -> '6.5.1 Chest Circuit'."""
    t = text.strip()
    m = _BROKEN_NUM_RE.match(t)
    return f"{m['a']}.{m['b']} {t[m.end():]}" if m else text


def repair_heading_sequence(texts: list[str]) -> list[str]:
    """Fix 3-level heading number typos where sub-number is lower than parent."""
    out: list[str] = []
    last2: list[str] | None = None
    for t in texts:
        m = _NUM_HEAD_RE.match(t.strip())
        if not m:
            out.append(t)
            continue
        parts = m.group(1).split(".")
        if len(parts) == 2:
            last2 = parts
        elif len(parts) >= 3:
            if last2 is None:
                last2 = parts[:2]
            elif parts[0] == last2[0] and parts[1] != last2[1] and int(parts[1]) < int(last2[1]):
                t = ".".join([*last2, *parts[2:]]) + m.group(2)
            else:
                last2 = parts[:2]
        out.append(t)
    return out


def renumber_sequence(labels: list[str]) -> list[str]:
    """['Day 7', 'Day 2'] -> ['Day 1', 'Day 2'] when at most one third of the numbers are wrong."""
    ms = [_SEQ_LABEL_RE.match(x.strip()) for x in labels]
    if len(labels) < 2 or not all(ms) or len({m[1] for m in ms}) != 1:
        return list(labels)
    nums = [int(m[2]) for m in ms]
    expected = list(range(1, len(nums) + 1))
    bad = sum(a != b for a, b in zip(nums, expected))
    if 0 < bad <= max(1, len(nums) // 3):
        return [f"{ms[0][1]} {e}" for e in expected]
    return list(labels)

# ----------------------------------------------------------------------------
# VLM Token Scrubbing & Compatibility Aliases
# ----------------------------------------------------------------------------

_VLM_TOKEN_RE = re.compile(r"<[a-z_0-9]{1,40}>|<[a-z_0-9]{0,40}\s*$")


def strip_vlm_tokens(text: str) -> str:
    """Scrub raw completion tokens (e.g. <end_of_utteranc>, <unused0>) from text."""
    if not text:
        return text
    cleaned = _VLM_TOKEN_RE.sub("", text)
    return cleaned.strip()


def clean_markdown_page(md: str, vocab: Counter | None = None) -> str:
    """
    Apply markdown text sanitization:
    - Strips leaked VLM tokens.
    - Runs full clean_page_markdown pipeline.
    """
    if not md:
        return md
    md = strip_vlm_tokens(md)
    return clean_page_markdown(md, vocab=vocab)


_ITALIC_RE = re.compile(r"(?<![*\w])\*(?![\s*])([^*\n]+?)(?<![\s*])\*(?![*\w])")


def strip_inline_emphasis(md: str) -> str:
    """v5.9.1: remove **bold** / *italic* markers before the markdown -> DoclingDocument round trip.

    Docling's markdown backend splits or drops inline strong runs (lost: 'No' in '- No presence 2',
    'SF12', 'be set.'; fragmented: 'without presence 2' / ', for' / '1 bed' on separate lines).
    Emphasis carries no retrieval value, so it is removed up front. Headings (#) are untouched.
    """
    if not md:
        return md
    md = md.replace("**", "")
    return _ITALIC_RE.sub(r"\1", md)


_ITALIC_RE = re.compile(r"(?<![*\w])\*(?![\s*])([^*\n]+?)(?<![\s*])\*(?![*\w])")


def strip_inline_emphasis(md: str) -> str:
    """v5.9.1: remove **bold** / *italic* markers before the markdown -> DoclingDocument round trip.

    Docling's markdown backend splits or drops inline strong runs (lost: 'No' in '- No presence 2',
    'SF12', 'be set.'; fragmented: 'without presence 2' / ', for' / '1 bed' on separate lines).
    Emphasis carries no retrieval value, so it is removed up front. Headings (#) are untouched.
    """
    if not md:
        return md
    md = md.replace("**", "")
    return _ITALIC_RE.sub(r"\1", md)

