from __future__ import annotations

import hashlib
import logging
import re
from typing import TYPE_CHECKING, Any

import fitz  # PyMuPDF

if TYPE_CHECKING:
    from docling_core.types.doc import DoclingDocument, TableItem

logger = logging.getLogger(__name__)

_MAX_MARK_AREA_PT2 = 400.0
_ASPECT_MIN = 0.70
_ASPECT_MAX = 1.40
_LEGEND_RE = re.compile(r"=\s*(available|unavailable)", re.I)


def scan_legend(page_texts: list[str]) -> dict[str, str] | None:
    """Scan all page text strings for a tick/dot availability legend."""
    
    combined = " ".join(page_texts)
    if _LEGEND_RE.search(combined):
        return {"tick": "Yes", "dots": "No"}
    return None


def _bbox_to_tuple(bbox: Any) -> tuple[float, float, float, float]:
    return float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b)


def _inside(ix0: float, iy0: float, ix1: float, iy1: float, ox0: float, oy0: float, ox1: float, oy1: float, tol: float = 2.0) -> bool:
    """Return True if inner box is inside or substantially overlaps the outer box."""
    
    cx = (ix0 + ix1) / 2.0
    cy = (iy0 + iy1) / 2.0
    return (ox0 - tol <= cx <= ox1 + tol) and (oy0 - tol <= cy <= oy1 + tol)


def inject_marks(
    doc: DoclingDocument,
    page_fitz: fitz.Page,
    page_no: int,
    legend: dict[str, str] | None = None,
) -> None:
    """
    Detect inline raster checkmark and crossmark images inside table cells and convert them
    to readable 'Yes' and 'No' text values in the Docling table structure.
    """
    
    try:
        image_infos = page_fitz.get_image_info(xrefs=True)
    except Exception:
        return

    if not image_infos:
        return

    candidate_images: list[tuple[float, float, float, float]] = []
    for info in image_infos:
        bbox = info.get("bbox")
        if not bbox:
            continue
        x0, y0, x1, y1 = bbox
        w = x1 - x0
        h = y1 - y0
        area = w * h
        if 0 < area <= _MAX_MARK_AREA_PT2 and h > 0 and _ASPECT_MIN <= (w / h) <= _ASPECT_MAX:
            candidate_images.append((x0, y0, x1, y1))

    if not candidate_images:
        return

    for table in doc.tables:
        t_data = getattr(table, "data", None)
        if not t_data or not getattr(t_data, "grid", None):
            continue

        for row in t_data.grid:
            for cell in row:
                if not getattr(cell, "bbox", None):
                    continue
                cl, ct, cr, cb = _bbox_to_tuple(cell.bbox)

                for img_box in candidate_images:
                    if _inside(img_box[0], img_box[1], img_box[2], img_box[3], cl, ct, cr, cb):
                        current_text = getattr(cell, "text", "").strip()
                        if not current_text or current_text == "...":
                            cell.text = "Yes"

