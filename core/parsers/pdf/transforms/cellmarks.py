"""v5.9 WP3: Availability-mark injection for PDF table cells.

Detects tick-mark images in table cells → converts to Yes/No text.
v5.9.2: image ticks are located by image centre (not strict containment) and written so they
survive Docling's computed grid. Called from pdf_router._docling_page() and _smolvlm_page() before export_to_markdown().
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
    legend: dict | None = None,
    repeat_min: int = 3,
    page_no: int = 1,
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


_SNAP_TOL = 3.0        # v5.9.2: centre-in-cell tolerance (pt); TableFormer boxes are not pixel exact
_SNAP_PITCH = 0.75     # v5.9.2: max distance to a row/col centre, as a fraction of the row/col pitch


def _is_tick_colour(page, x0, y0, x1, y1) -> bool:
    """v5.9.2: stricter than _is_greenish - judged on the non-white pixels only."""
    try:
        import fitz
        pm = page.get_pixmap(clip=fitz.Rect(x0, y0, x1, y1), colorspace=fitz.csRGB, alpha=False)
        s = pm.samples
        ink = green = 0
        for i in range(0, len(s) - 2, 3):
            r, g, b = s[i], s[i + 1], s[i + 2]
            if min(r, g, b) >= 215:
                continue
            ink += 1
            if g > r + 15 and g > b + 15:
                green += 1
        return ink > 0 and green / ink >= 0.6
    except Exception:
        return False


def _median(vals):
    v = sorted(vals)
    return v[len(v) // 2] if v else None


def _axes(cells):
    """Median centre per column / row index from the single-span cells that carry indices."""
    cols: dict[int, list[float]] = {}
    rows: dict[int, list[float]] = {}
    for cell, (l, t, r, b) in cells:
        ri = getattr(cell, "start_row_offset_idx", None)
        ci = getattr(cell, "start_col_offset_idx", None)
        if ri is None or ci is None:
            continue
        if getattr(cell, "end_col_offset_idx", ci + 1) - ci == 1:
            cols.setdefault(ci, []).append((l + r) / 2)
        if getattr(cell, "end_row_offset_idx", ri + 1) - ri == 1:
            rows.setdefault(ri, []).append((t + b) / 2)
    return ({k: _median(v) for k, v in cols.items()}, {k: _median(v) for k, v in rows.items()})


def _nearest(axis: dict[int, float], v: float):
    if not axis:
        return None
    k = min(axis, key=lambda i: abs(axis[i] - v))
    pts = sorted(axis.values())
    pitch = _median([b - a for a, b in zip(pts, pts[1:])]) if len(pts) > 1 else None
    if pitch and abs(axis[k] - v) > _SNAP_PITCH * pitch:
        return None
    return k


def _write_position(table_item, r: int, c: int, text: str) -> bool:
    """v5.9.2: write `text` into grid position (r, c) in a way that survives export.

    docling-core builds `grid` fresh on every access and fills cells that have no content with
    new blank placeholders, so `grid[r][c].text = ...` on an empty cell is silently lost. Write
    into `table_cells` instead (adding a cell when none covers the position)."""
    data = table_item.data
    tcs = getattr(data, "table_cells", None)
    if tcs is None:
        try:
            data.grid[r][c].text = text
            return True
        except Exception:
            return False
    for tc in tcs:
        if (tc.start_row_offset_idx <= r < tc.end_row_offset_idx
                and tc.start_col_offset_idx <= c < tc.end_col_offset_idx):
            tc.text = text
            return True
    if not tcs:
        return False
    upd = dict(text=text, row_span=1, col_span=1, start_row_offset_idx=r, end_row_offset_idx=r + 1,
               start_col_offset_idx=c, end_col_offset_idx=c + 1, column_header=False,
               row_header=False, bbox=None)
    proto = tcs[0]
    if hasattr(proto, "model_copy"):
        new = proto.model_copy(update=upd)
    else:
        import copy
        new = copy.copy(proto)
        for k, v in upd.items():
            setattr(new, k, v)
    tcs.append(new)
    return True


def _mark_text(old: str) -> str:
    old = (old or "").strip()
    # v5.9.3: a footnote marker such as "*" carries no text; chunk cleanup strips it to "Yes ()"
    return "Yes" if (not old or old in ("...", "\u2026") or not re.search(r"\w", old)) else f"Yes ({old})"


def _is_legend_swatch(page, bbox) -> bool:
    """v5.9.3: the tick in the table legend ("[tick] = available") is a key, not a table value.
    On the SEM manual it sits inside the last body row's box and was written into that row."""
    try:
        import fitz
        x0, y0, x1, y1 = bbox
        words = page.get_text("words", clip=fitz.Rect(x1, y0 - 2, x1 + 40, y1 + 2))
        words.sort(key=lambda w: w[0])
        return bool(words) and words[0][4].startswith("=")
    except Exception:
        return False

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

    # v5.9.2: v5.9.1 required a tick image to lie FULLY inside one cell box (2 pt tolerance).
    # That passed the offline test (exact PyMuPDF ruling-line rectangles) but not on real Docling
    # output, whose TableFormer boxes are approximate and whose empty cells are blank placeholders.
    # Now: the image CENTRE must fall in a cell box (+3 pt) or snap to the nearest row/column.
    tl_ = min(bb[0] for _, bb in cells) - _SNAP_TOL
    tt_ = min(bb[1] for _, bb in cells) - _SNAP_TOL
    tr_ = max(bb[2] for _, bb in cells) + _SNAP_TOL
    tb_ = max(bb[3] for _, bb in cells) + _SNAP_TOL
    col_x, row_y = _axes(cells)

    n_small = 0
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
        cx, cy = (ix0 + ix1) / 2, (iy0 + iy1) / 2
        if not (tl_ <= cx <= tr_ and tt_ <= cy <= tb_):
            continue
        if _is_legend_swatch(page_fitz, (ix0, iy0, ix1, iy1)):
            continue
        n_small += 1
        xref = img.get("xref", 0)
        candidates.append({"bbox": (ix0, iy0, ix1, iy1), "c": (cx, cy), "xref": xref,
                            "hash": _cand_hash(img, page_fitz, xref)})

    def locate(c):
        """-> (cell | None, (row, col) | None) for a candidate image."""
        cx, cy = c["c"]
        hit = [(cell, bb) for cell, bb in cells
               if bb[0] - _SNAP_TOL <= cx <= bb[2] + _SNAP_TOL and bb[1] - _SNAP_TOL <= cy <= bb[3] + _SNAP_TOL]
        if hit:
            cell = min(hit, key=lambda x: (x[1][2] - x[1][0]) * (x[1][3] - x[1][1]))[0]
            return cell, (getattr(cell, "start_row_offset_idx", None), getattr(cell, "start_col_offset_idx", None))
        ci, ri = _nearest(col_x, cx), _nearest(row_y, cy)
        return (None, (ri, ci)) if ri is not None and ci is not None else (None, None)

    hash_count: dict[str, int] = {}
    for cand in candidates:
        if cand["hash"]:
            hash_count[cand["hash"]] = hash_count.get(cand["hash"], 0) + 1
    mark_hashes = {h for h, n in hash_count.items() if n >= repeat_min}

    col_img_count: dict[int, int] = {}
    col_total: dict[int, int] = {}
    for row_i, row in enumerate(grid):
        for col_i, cell in enumerate(row):
            if row_i:
                col_total[col_i] = col_total.get(col_i, 0) + 1

    marked_cells: set[int] = set()
    marked_pos: set[tuple] = set()
    n_marked = 0
    for cand in candidates:
        cell, pos = locate(cand)
        ix0, iy0, ix1, iy1 = cand["bbox"]
        if mark_hashes:                      # repeated image: the classic tick
            is_mark = cand["hash"] in mark_hashes and _is_greenish(page_fitz, ix0, iy0, ix1, iy1)
        else:                                # digests missing / all different: judge by colour
            is_mark = _is_tick_colour(page_fitz, ix0, iy0, ix1, iy1)
        if not is_mark:
            if cell is not None:
                ci = getattr(cell, "start_col_offset_idx", -1)
                col_img_count[ci] = col_img_count.get(ci, 0) + 1
            continue
        if cell is not None and id(cell) in marked_cells:
            continue
        if cell is None and (pos is None or pos in marked_pos):
            continue
        if cell is not None:
            cell.text = _mark_text(cell.text)
            marked_cells.add(id(cell))
            n_marked += 1
        else:
            r, c_ = pos
            try:
                old = grid[r][c_].text
            except Exception:
                old = ""
            if _write_position(table_item, r, c_, _mark_text(old)):
                marked_pos.add(pos)
                n_marked += 1

    for cell, (cx0, cy0, cx1, cy1) in cells:
        if id(cell) in marked_cells:
            continue
        pos = (getattr(cell, "start_row_offset_idx", None), getattr(cell, "start_col_offset_idx", None))
        if pos in marked_pos:
            continue
        _apply_dots(cell, legend)
        if not (cell.text or "").strip():
            ocr = _ocr_cell(page_fitz, cx0, cy0, cx1, cy1)
            if ocr:
                cell.text = ocr

    # v5.9.2: always visible in the console when small images were seen but none became a mark.
    (logger.warning if (n_small and not n_marked) else logger.info)(
        "cellmarks: %d cells, %d small imgs in table, %d repeated-hash groups, %d cells marked",
        len(cells), n_small, len(mark_hashes), n_marked)
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
