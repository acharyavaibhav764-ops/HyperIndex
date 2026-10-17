"""v5.9 WP3: Availability-mark injection for PDF table cells.

Detects tick-mark images in table cells → converts to Yes/No text.
Called from pdf_router._docling_page() and _smolvlm_page() before export_to_markdown().
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docling_core.types.doc import DoclingDocument

logger = logging.getLogger(__name__)

_MAX_MARK_AREA_PT2 = 400.0
_ASPECT_MIN = 0.70
_ASPECT_MAX = 1.40
_LEGEND_RE = re.compile(r"=\s*(available|unavailable)", re.I)


def scan_legend(page_texts: list[str]) -> dict | None:
    """Scan all page text strings for a tick/dot availability legend.

    Returns {"tick": "Yes", "dots": "No"} when found, else None.
    """
    combined = " ".join(page_texts)
    if _LEGEND_RE.search(combined):
        return {"tick": "Yes", "dots": "No"}
    return None


def _bbox_to_tuple(bbox) -> tuple:
    return float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b)


def _flip_if_needed(l, t, r, b, page_height: float) -> tuple:
    if t > b:
        t, b = page_height - b, page_height - t
    return l, t, r, b


def _inside(ix0, iy0, ix1, iy1, ox0, oy0, ox1, oy1, tol: float = 2.0) -> bool:
    return (ix0 >= ox0 - tol and iy0 >= oy0 - tol
            and ix1 <= ox1 + tol and iy1 <= oy1 + tol)


def _cand_hash(img: dict, page, xref: int) -> str:
    """v5.9.1: availability ticks are INLINE images (xref == 0), so extract_image(xref) cannot
    hash them. PyMuPDF already reports an MD5 'digest' per image in get_image_info()."""
    d = img.get("digest")
    if d:
        return d.hex() if isinstance(d, (bytes, bytearray)) else str(d)
    return _image_hash(page, xref) if xref else ""


def _image_hash(page, xref: int) -> str:
    try:
        data = page.parent.extract_image(xref)["image"]
        return hashlib.md5(data).hexdigest()
    except Exception:
        return ""


def _is_greenish(page, x0, y0, x1, y1) -> bool:
    try:
        import fitz
        clip = fitz.Rect(x0, y0, x1, y1)
        pm = page.get_pixmap(clip=clip, colorspace=fitz.csRGB, alpha=False)
        s = pm.samples
        if not s:
            return True
        r_s = sum(s[i]     for i in range(0, len(s), 3))
        g_s = sum(s[i + 1] for i in range(0, len(s), 3))
        b_s = sum(s[i + 2] for i in range(0, len(s), 3))
        return g_s > r_s and g_s > b_s
    except Exception:
        return True


def _ocr_cell(page, x0, y0, x1, y1) -> str:
    try:
        import fitz
        clip = fitz.Rect(x0, y0, x1, y1)
        words = page.get_text("words", clip=clip)
        if words:
            return " ".join(w[4] for w in words).strip()
    except Exception:
        pass
    return ""


def inject_marks(
    doc: "DoclingDocument",
    page_fitz,
    legend: dict | None,
    repeat_min: int = 3,
) -> None:
    """Inject availability-mark text into TableCell.text fields in-place.

    Must be called BEFORE doc.export_to_markdown() while cell bboxes exist.
    Note: WP0 grid-caching test determines whether mutation is effective.
    If the grid is cached, this no-ops gracefully and logs a warning.
    """
    if not doc.tables:
        return

    page_height = float(page_fitz.rect.height)

    try:
        all_images = page_fitz.get_image_info(hashes=True, xrefs=True)
    except Exception:
        all_images = []

    for table_item in doc.tables:
        try:
            _process_table(table_item, all_images, page_fitz,
                           page_height, legend, repeat_min)
        except Exception as exc:
            logger.warning("cellmarks: table processing failed: %s", exc)


def _process_table(table_item, all_images, page_fitz, page_height, legend, repeat_min):
    grid = table_item.data.grid
    if not grid:
        return

    cells = []
    for row in grid:
        for cell in row:
            raw = getattr(cell, "bbox", None)
            if raw is None:
                continue
            try:
                l, t, r, b = _bbox_to_tuple(raw)
                l, t, r, b = _flip_if_needed(l, t, r, b, page_height)
                cells.append((cell, (l, t, r, b)))
            except Exception:
                continue

    if not cells:
        return

    candidates = []
    for img in all_images:
        ib = img.get("bbox") or img.get("rect")
        if ib is None:
            continue
        ix0, iy0, ix1, iy1 = float(ib[0]), float(ib[1]), float(ib[2]), float(ib[3])
        w, h = ix1 - ix0, iy1 - iy0
        if w <= 0 or h <= 0 or w * h > _MAX_MARK_AREA_PT2:
            continue
        asp = w / h
        if not (_ASPECT_MIN <= asp <= _ASPECT_MAX):
            continue
        in_cell = any(_inside(ix0, iy0, ix1, iy1, *pm) for _, pm in cells)
        if not in_cell:
            continue
        xref = img.get("xref", 0)
        candidates.append({"bbox": (ix0, iy0, ix1, iy1), "xref": xref,
                           "hash": _cand_hash(img, page_fitz, xref)})

    if not candidates:
        for cell, _ in cells:
            _apply_dots(cell, legend)
        return

    hash_count: dict[str, int] = {}
    for cand in candidates:
        h = cand["hash"]
        if h:
            hash_count[h] = hash_count.get(h, 0) + 1

    mark_hashes = {h for h, c in hash_count.items() if c >= repeat_min}

    col_img_count: dict[int, int] = {}
    col_total: dict[int, int] = {}
    for row_i, row in enumerate(grid):
        for col_i, cell in enumerate(row):
            if row_i == 0:
                continue
            col_total[col_i] = col_total.get(col_i, 0) + 1

    n_marked = 0
    for cell, (cx0, cy0, cx1, cy1) in cells:
        col_i = getattr(cell, "start_col_offset_idx", -1)
        mark_found = False

        for cand in candidates:
            ix0, iy0, ix1, iy1 = cand["bbox"]
            if not _inside(ix0, iy0, ix1, iy1, cx0, cy0, cx1, cy1):
                continue
            h = cand["hash"]
            if not h or h not in mark_hashes:
                col_img_count[col_i] = col_img_count.get(col_i, 0) + 1
                continue
            if not _is_greenish(page_fitz, ix0, iy0, ix1, iy1):
                continue
            mark_found = True
            break

        if mark_found:
            n_marked += 1
            old = (cell.text or "").strip()
            if not old or old in ("...", "..."):
                cell.text = "Yes"
            else:
                cell.text = f"Yes ({old})"
        else:
            _apply_dots(cell, legend)
            if not (cell.text or "").strip():
                ocr = _ocr_cell(page_fitz, cx0, cy0, cx1, cy1)
                if ocr:
                    cell.text = ocr

    logger.info("cellmarks: %d cells, %d candidate imgs, %d mark hashes, %d cells marked",
                len(cells), len(candidates), len(mark_hashes), n_marked)
    header_row = grid[0] if grid else []
    for col_i, img_c in col_img_count.items():
        total = col_total.get(col_i, 1)
        if total > 0 and img_c / total >= 0.8:
            col_name = "Figure"
            if col_i < len(header_row):
                col_name = (header_row[col_i].text or "Figure").strip()
            logger.info("cellmarks: thumbnail column %r (col %d) cleared", col_name, col_i)
            for row in grid:
                if col_i < len(row):
                    row[col_i].text = f"[{col_name}: product picture]"


# v5.9.1+: Unicode checkmark characters that appear as text in some PDFs
# (as opposed to inline images handled by inject_marks above).
# Covers standard checkmarks, heavy variants, ballot boxes, and the common
# Wingdings/Symbol font codepoints that PyMuPDF maps to these code points.
_TEXT_TICK_CHARS = frozenset({
    "\u2713",  # ✓ CHECK MARK
    "\u2714",  # ✔ HEAVY CHECK MARK
    "\u2611",  # ☑ BALLOT BOX WITH CHECK
    "\u2705",  # ✅ WHITE HEAVY CHECK MARK (emoji)
    "\u221a",  # √ SQUARE ROOT (Wingdings tick)
    "\uf052",  # Private Use Area — common Wingdings tick mapping
    "\uf0fc",  # Private Use Area — Symbol font tick
    "\uf0fe",  # Private Use Area — Wingdings 2 tick
})

_TEXT_CROSS_CHARS = frozenset({
    "\u2717",  # ✗ BALLOT X
    "\u2718",  # ✘ HEAVY BALLOT X
    "\u2612",  # ☒ BALLOT BOX WITH X
    "\u274c",  # ❌ CROSS MARK (emoji)
    "\u00d7",  # × MULTIPLICATION SIGN (often used as cross)
})


def _normalize_text_ticks(cell) -> None:
    """v5.9.1+: convert Unicode checkmark / cross characters to 'Yes' / 'No'.

    Some PDFs encode availability ticks as font glyphs that Docling extracts
    as Unicode characters rather than inline images.  inject_marks() cannot
    detect these because there are no images in the cell.  This pass runs
    after inject_marks() and normalises any surviving tick/cross characters.
    """
    text = (cell.text or "").strip()
    if not text:
        return
    # Single-char cell or cell whose entire content is tick/cross chars
    unique = set(text)
    if unique <= _TEXT_TICK_CHARS:
        cell.text = "Yes"
    elif unique <= _TEXT_CROSS_CHARS:
        cell.text = "No"
    elif len(text) <= 4 and any(c in _TEXT_TICK_CHARS for c in text):
        # e.g. "✓ " or "✓1" — tick with minor suffix
        cell.text = "Yes"


def _apply_dots(cell, legend):
    _normalize_text_ticks(cell)  # v5.9.1+: handle text-based ticks first
    text = (cell.text or "").strip()
    if text in ("...", "…", "⋯") and legend and legend.get("dots") == "No":

        cell.text = "No"
