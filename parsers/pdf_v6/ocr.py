"""Optional OCR labels for diagrams that have no text layer (RapidOCR, imported lazily).

Used only when PDF_FIGURE_OCR=true or the VLM is enabled.  OCR output is shaped like the PDF
text layer so the same exact-match validation applies:
  * a bare 'ID1' is paired with the nearest device label (OCR detects 'SEM-IP' and 'ID1' apart),
  * compact 'DBUS2' also gets its spaced form 'DBUS 2' (OCR drops spaces between letters/digits).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from .labels import MAX_LABEL_LINES, _id_composites
from .text import dedup

logger = logging.getLogger(__name__)

MAX_SIDE_PX = 1600
MIN_DPI = 96
OCR_MIN_SCORE = 0.5
ID_GAP_PT = 25.0

_OCR_ENGINE: Any = None
_OCR_FAILED = False
_COMPACT_RE = re.compile(r"^([A-Za-z]{3,}(?:-[A-Za-z]+)?)(\d+)$")


def effective_dpi(bbox, dpi: int = 200, max_side_px: int = MAX_SIDE_PX) -> int:
    """Render DPI actually used for ``bbox``: capped so the long side stays <= ``max_side_px``."""
    w = max(bbox[2] - bbox[0], 1.0)
    h = max(bbox[3] - bbox[1], 1.0)
    return max(MIN_DPI, min(int(dpi), int(max_side_px * 72 / max(w, h))))


def render_crop(page, bbox, dpi: int = 200, max_side_px: int = MAX_SIDE_PX) -> bytes:
    """PNG of ``bbox`` rendered from the page itself (vector diagrams included)."""
    import pymupdf
    pix = page.get_pixmap(clip=pymupdf.Rect(*bbox), dpi=effective_dpi(bbox, dpi, max_side_px))
    return pix.tobytes("png")


def spaced_variants(lines: list[str]) -> list[str]:
    """'DBUS2' -> 'DBUS 2' (letters then digits).  'ID1' is left alone: it is already an address."""
    out = []
    for line in lines:
        m = _COMPACT_RE.match(line.strip())
        if m and not re.fullmatch(r"ID\d+", line.strip(), re.I):
            out.append(f"{m.group(1)} {m.group(2)}")
    return out


def _items(res) -> list[tuple]:
    """[(text, (x0, y0, x1, y1))] from either RapidOCR return shape."""
    items = []
    if hasattr(res, "txts"):                       # rapidocr >= 2
        boxes = list(getattr(res, "boxes", None) if getattr(res, "boxes", None) is not None else [])
        scores = list(getattr(res, "scores", None) if getattr(res, "scores", None) is not None else [])
        for i, t in enumerate(res.txts or []):
            if i < len(scores) and float(scores[i]) < OCR_MIN_SCORE:
                continue
            items.append((str(t), _rect(boxes[i]) if i < len(boxes) else None))
        return items
    result = res[0] if isinstance(res, tuple) else res        # rapidocr_onnxruntime
    for r in result or []:
        if len(r) >= 3 and float(r[2]) < OCR_MIN_SCORE:
            continue
        items.append((str(r[1]), _rect(r[0])))
    return items


def _rect(box):
    try:
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        return (min(xs), min(ys), max(xs), max(ys))
    except Exception:
        return None


def ocr_labels(png: bytes, px_per_pt: float = 1.0) -> list[str]:
    """OCR text lines of a rendered crop, shaped like the PDF text layer ([] if RapidOCR is missing)."""
    global _OCR_ENGINE, _OCR_FAILED
    if _OCR_FAILED:
        return []
    try:
        if _OCR_ENGINE is None:
            try:
                from rapidocr_onnxruntime import RapidOCR  # type: ignore
            except ImportError:
                from rapidocr import RapidOCR  # type: ignore
            _OCR_ENGINE = RapidOCR()
        items = [(t, r) for t, r in _items(_OCR_ENGINE(png)) if t.strip()]
        items.sort(key=lambda it: ((it[1][1] // 12) if it[1] else 0, it[1][0] if it[1] else 0))
        texts = [t for t, _ in items]
        placed = [(t, r) for t, r in items if r]
        composites = _id_composites(placed, max_gap=ID_GAP_PT * max(px_per_pt, 0.1))
        return dedup(texts + spaced_variants(texts) + composites)[:MAX_LABEL_LINES]
    except Exception as exc:  # pragma: no cover - depends on the optional package
        _OCR_FAILED = True
        logger.warning("pdf_v6: OCR unavailable (%s); text-layer labels only", exc)
        return []
