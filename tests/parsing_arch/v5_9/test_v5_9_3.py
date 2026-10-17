"""v5.9.3 offline checks. Run from the repo root:  python -m pytest tests/parsing_arch/v5_9/test_v5_9_3.py -q
Set V593_K2_PDF to 89470K2.GB0_V2.pdf to enable the real-PDF legend check."""
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
cellmarks = _load("parsers/pdf_cellmarks.py")
K2 = os.getenv("V593_K2_PDF", "")


def test_fullwidth_parentheses_become_ascii():
    assert glyphs.normalize_glyphs("consumption \uff08all LED off\uff09") == "consumption (all LED off)"
    assert glyphs.strip_glyphs("a \uff08b\uff09") == "a (b)"


def test_footnote_marker_is_not_kept_as_text():
    assert cellmarks._mark_text("*") == "Yes"
    assert cellmarks._mark_text("") == "Yes"
    assert cellmarks._mark_text("Only Profile 2") == "Yes (Only Profile 2)"


class _C(SimpleNamespace):
    pass


class _FakeData:
    """docling-core-like: grid rebuilt on every access, blank placeholders for empty cells."""

    def __init__(self, n_rows, n_cols, table_cells):
        self.num_rows, self.num_cols, self.table_cells = n_rows, n_cols, table_cells

    @property
    def grid(self):
        g = [[_C(text="", bbox=None, start_row_offset_idx=r, end_row_offset_idx=r + 1,
                 start_col_offset_idx=c, end_col_offset_idx=c + 1) for c in range(self.num_cols)]
             for r in range(self.num_rows)]
        for tc in self.table_cells:
            for r in range(tc.start_row_offset_idx, tc.end_row_offset_idx):
                for c in range(tc.start_col_offset_idx, tc.end_col_offset_idx):
                    g[r][c] = tc
        return g


def _table_from_pymupdf(page, shrink=0.0):
    tab = max(page.find_tables().tables, key=lambda t: len(t.cells))
    n_rows, n_cols = len(tab.rows), max(len(r.cells) for r in tab.rows)
    tcs = []
    for ri, row in enumerate(tab.rows):
        for ci, rect in enumerate(row.cells):
            if not rect:
                continue
            txt = page.get_textbox(rect).strip()
            if txt:
                tcs.append(_C(text=txt, bbox=SimpleNamespace(l=rect[0] + shrink, t=rect[1] + shrink,
                                                            r=rect[2] - shrink, b=rect[3] - shrink),
                              start_row_offset_idx=ri, end_row_offset_idx=ri + 1,
                              start_col_offset_idx=ci, end_col_offset_idx=ci + 1))
    return SimpleNamespace(data=_FakeData(n_rows, n_cols, tcs))


@pytest.mark.skipif(not _PYMUPDF, reason="pymupdf not installed")
def test_legend_tick_next_to_equals_sign_is_not_a_mark_synthetic():
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    pm = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 24, 24))
    pm.set_rect(pm.irect, (30, 160, 60))
    page.insert_image(pymupdf.Rect(60, 100, 72, 112), pixmap=pm)       # legend swatch
    page.insert_text((76, 110), "= available")
    page.insert_image(pymupdf.Rect(60, 200, 72, 212), pixmap=pm)       # table tick, no "=" next to it
    page.insert_text((200, 210), "plain text")
    assert cellmarks._is_legend_swatch(page, (60, 100, 72, 112))
    assert not cellmarks._is_legend_swatch(page, (60, 200, 72, 212))


@pytest.mark.skipif(not K2 or not Path(K2).exists(), reason="V593_K2_PDF not set")
@pytest.mark.parametrize("shrink", [0.0, 5.0])
def test_real_k2_p17_ticks_marked_legend_untouched(shrink):
    import pymupdf
    page = pymupdf.open(K2)[16]
    item = _table_from_pymupdf(page, shrink)
    cellmarks.inject_marks(SimpleNamespace(tables=[item]), page, {"tick": "Yes", "dots": "No"}, repeat_min=3)
    cells = [c for row in item.data.grid for c in row]
    yes = [c for c in cells if c.text.startswith("Yes")]
    assert len(yes) == 16                        # 2+3+2+2+1+2+1+3 ticks in the terminals table
    assert all("available" not in c.text for c in yes)
    assert any(c.text.startswith("= available") for c in cells)
