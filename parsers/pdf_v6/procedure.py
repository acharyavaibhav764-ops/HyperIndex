"""Step-by-step illustration pages -> ONE ordered Procedure chunk.

A page of 3+ similar line-art panels with a short sentence under each is a procedure
("Reinsert the PCB...", "Plug in the connection cable...").  The sentences are live text that
Docling already extracts, but as unrelated short paragraphs: nothing tells retrieval they are
steps 1..N of one task.  So the panels get no per-image captions; the page gets one chunk.
"""
from __future__ import annotations

import re

from .geometry import inside

MAX_PANELS = 12
MAX_CAPTION_CHARS = 220
_FIG_CAPTION_RE = re.compile(r"^(fig\.?|figure|table|abb\.?|bild)\s*\d", re.I)


def _row_major(panels: list[dict]) -> list[dict]:
    """Reading order of a panel grid: rows top to bottom, left to right within a row."""
    if not panels:
        return panels
    hs = sorted(p["bbox"][3] - p["bbox"][1] for p in panels)
    tol = max(hs[len(hs) // 2] * 0.5, 10.0)
    rows: list[list[dict]] = []
    for p in sorted(panels, key=lambda p: p["bbox"][1]):
        if rows and abs(p["bbox"][1] - rows[-1][0]["bbox"][1]) <= tol:
            rows[-1].append(p)
        else:
            rows.append([p])
    return [p for row in rows for p in sorted(row, key=lambda p: p["bbox"][0])]


def text_lines(page) -> list[tuple]:
    """[(text, (x0, y0, x1, y1))] for every text line on the page (PyMuPDF 'dict' lines).

    Lines, not blocks: PyMuPDF happily merges two captions that sit side by side on the same
    baseline into one block, which would glue two steps together.
    """
    out = []
    try:
        for blk in page.get_text("dict").get("blocks", []):
            if blk.get("type") != 0:
                continue
            for ln in blk.get("lines", []):
                text = "".join(sp.get("text", "") for sp in ln.get("spans", [])).strip()
                if text:
                    out.append((text, tuple(ln["bbox"])))
    except Exception:
        return []
    return out


def build_procedure(page, bboxes: list[tuple], max_gap: float = 90.0) -> list[str] | None:
    """Ordered step captions for a page of illustrated panels, or None when it does not look
    like a procedure.  A caption is the 1-4 text lines directly under a panel."""
    if len(bboxes) < 3 or len(bboxes) > MAX_PANELS:
        return None
    areas = [(b[2] - b[0]) * (b[3] - b[1]) for b in bboxes]
    if max(areas) / max(min(areas), 1.0) > 8:
        return None
    lines = text_lines(page)
    if not lines:
        return None
    panels = [{"bbox": b, "caption": ""} for b in bboxes]
    used: set[int] = set()
    for p in panels:
        x0, y0, x1, y1 = p["bbox"]
        cands = []
        for i, (_, r) in enumerate(lines):
            if i in used:
                continue
            cx = (r[0] + r[2]) / 2
            gap = r[1] - y1
            if gap < -4 or gap > max_gap or not (x0 - 5 <= cx <= x1 + 5):
                continue
            if any(inside(r, q["bbox"], 1.0) for q in panels):
                continue
            cands.append((r[1], i))
        if not cands:
            continue
        cands.sort()
        chosen = [cands[0][1]]
        for _, i in cands[1:4]:
            prev, cur = lines[chosen[-1]][1], lines[i][1]
            if cur[1] - prev[3] <= max(6.0, 0.9 * (prev[3] - prev[1])):
                chosen.append(i)
            else:
                break
        used.update(chosen)
        caption = re.sub(r"\s+", " ", " ".join(lines[i][0] for i in chosen)).strip()
        if len(caption) <= MAX_CAPTION_CHARS:
            p["caption"] = caption
    caps = [p["caption"] for p in panels if p["caption"]]
    if len(caps) < max(3, int(0.8 * len(panels) + 0.999)):
        return None
    if sum(1 for c in caps if _FIG_CAPTION_RE.match(c)) > len(caps) // 2:
        return None  # figure captions ("Fig. 3 ..."), not steps
    if sum(1 for c in caps if len(c.split()) >= 3) < len(caps) * 0.8:
        return None
    return [p["caption"] for p in _row_major(panels) if p["caption"]]
