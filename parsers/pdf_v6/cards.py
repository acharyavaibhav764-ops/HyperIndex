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
from . import procedure
from . import ocr, vlm

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
    vlm_calls: int = 0

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


def format_procedure(steps: list[str], section: str) -> str:
    parts = [f"Procedure ({len(steps)} illustrated steps)"]
    if section:
        parts.append(f"Section: {section}")
    parts.extend(f"Step {i}: {s}" for i, s in enumerate(steps, 1))
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

    # ---- procedure: 3+ similar, label-poor, non-technical panels with captions beneath
    if getattr(st, "pdf_figure_procedures", True):
        panels = [c for c in cands
                  if not c["tech"] and len(c["labels"]) < lbl.MIN_LABELS_FOR_CARD
                  and c["cls"] not in gate.CHART_CLASSES]
        steps = procedure.build_procedure(page, [c["bbox"] for c in panels]) if len(panels) >= 3 else None
        if steps:
            consumed = {c["idx"] for c in panels}
            cards.append({
                "figure_id": f"proc_p{page_no}", "text": format_procedure(steps, section),
                "content_type": "procedure", "class_hint": "procedure",
                "confidence": "high", "source": "text_layer", "page": page_no,
            })
            run.note("procedure")

    # ---- figure cards
    for c in cands:
        if c["idx"] in consumed:
            continue
        pic, bbox, cls, labels = c["pic"], c["bbox"], c["cls"], list(c["labels"])
        source = "text_layer" if labels else "none"
        png = None
        wants_vlm = bool(getattr(st, "pdf_vlm_enabled", False))
        use_ocr = wants_vlm or bool(getattr(st, "pdf_figure_ocr", False))
        if use_ocr and len(labels) < lbl.MIN_LABELS_FOR_CARD and (cls in gate.DIAGRAM_CLASSES or c["tech"]):
            try:
                dpi = int(getattr(st, "pdf_figure_render_dpi", 200))
                png = ocr.render_crop(page, bbox, dpi)
                found = ocr.ocr_labels(png, px_per_pt=ocr.effective_dpi(bbox, dpi) / 72.0)
                if len(found) > len(labels):
                    labels, source = found, "ocr"
                    c["tech"] = lbl.is_technical(labels, tech_re)
            except Exception as exc:
                logger.warning("pdf_v6: %s OCR failed: %s", c["figure_id"], exc)
            reason = gate.class_skip(cls, c["tech"], len(labels))
            if reason:
                run.note(reason)
                continue

        caption = ""
        try:
            caption = txt.clean_caption(pic.caption_text(doc) or "")
        except Exception:
            pass
        if len(labels) < lbl.MIN_LABELS_FOR_CARD and not caption:
            run.note("skip_no_text")
            continue

        connections: list[dict] = []
        max_vlm = int(getattr(st, "pdf_vlm_max_per_doc", 40))
        if (wants_vlm and len(labels) >= lbl.MIN_LABELS_FOR_CARD
                and (cls in gate.DIAGRAM_CLASSES or c["tech"]) and run.vlm_calls < max_vlm):
            try:
                png = png or ocr.render_crop(page, bbox, int(getattr(st, "pdf_figure_render_dpi", 200)))
                run.vlm_calls += 1
                raw = vlm.parse_vlm_json(vlm.chat(
                    png, vlm.build_prompt(labels, section, caption),
                    getattr(st, "pdf_vlm_model", "qwen2.5vl:3b"),
                    st.ollama_host, st.ollama_port,
                    int(getattr(st, "pdf_vlm_timeout", 120)),
                    str(getattr(st, "pdf_vlm_keep_alive", "5m")),
                ))
                connections = vlm.validate_connections(raw, labels + ([caption] if caption else []))
                run.note("vlm_edges_kept" if connections else "vlm_edges_none")
                if raw and len(connections) < len(raw):
                    run.note("vlm_edges_dropped")
            except Exception as exc:
                run.note("vlm_error")
                logger.warning("pdf_v6: %s VLM read failed: %s", c["figure_id"], exc)

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
