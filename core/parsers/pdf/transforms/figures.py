"""v5.9 WP5: Deterministic figure pipeline (labels_only mode).

Builds figure cards from PictureItems without VLM. Called from pdf_router._docling_page().
"""
from __future__ import annotations

import logging
import re
import zlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docling_core.types.doc import DoclingDocument

logger = logging.getLogger(__name__)

_GENERIC_RE = re.compile(r"^In this (image|picture|diagram|figure)\b", re.I)
_ZLIB_RATIO_MIN = 0.35
_NGRAM_REPEATS = 3


def _zlib_ratio(text: str) -> float:
    raw = text.encode("utf-8")
    return len(zlib.compress(raw)) / len(raw) if raw else 1.0


def _has_repeated_ngram(text: str, n: int = 4) -> bool:
    words = text.split()
    if len(words) < n:
        return False
    grams: dict[tuple, int] = {}
    for i in range(len(words) - n + 1):
        g = tuple(words[i:i + n])
        grams[g] = grams.get(g, 0) + 1
    return any(c >= _NGRAM_REPEATS for c in grams.values())


def _dedup(labels: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for l in labels:
        k = l.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(l.strip())
    return out


def _extract_numbers(labels: list[str]) -> list[str]:
    nums = []
    for l in labels:
        nums.extend(re.findall(r"\b\d+(?:\.\d+)?\b", l))
    return list(dict.fromkeys(nums))


def _inside_table(bbox, table_bboxes) -> bool:
    px0, py0, px1, py1 = bbox
    for tx0, ty0, tx1, ty1 in table_bboxes:
        if px0 >= tx0 - 2 and py0 >= ty0 - 2 and px1 <= tx1 + 2 and py1 <= ty1 + 2:
            return True
    return False


def process_pictures(
    doc: "DoclingDocument",
    page_fitz,
    heading_path: list[str],
    page_no: int,
    mode: str = "labels_only",
    hash_cache: dict | None = None,
) -> list[dict]:
    """Build deterministic figure cards for all non-skipped PictureItems."""
    pictures = getattr(doc, "pictures", None)
    if mode == "off" or not pictures:
        return []

    hash_cache = hash_cache or {}
    table_bboxes = []
    for tbl in getattr(doc, "tables", []):
        tb = getattr(tbl, "bbox", None)
        if tb is not None:
            try:
                table_bboxes.append((float(tb.l), float(tb.t), float(tb.r), float(tb.b)))
            except Exception:
                pass

    cards = []
    for idx, pic in enumerate(doc.pictures):
        figure_id = f"fig_p{page_no}_{idx}"
        try:
            card = _build_card(pic, doc, page_fitz, heading_path, figure_id,
                               table_bboxes, hash_cache)
        except Exception as exc:
            logger.warning("pdf_figures: %s failed: %s", figure_id, exc)
            continue
        if card:
            cards.append(card)
    return cards


def _class_hint(pic) -> str:
    try:
        lbl = getattr(pic, "label", None) or getattr(pic, "predicted_class", None)
        return str(lbl) if lbl else ""
    except Exception:
        return ""


def _build_card(pic, doc, page_fitz, heading_path, figure_id, table_bboxes, hash_cache):
    raw_bbox = getattr(pic, "bbox", None)
    bbox = None
    if raw_bbox is not None:
        try:
            bbox = (float(raw_bbox.l), float(raw_bbox.t),
                    float(raw_bbox.r), float(raw_bbox.b))
        except Exception:
            pass

    if bbox and _inside_table(bbox, table_bboxes):
        return None

    if bbox:
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if w * h < 1000:
            return None

    xref = 0
    try:
        img = getattr(pic, "image", None)
        if isinstance(img, dict):
            xref = img.get("xref", 0)
    except Exception:
        pass
    if hash_cache.get(xref, 1) >= 3:
        return None

    caption = ""
    try:
        caption = (pic.caption_text(doc=None) or "").strip()
    except Exception:
        pass

    labels: list[str] = []
    if bbox and page_fitz:
        try:
            import fitz
            words = page_fitz.get_text("words", clip=fitz.Rect(*bbox))
            labels = _dedup([w[4] for w in words])
        except Exception:
            pass

    numbers = _extract_numbers(labels)
    section = " > ".join(heading_path) if heading_path else ""

    parts = []
    if caption:
        parts.append(f"Figure: {caption}")
    if section:
        parts.append(f"Section: {section}")
    if labels:
        parts.append(f"Labels: {', '.join(labels)}")
    if numbers:
        parts.append(f"Numbers: {', '.join(numbers)}")
    card_text = " | ".join(parts) if parts else f"Figure {figure_id}"

    if _generic_caption(card_text):
        return None
    if _has_repeated_ngram(card_text):
        return None
    if _zlib_ratio(card_text) < _ZLIB_RATIO_MIN:
        return None

    return {
        "figure_id": figure_id,
        "text": card_text,
        "content_type": "figure",
        "class_hint": _class_hint(pic),
        "confidence": "high",
    }


def _generic_caption(text: str) -> bool:
    return bool(_GENERIC_RE.match(text.strip())) and len(text.split()) < 12


def inject_figure_cards(doc: "DoclingDocument") -> None:
    """Ensure picture elements in DoclingDocument have clean captions without repeating hallucinated n-grams."""
    from docling_core.types.doc import PictureDescriptionData
    for pic in getattr(doc, "pictures", []):
        desc = getattr(getattr(pic, "meta", None), "description", None)
        text = getattr(desc, "text", "") if desc else ""
        if text and (_has_repeated_ngram(text) or _zlib_ratio(text) < _ZLIB_RATIO_MIN):
            desc.text = ""

        if getattr(pic, "annotations", None):
            for ann in pic.annotations:
                if isinstance(ann, PictureDescriptionData) and getattr(ann, "text", None):
                    if _has_repeated_ngram(ann.text) or _zlib_ratio(ann.text) < _ZLIB_RATIO_MIN:
                        ann.text = ""
