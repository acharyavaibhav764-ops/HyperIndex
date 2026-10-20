"""Which pictures are not worth a card.  The classifier is a router, not an oracle: classes below
the confidence floor are ignored and anything unlisted is READ, never dropped."""
from __future__ import annotations

# Safe to drop when the picture carries no technical text.
SKIP_CLASSES = frozenset({
    "logo", "icon", "photograph", "signature", "stamp",
    "qr_code", "bar_code", "music", "calendar", "page_thumbnail",
})
# Worth a VLM look for connections (used from phase 4).
DIAGRAM_CLASSES = frozenset({"engineering_drawing", "flow_chart", "other", "screenshot_from_manual", ""})
# Never a single wiring diagram or a procedure panel.
CHART_CLASSES = frozenset({
    "line_chart", "bar_chart", "pie_chart", "scatter_plot", "table",
    "geographical_map", "topographical_map", "chemistry_structure",
})

CLASS_CONF_MIN = 0.60
MIN_AREA_PT2 = 2500.0       # ~50x50 pt
MIN_SIDE_PT = 24.0
MAX_ASPECT = 8.0            # divider bars / rules
PHOTO_KEEP_LABELS = 4       # an annotated photo with this many live labels is kept


def geometry_skip(bbox) -> str:
    """'skip_tiny' / 'skip_sliver' / '' for a (x0, y0, x1, y1) box in points."""
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if w * h < MIN_AREA_PT2 or min(w, h) < MIN_SIDE_PT:
        return "skip_tiny"
    if max(w / max(h, 1.0), h / max(w, 1.0)) > MAX_ASPECT:
        return "skip_sliver"
    return ""


def effective_class(cls: str, conf: float) -> str:
    """Ignore a class the classifier is not sure about."""
    return cls if conf >= CLASS_CONF_MIN else ""


def class_skip(cls: str, technical: bool, n_labels: int) -> str:
    """'skip_class_<name>' for a decorative class with no technical text and few live labels."""
    if cls in SKIP_CLASSES and not technical and n_labels < PHOTO_KEEP_LABELS:
        return f"skip_class_{cls}"
    return ""
