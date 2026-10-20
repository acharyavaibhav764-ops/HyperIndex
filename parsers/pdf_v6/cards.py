"""Per-page orchestration: the pictures Docling found on one page -> Figure / Procedure cards.

Per picture:  geometry -> skip gate -> exact labels (PDF text layer) -> caption -> card.
Nothing here asks a model to write prose for the index.  A picture with no text layer and no
caption produces no card: nothing deterministic to say beats a hallucinated caption.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import gate, geometry
from . import labels as lbl
from . import text as txt

if TYPE_CHECKING:  # pragma: no cover
    from docling_core.types.doc import DoclingDocument

logger = logging.getLogger(__name__)


def _settings():
    from config import settings
    return settings


@dataclass
class FigureRun:
    """Per-document state shared across pages."""
    repeated: set = field(default_factory=set)
    stats: dict = field(default_factory=dict)

    def note(self, key: str) -> None:
        self.stats[key] = self.stats.get(key, 0) + 1

    @classmethod
    def from_pdf(cls, pdf, min_pages: int = 3) -> "FigureRun":
        """Digests of images that appear on ``min_pages``+ pages (logos, headers, watermarks)."""
        pages_by_digest: dict[str, set] = {}
        try:
            for pno, page in enumerate(pdf):
                try:
                    infos = page.get_image_info(hashes=True)
                except Exception:
                    continue
                for info in infos:
                    d = info.get("digest")
                    if d:
                        key = d.hex() if isinstance(d, (bytes, bytearray)) else str(d)
                        pages_by_digest.setdefault(key, set()).add(pno)
        except Exception:
            pass
        return cls(repeated={d for d, ps in pages_by_digest.items() if len(ps) >= min_pages})


def _picture_digest(page, bbox) -> str:
    try:
        for info in page.get_image_info(hashes=True):
            if geometry.iou(tuple(info["bbox"]), bbox) > 0.5:
                d = info.get("digest")
                return d.hex() if isinstance(d, (bytes, bytearray)) else str(d or "")
    except Exception:
        pass
    return ""


def format_card(caption: str, kind: str, section: str, labels: list[str],
                connections: list[dict] | None = None) -> str:
    parts = [f"Figure: {caption}" if caption else "Figure: (untitled)"]
    if kind:
        parts.append(f"Type: {kind.replace('_', ' ')}")
    if section:
        parts.append(f"Section: {section}")
    if labels:
        parts.append("Labels: " + ", ".join(labels))
        nums = txt.extract_numbers(labels)[:30]
        if nums:
            parts.append("Numbers: " + ", ".join(nums))
    if connections:
        body = "; ".join(
            f"{c['from']} -{'[' + c['via'] + ']-' if c['via'] else ''}> {c['to']}" for c in connections
        )
        parts.append("Connections (machine-read, verify against the figure): " + body)
    return " | ".join(parts)


def process_pictures(
    doc: "DoclingDocument",
    page,
    heading_path,
    page_no: int,
    run: FigureRun | None = None,
) -> list[dict]:
    """Build Figure / Procedure cards for the pictures Docling found on one page.

    ``page`` is a single-page ``pymupdf.Page`` (live text for labels, pixels for crops).
    """
    if not getattr(doc, "pictures", None):
        return []
    st = _settings()
    run = run or FigureRun()
    section = " > ".join(heading_path) if isinstance(heading_path, (list, tuple)) else str(heading_path or "")
    tech_re = getattr(st, "pdf_figure_tech_regex", "") or None

    table_boxes = []
    for tbl in getattr(doc, "tables", []) or []:
        tb = geometry.item_bbox(tbl, doc, page)
        if tb:
            table_boxes.append(tb)

    cands: list[dict] = []
    for idx, pic in enumerate(doc.pictures):
        c = {"idx": idx, "pic": pic, "figure_id": f"fig_p{page_no}_{idx}"}
        bbox = geometry.item_bbox(pic, doc, page)
        if bbox is None:
            run.note("skip_no_bbox")
            continue
        reason = gate.geometry_skip(bbox)
        if reason:
            run.note(reason)
            continue
        if any(geometry.inside(bbox, tb) for tb in table_boxes):
            run.note("skip_in_table")
            continue
        dig = _picture_digest(page, bbox)
        if dig and dig in run.repeated:
            run.note("skip_repeated")
            continue
        cls = gate.effective_class(*geometry.class_info(pic))
        labels = lbl.extract_labels(page, bbox)
        tech = lbl.is_technical(labels, tech_re)
        reason = gate.class_skip(cls, tech, len(labels))
        if reason:
            run.note(reason)
            continue
        c.update(bbox=bbox, cls=cls, labels=labels, tech=tech)
        cands.append(c)

    cards: list[dict] = []
    consumed: set[int] = set()


    # ---- figure cards
    for c in cands:
        if c["idx"] in consumed:
            continue
        pic, bbox, cls, labels = c["pic"], c["bbox"], c["cls"], list(c["labels"])
        source = "text_layer" if labels else "none"

        caption = ""
        try:
            caption = txt.clean_caption(pic.caption_text(doc) or "")
        except Exception:
            pass
        if len(labels) < lbl.MIN_LABELS_FOR_CARD and not caption:
            run.note("skip_no_text")
            continue

        connections: list[dict] = []

        conf = "high" if source == "text_layer" and len(labels) >= lbl.MIN_LABELS_FOR_CARD else (
            "medium" if source == "ocr" else "low")
        cards.append({
            "figure_id": c["figure_id"],
            "text": format_card(caption, cls, section, labels, connections),
            "content_type": "figure", "class_hint": cls, "confidence": conf,
            "source": source, "edges": len(connections), "page": page_no,
        })
        run.note("card")

    if run.stats:
        logger.info("pdf_v6: page %s stats=%s", page_no, run.stats)
    return cards
