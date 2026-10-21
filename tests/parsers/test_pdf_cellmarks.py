import unittest
from types import SimpleNamespace

import fitz

from core.parsers.pdf.transforms.cellmarks import (
    _inside,
    _is_legend_swatch,
    _is_tick_colour,
    _mark_text,
    inject_marks,
    scan_legend,
)


class _Cell(SimpleNamespace):
    pass


class _FakeData:
    """Mimics docling-core TableData: grid rebuilt on every access, placeholders for missing cells."""

    def __init__(self, n_rows, n_cols, table_cells):
        self.num_rows = n_rows
        self.num_cols = n_cols
        self.table_cells = table_cells

    @property
    def grid(self):
        g = [
            [
                _Cell(
                    text="",
                    bbox=None,
                    start_row_offset_idx=r,
                    end_row_offset_idx=r + 1,
                    start_col_offset_idx=c,
                    end_col_offset_idx=c + 1,
                )
                for c in range(self.num_cols)
            ]
            for r in range(self.num_rows)
        ]
        for tc in self.table_cells:
            for r in range(tc.start_row_offset_idx, tc.end_row_offset_idx):
                for c in range(tc.start_col_offset_idx, tc.end_col_offset_idx):
                    g[r][c] = tc
        return g


def _build_tick_page(n_rows=5, n_cols=4, cw=90.0, rh=30.0):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    x0, y0 = 50.0, 100.0
    for r in range(n_rows + 1):
        page.draw_line((x0, y0 + r * rh), (x0 + n_cols * cw, y0 + r * rh))
    for c in range(n_cols + 1):
        page.draw_line((x0 + c * cw, y0), (x0 + c * cw, y0 + n_rows * rh))
    pm = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 24, 24))
    pm.set_rect(pm.irect, (30, 160, 60))
    ticks = [(1, 2), (2, 2), (3, 3), (4, 1), (4, 3)]
    for r, c in ticks:
        cx, cy = x0 + c * cw + cw / 2, y0 + r * rh + rh / 2
        page.insert_image(fitz.Rect(cx - 6, cy - 6, cx + 6, cy + 6), pixmap=pm)
    return page, (x0, y0, cw, rh), ticks


class TestPdfCellmarks(unittest.TestCase):
    """Unit tests for availability marks and legend discovery in tables."""

    def test_scan_legend_detection(self):
        """scan_legend correctly identifies availability legend definitions."""
        page_texts = [
            "Honeywell Model 500 Features",
            "Notes: [check] = available, [dot] = unavailable",
        ]
        legend = scan_legend(page_texts)
        self.assertIsNotNone(legend)
        self.assertEqual(legend.get("tick"), "Yes")
        self.assertEqual(legend.get("dots"), "No")

    def test_inside_bounding_box_collision(self):
        """_inside correctly identifies image inside cell boundaries."""
        # Cell: (100, 100, 200, 200)
        # Image: (120, 120, 140, 140) -> inside
        self.assertTrue(_inside(120, 120, 140, 140, 100, 100, 200, 200))

        # Image far away: (300, 300, 320, 320) -> outside
        self.assertFalse(_inside(300, 300, 320, 320, 100, 100, 200, 200))

    def test_footnote_marker_and_mark_text(self):
        """_mark_text replaces footnote asterisks and preserves qualifiers."""
        self.assertEqual(_mark_text("*"), "Yes")
        self.assertEqual(_mark_text(""), "Yes")
        self.assertEqual(_mark_text("Only Profile 2"), "Yes (Only Profile 2)")

    def test_is_tick_colour_detection(self):
        """_is_tick_colour flags green / blue chroma and rejects pure gray / black."""
        doc = fitz.open()
        page = doc.new_page(width=100, height=100)
        green_pm = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10))
        green_pm.set_rect(green_pm.irect, (30, 180, 60))
        page.insert_image(fitz.Rect(10, 10, 20, 20), pixmap=green_pm)
        self.assertTrue(_is_tick_colour(page, 10, 10, 20, 20))

        gray_pm = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10))
        gray_pm.set_rect(gray_pm.irect, (100, 100, 100))
        page.insert_image(fitz.Rect(30, 30, 40, 40), pixmap=gray_pm)
        self.assertFalse(_is_tick_colour(page, 30, 30, 40, 40))

    def test_legend_swatch_exclusion(self):
        """_is_legend_swatch excludes swatch icons placed beside '= available'."""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        pm = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 24, 24))
        pm.set_rect(pm.irect, (30, 160, 60))
        page.insert_image(fitz.Rect(60, 100, 72, 112), pixmap=pm)
        page.insert_text((76, 110), "= available")
        page.insert_image(fitz.Rect(60, 200, 72, 212), pixmap=pm)
        page.insert_text((200, 210), "plain text")

        self.assertTrue(_is_legend_swatch(page, (60, 100, 72, 112)))
        self.assertFalse(_is_legend_swatch(page, (60, 200, 72, 212)))

    def test_ticks_survive_inexact_boxes_and_blank_placeholders(self):
        """Grid snapping associates displaced tick marks with corresponding table cells."""
        page, (x0, y0, cw, rh), ticks = _build_tick_page()
        n_rows, n_cols = 5, 4
        cells = []
        for r in range(n_rows):
            for c in range(n_cols):
                if r == 0 or c == 0:
                    cells.append(
                        _Cell(
                            text=f"t{r}{c}",
                            bbox=SimpleNamespace(
                                l=x0 + c * cw + 6,
                                t=y0 + r * rh + 6,
                                r=x0 + (c + 1) * cw - 6,
                                b=y0 + (r + 1) * rh - 6,
                            ),
                            start_row_offset_idx=r,
                            end_row_offset_idx=r + 1,
                            start_col_offset_idx=c,
                            end_col_offset_idx=c + 1,
                        )
                    )
        item = SimpleNamespace(data=_FakeData(n_rows, n_cols, cells))
        doc = SimpleNamespace(tables=[item])
        inject_marks(doc, page, {"tick": "Yes", "dots": "No"}, repeat_min=3)
        grid = item.data.grid

        for r, c in ticks:
            self.assertTrue(
                grid[r][c].text.startswith("Yes"),
                f"Tick at ({r},{c}) was not marked as 'Yes'",
            )
        yes_count = sum(1 for row in grid for cell in row if cell.text.startswith("Yes"))
        self.assertEqual(yes_count, len(ticks))


if __name__ == "__main__":
    unittest.main()
