"""Exact labels from the PDF's own text layer (no OCR, no model)."""
from __future__ import annotations

import re

from .text import dedup

MAX_LABEL_LINES = 80
MIN_LABELS_FOR_CARD = 3     # text-layer labels needed to call a figure "readable"

# Technical tokens (Honeywell nurse-call) that rescue a diagram the classifier called a photo.
DEFAULT_TECH_REGEX = (
    r"\b(?:D-?BUS|R-?ABUS|SEM(?:-IP)?\+?|STIP|SCIP\+?|SMCC|SRT|SCB-R[MU]|SBU|SCU|PU|"
    r"24\s?V\s?DC|GND|PoE|ID\d+)\b|\[\d+\]"
)

_ID_LINE_RE = re.compile(r"^ID\s?\d+$", re.I)
_HAS_ID_RE = re.compile(r"\bID\s?\d+\b", re.I)


def is_technical(labels: list[str], regex: str | None = None) -> bool:
    pat = re.compile(regex or DEFAULT_TECH_REGEX, re.I)
    return any(pat.search(label) for label in labels)


def _id_composites(items: list, max_gap: float = 25.0) -> list[str]:
    """Pair a bare 'ID1' text with the nearest label so 'SBU' + 'ID1' also exists as 'SBU ID1'.

    Wiring drawings often draw the device name and its bus address as two separate text objects.
    Pairing is purely geometric (nearest non-ID line within ``max_gap`` points).
    """
    out: list[str] = []
    for i, (text, r) in enumerate(items):
        if not _ID_LINE_RE.match(text.strip()):
            continue
        best = None
        for j, (t2, r2) in enumerate(items):
            if i == j or _HAS_ID_RE.search(t2):
                continue
            dx = max(0.0, r[0] - r2[2], r2[0] - r[2])
            dy = max(0.0, r[1] - r2[3], r2[1] - r[3])
            d = (dx * dx + dy * dy) ** 0.5
            if d <= max_gap and (best is None or d < best[0]):
                best = (d, t2)
        if best:
            out.append(f"{best[1].strip()} {text.strip()}")
    return out


def _label_lines(page, bbox) -> list[tuple]:
    """[(line_text, (x0, y0, x1, y1))] for text lines whose centre lies inside ``bbox``."""
    try:
        words = page.get_text("words")
    except Exception:
        return []
    pad = 1.5
    lines: dict[tuple, list] = {}
    for w in words:
        x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], str(w[4])
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if not (bbox[0] - pad <= cx <= bbox[2] + pad and bbox[1] - pad <= cy <= bbox[3] + pad):
            continue
        if not text.strip():
            continue
        lines.setdefault((w[5], w[6]), []).append(w)
    ordered = sorted(lines.values(), key=lambda ws: (round(min(w[1] for w in ws)), min(w[0] for w in ws)))
    items = []
    for ws in ordered:
        ws = sorted(ws, key=lambda w: w[7])
        line = " ".join(str(w[4]).strip() for w in ws).strip()
        if line and re.search(r"\w", line):
            rect = (min(w[0] for w in ws), min(w[1] for w in ws), max(w[2] for w in ws), max(w[3] for w in ws))
            items.append((line, rect))
    return items


def extract_labels(page, bbox, limit: int = MAX_LABEL_LINES) -> list[str]:
    """Live-text labels inside ``bbox``, one entry per text line (keeps 'SEM-IP ID1' whole),
    plus geometric 'NAME ID<n>' composites.  Order: reading order, composites last."""
    items = _label_lines(page, bbox)
    return dedup([t for t, _ in items] + _id_composites(items))[:limit]
