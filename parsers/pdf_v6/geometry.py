"""Picture geometry and classifier read-out.

Docling keeps a picture's box in ``item.prov[0].bbox`` with a BOTTOM-LEFT origin; PyMuPDF
works top-left.  v5.9 read a non-existent ``item.bbox`` and so never saw a box at all.
"""
from __future__ import annotations


def _bbox_topleft(prov_bbox, page_height: float):
    """Docling bbox -> (x0, y0, x1, y1) in top-left origin points, or None."""
    try:
        bb = prov_bbox
        if getattr(getattr(bb, "coord_origin", None), "name", "") == "BOTTOMLEFT":
            bb = bb.to_top_left_origin(page_height=page_height)
        x0, x1 = sorted((float(bb.l), float(bb.r)))
        y0, y1 = sorted((float(bb.t), float(bb.b)))
        return (x0, y0, x1, y1)
    except Exception:
        return None


def item_bbox(item, doc, page):
    """Box of a PictureItem/TableItem in PyMuPDF space (``page`` is a pymupdf.Page)."""
    prov = getattr(item, "prov", None)
    if not prov:
        return None
    p = prov[0]
    page_h = None
    try:
        page_h = doc.pages[p.page_no].size.height
    except Exception:
        pass
    if not page_h:
        try:
            page_h = float(page.rect.height)
        except Exception:
            return None
    return _bbox_topleft(p.bbox, float(page_h))


def iou(a, b) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def inside(bbox, outer, tol: float = 2.0) -> bool:
    return (bbox[0] >= outer[0] - tol and bbox[1] >= outer[1] - tol
            and bbox[2] <= outer[2] + tol and bbox[3] <= outer[3] + tol)


def class_info(pic) -> tuple[str, float]:
    """(class_name, confidence) from Docling's picture classifier; ('', 0.0) if absent."""
    try:
        meta = getattr(pic, "meta", None)
        preds = getattr(getattr(meta, "classification", None), "predictions", None)
        if preds:
            best = max(preds, key=lambda p: float(getattr(p, "confidence", 0) or 0))
            return str(best.class_name).strip().lower(), float(best.confidence or 0)
    except Exception:
        pass
    try:  # older Docling: annotations -> PictureClassificationData
        for ann in getattr(pic, "annotations", None) or []:
            pcs = getattr(ann, "predicted_classes", None)
            if pcs:
                best = max(pcs, key=lambda p: float(getattr(p, "confidence", 0) or 0))
                return str(best.class_name).strip().lower(), float(best.confidence or 0)
    except Exception:
        pass
    return "", 0.0
