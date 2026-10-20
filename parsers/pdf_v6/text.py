"""String helpers shared by the figure pipeline (pure functions, no PDF or Docling imports)."""
from __future__ import annotations

import re
import zlib

_GENERIC_RE = re.compile(r"^In this (image|picture|diagram|figure)\b", re.I)
_ZLIB_RATIO_MIN = 0.35
_NGRAM_REPEATS = 3
_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2212"), "-")

# DocumentFigureClassifier labels, as the human-readable lines Docling prints into markdown.
# "other" is deliberately absent: a bare "Other" line can be real text.
_CLASSIFIER_LABELS = frozenset(
    c.replace("_", " ") for c in (
        "logo", "photograph", "icon", "engineering_drawing", "line_chart", "bar_chart",
        "table", "flow_chart", "screenshot_from_computer", "signature", "screenshot_from_manual",
        "geographical_map", "pie_chart", "page_thumbnail", "stamp", "music", "calendar", "qr_code",
        "bar_code", "full_page_image", "scatter_plot", "chemistry_structure", "topographical_map",
        "crossword_puzzle", "box_plot",
    )
)


def _zlib_ratio(text: str) -> float:
    raw = text.encode("utf-8")
    return len(zlib.compress(raw)) / len(raw) if raw else 1.0


def has_repeated_ngram(text: str, n: int = 4) -> bool:
    words = text.split()
    if len(words) < n:
        return False
    grams: dict[tuple, int] = {}
    for i in range(len(words) - n + 1):
        g = tuple(words[i:i + n])
        grams[g] = grams.get(g, 0) + 1
    return any(c >= _NGRAM_REPEATS for c in grams.values())


def generic_caption(text: str) -> bool:
    return bool(_GENERIC_RE.match(text.strip())) and len(text.split()) < 12


def clean_caption(text: str) -> str:
    """Drop captions that look machine-generated or degenerate ('' = unusable)."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text or generic_caption(text) or has_repeated_ngram(text):
        return ""
    if len(text) > 40 and _zlib_ratio(text) < _ZLIB_RATIO_MIN:
        return ""
    return text


def norm(s: str) -> str:
    s = (s or "").translate(_DASHES).casefold()
    return re.sub(r"\s+", " ", s).strip(" .,:;")


def tokens(s: str) -> list[str]:
    out = []
    for t in re.split(r"[\s,;]+", norm(s)):
        t = t.strip("().,;:")
        if t:
            out.append(t)
    return out


def dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for it in items:
        k = norm(it)
        if k and k not in seen:
            seen.add(k)
            out.append(re.sub(r"\s+", " ", it).strip())
    return out


def extract_numbers(labels: list[str]) -> list[str]:
    nums: list[str] = []
    for label in labels:
        nums.extend(re.findall(r"\b\d+(?:\.\d+)?\b", label))
    return list(dict.fromkeys(nums))


def last_heading(md: str) -> str:
    """Last markdown heading in ``md`` (empty string when there is none or ``md`` is not text)."""
    found = ""
    if not isinstance(md, str):
        return found
    for line in md.splitlines():
        m = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if m:
            found = m.group(1).strip()
    return found


def strip_classifier_labels(md: str) -> str:
    """Remove stand-alone lines that are just a figure-classifier label ("Screenshot from manual").

    Fallback for a Docling whose markdown export cannot suppress them.
    """
    out = [ln for ln in (md or "").split("\n") if ln.strip().casefold() not in _CLASSIFIER_LABELS]
    return "\n".join(out)
