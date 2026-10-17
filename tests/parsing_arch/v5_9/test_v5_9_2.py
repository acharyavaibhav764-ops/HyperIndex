"""v5.9.2 offline checks - pure Python (+ PyMuPDF for the synthetic tick page), no Docling needed.

Run from the repo root:   python -m pytest tests/parsing_arch/v5_9/test_v5_9_2.py -q
Set V592_STIP_PDF to 89470J4.GB0.pdf to enable the real-PDF glyph check.
"""
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))

_PYMUPDF = importlib.util.find_spec("pymupdf") is not None


def _load(rel: str):
    p = _REPO / rel
    spec = importlib.util.spec_from_file_location(p.stem, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


glyphs = _load("parsers/pdf_glyphs.py")
cc = _load("core/chunk_cleanup.py")
STIP = os.getenv("V592_STIP_PDF", "")


# ------------------------------------------------------------------ glyphs
def test_pymupdf4llm_tick_row_becomes_yes():
    row = "|Power in<br>24 V / 10 A|**Power supply**|\uf0fc|\uf0fc|**\u2026**|\uf0fc|"
    out = glyphs.normalize_glyphs(row)
    assert out.count("Yes") == 3 and "\uf0fc" not in out


def test_circled_numbers_follow_wingdings_order():
    assert glyphs.normalize_glyphs("hooks \uf087, state \uf088, plug \uf083") == "hooks \u2466, state \u2467, plug \u2462"


def test_arrow_and_unknown_private_use_glyph():
    assert glyphs.normalize_glyphs("Position \uf0e8 Unlock level\ue123") == "Position \u2192 Unlock level"


def test_tick_in_prose_is_kept_as_tick_not_yes():
    assert glyphs.normalize_glyphs("\uf0fc = available") == "\u2713 = available"


def test_strip_glyphs_for_coverage():
    assert glyphs.strip_glyphs("A \uf0fc B") == "A  B"


@pytest.mark.skipif(not STIP or not Path(STIP).exists(), reason="V592_STIP_PDF not set")
def test_real_stip_page16_has_no_private_use_left():
    import pymupdf
    import pymupdf4llm
    md = pymupdf4llm.to_markdown(pymupdf.open(STIP), pages=[15])
    assert "\uf0fc" in md                      # the bug: raw glyphs reach the chunk text
    fixed = glyphs.normalize_glyphs(md)
    assert not any("\ue000" <= ch <= "\uf8ff" for ch in fixed)
    assert fixed.count("Yes") >= 30


# ------------------------------------------------------------------ ToC
STIP_TOC_P3 = (
    "Systevo Touch IP (STIP)\n\u00a9 Honeywell International Inc./technical changes reserved!\n"
    "tunnel socket) 9 2.4 Inserting the connection board into the bottom housing panel 10 "
    "2.5 Installation of the Touch terminal and connection board 12 2.6 Removing the Touch terminal "
    "from the bottom housing panel / connection board 15 3 Electrical connection 16 3.1 Connection "
    "board versions 17 3.1.1 Connection board 79CM307Z1 data bus mode 17 3.1.2 Connection board "
    "79CM307Z2 IP+ mode 18"
)
BODY_SECTION_LIST = (
    "7 Pre-defined profiles\n7.1 Profile 1\n7.1.1 Connection examples of passive components in "
    "profile 1\nBy default, if profile 1 is selected, the outputs of I/O ports 1-4 are allocated "
    "to the functions presence 1, call and BATHROOM / WC."
)


def test_reflowed_toc_continuation_is_toc_after_a_toc_chunk():
    meta = {"content_type": "text", "heading_path": "Systevo Touch IP (STIP)"}
    assert cc._is_toc_chunk(STIP_TOC_P3, meta, prev_is_toc=False)       # dense enough on its own
    assert cc._is_toc_chunk(STIP_TOC_P3[:200] + " 17 3.2 x 18", meta, prev_is_toc=True)


def test_body_text_with_section_numbers_is_not_toc():
    meta = {"content_type": "text", "heading_path": "7 Pre-defined profiles"}
    assert not cc._is_toc_chunk(BODY_SECTION_LIST, meta, prev_is_toc=False)
    assert not cc._is_toc_chunk(BODY_SECTION_LIST, meta, prev_is_toc=True)


def test_postprocess_merges_toc_page_continuation_into_one_chunk():
    chunks = [
        "Table of contents\n1 General / Application 4 1.1 Other applicable documentation 4 "
        "1.2 List of abbreviations 5 1.3 Requirements 5 2 Installation 6 2.1 Mounting 7",
        STIP_TOC_P3,
        "Systevo Touch IP (STIP)\n[Recovered text] Systevo Touch IP (STIP) 89470J4.GB0 / 10.2021 Table of Contents",
        "1 General / Application\nThe Honeywell Systevo Touch IP terminal, hereinafter STIP, is a modern "
        "communication device equipped with a Touch terminal for care facilities.",
    ]
    metas = [{"content_type": "toc", "heading_path": "x"}] + [
        {"content_type": "text", "heading_path": "x", "page_numbers": "3"} for _ in chunks[1:3]
    ] + [{"content_type": "text", "heading_path": "1 General / Application"}]
    out, om = cc.postprocess_chunks(chunks, metas)
    assert [m["content_type"] for m in om] == ["toc", "text"]
    assert "Systevo Touch IP (STIP)\n" not in out[0].split("\n", 1)[1][:30]   # running header dropped
    assert "2.5 Installation" in out[0] and "Recovered text" not in out[0]


# ------------------------------------------------------------------ cellmarks on Docling-like tables
class _Cell(SimpleNamespace):
    pass


class _FakeData:
    """Mimics docling-core TableData: `grid` is rebuilt on every access and every position that has
    no cell in `table_cells` is a fresh blank placeholder (so writes to it are lost)."""

    def __init__(self, n_rows, n_cols, table_cells):
        self.num_rows, self.num_cols, self.table_cells = n_rows, n_cols, table_cells

    @property
    def grid(self):
        g = [[_Cell(text="", bbox=None, start_row_offset_idx=r, end_row_offset_idx=r + 1,
                    start_col_offset_idx=c, end_col_offset_idx=c + 1) for c in range(self.num_cols)]
             for r in range(self.num_rows)]
        for tc in self.table_cells:
            for r in range(tc.start_row_offset_idx, tc.end_row_offset_idx):
                for c in range(tc.start_col_offset_idx, tc.end_col_offset_idx):
                    g[r][c] = tc
        return g


def _tick_page(n_rows=5, n_cols=4, cw=90.0, rh=30.0):
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    x0, y0 = 50.0, 100.0
    for r in range(n_rows + 1):
        page.draw_line((x0, y0 + r * rh), (x0 + n_cols * cw, y0 + r * rh))
    for c in range(n_cols + 1):
        page.draw_line((x0 + c * cw, y0), (x0 + c * cw, y0 + n_rows * rh))
    pm = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 24, 24))
    pm.set_rect(pm.irect, (30, 160, 60))
    ticks = [(1, 2), (2, 2), (3, 3), (4, 1), (4, 3)]
    for r, c in ticks:
        cx, cy = x0 + c * cw + cw / 2, y0 + r * rh + rh / 2
        page.insert_image(pymupdf.Rect(cx - 6, cy - 6, cx + 6, cy + 6), pixmap=pm)
    return page, (x0, y0, cw, rh), ticks


@pytest.mark.parametrize("shrink", [0.0, 6.0, 14.0])
@pytest.mark.skipif(not _PYMUPDF, reason="pymupdf not installed")
def test_ticks_survive_inexact_boxes_and_blank_placeholders(shrink):
    pdf_cellmarks = _load("parsers/pdf_cellmarks.py")
    page, (x0, y0, cw, rh), ticks = _tick_page()
    n_rows, n_cols = 5, 4
    cells = []
    for r in range(n_rows):
        for c in range(n_cols):
            if r == 0 or c == 0:                       # header row / label column have text and boxes
                cells.append(_Cell(text=f"t{r}{c}",
                                   bbox=SimpleNamespace(l=x0 + c * cw + shrink, t=y0 + r * rh + shrink,
                                                        r=x0 + (c + 1) * cw - shrink, b=y0 + (r + 1) * rh - shrink),
                                   start_row_offset_idx=r, end_row_offset_idx=r + 1,
                                   start_col_offset_idx=c, end_col_offset_idx=c + 1))
    # a few EMPTY cells that do exist in table_cells but whose boxes are shifted (TableFormer-like)
    cells.append(_Cell(text="", bbox=SimpleNamespace(l=x0 + 2 * cw + 20, t=y0 + 1 * rh + 14, r=x0 + 3 * cw, b=y0 + 2 * rh),
                       start_row_offset_idx=1, end_row_offset_idx=2, start_col_offset_idx=2, end_col_offset_idx=3))
    item = SimpleNamespace(data=_FakeData(n_rows, n_cols, cells))
    doc = SimpleNamespace(tables=[item])
    pdf_cellmarks.inject_marks(doc, page, {"tick": "Yes", "dots": "No"}, repeat_min=3)
    grid = item.data.grid                              # fresh access, as export_to_markdown does
    for r, c in ticks:
        assert grid[r][c].text.startswith("Yes"), f"tick at ({r},{c}) lost (shrink={shrink})"
    yes = sum(1 for row in grid for cell in row if cell.text.startswith("Yes"))
    assert yes == len(ticks)
