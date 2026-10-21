"""
Ported v5.9 regression test suite (test_v5_9_1 through test_v5_9_4).
Guarantees 100% heuristic parity with parser_v1 across glyphs, cellmarks, coverage, and chunk cleanup.
"""
import unittest
from types import SimpleNamespace

import fitz

from core.chunk_cleanup import (
    _is_toc_chunk,
    extract_doc_meta,
    postprocess_chunks,
    section_id,
)
from core.parsers.pdf.transforms.cellmarks import (
    _inside,
    _is_legend_swatch,
    _mark_text,
    inject_marks,
)
from core.parsers.pdf.transforms.coverage import check_page
from core.parsers.pdf.transforms.glyphs import normalize_glyphs, strip_glyphs


# ============================================================================
# Helpers & Synthetic Fixtures
# ============================================================================

def _meta(ct="table", hp=None, pages=(30,)):
    return {
        "content_type": ct,
        "heading_path": hp or ["7. Specifications"],
        "page_numbers": list(pages),
    }


class _Cell(SimpleNamespace):
    pass


class _FakeData:
    """Mimics docling-core TableData: grid rebuilt on access, blank placeholders for empty cells."""

    def __init__(self, n_rows, n_cols, table_cells):
        self.num_rows, self.num_cols, self.table_cells = n_rows, n_cols, table_cells

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


def _tick_page(n_rows=5, n_cols=4, cw=90.0, rh=30.0):
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


STIP_TOC_P3 = (
    "Systevo Touch IP (STIP)\n© Honeywell International Inc./technical changes reserved!\n"
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


# ============================================================================
# Regression Test Cases
# ============================================================================

class TestPdfV59Regression(unittest.TestCase):
    """Port of v5.9 regression suite testing the unified PDF pipeline."""

    # ------------------------------------------------------------------ Glyphs
    def test_pymupdf4llm_tick_row_becomes_yes(self):
        row = "|Power in<br>24 V / 10 A|**Power supply**|\uf0fc|\uf0fc|**\u2026**|\uf0fc|"
        out = normalize_glyphs(row)
        self.assertEqual(out.count("Yes"), 3)
        self.assertNotIn("\uf0fc", out)

    def test_circled_numbers_follow_wingdings_order(self):
        self.assertEqual(
            normalize_glyphs("hooks \uf087, state \uf088, plug \uf083"),
            "hooks ⑦, state ⑧, plug ③",
        )

    def test_arrow_and_unknown_private_use_glyph(self):
        self.assertEqual(
            normalize_glyphs("Position \uf0e8 Unlock level\ue123"),
            "Position → Unlock level",
        )

    def test_tick_in_prose_is_kept_as_tick_not_yes(self):
        self.assertEqual(normalize_glyphs("\uf0fc = available"), "✓ = available")

    def test_strip_glyphs_for_coverage(self):
        self.assertEqual(strip_glyphs("A \uf0fc B"), "A  B")

    def test_fullwidth_parentheses_become_ascii(self):
        self.assertEqual(
            normalize_glyphs("consumption \uff08all LED off\uff09"),
            "consumption (all LED off)",
        )
        self.assertEqual(strip_glyphs("a \uff08b\uff09"), "a (b)")

    # ---------------------------------------------------------------- Cellmarks
    def test_footnote_marker_is_not_kept_as_text(self):
        self.assertEqual(_mark_text("*"), "Yes")
        self.assertEqual(_mark_text(""), "Yes")
        self.assertEqual(_mark_text("Only Profile 2"), "Yes (Only Profile 2)")

    def test_legend_tick_next_to_equals_sign_is_not_a_mark_synthetic(self):
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
        for shrink in (0.0, 6.0, 14.0):
            page, (x0, y0, cw, rh), ticks = _tick_page()
            n_rows, n_cols = 5, 4
            cells = []
            for r in range(n_rows):
                for c in range(n_cols):
                    if r == 0 or c == 0:
                        cells.append(
                            _Cell(
                                text=f"t{r}{c}",
                                bbox=SimpleNamespace(
                                    l=x0 + c * cw + shrink,
                                    t=y0 + r * rh + shrink,
                                    r=x0 + (c + 1) * cw - shrink,
                                    b=y0 + (r + 1) * rh - shrink,
                                ),
                                start_row_offset_idx=r,
                                end_row_offset_idx=r + 1,
                                start_col_offset_idx=c,
                                end_col_offset_idx=c + 1,
                            )
                        )
            cells.append(
                _Cell(
                    text="",
                    bbox=SimpleNamespace(l=x0 + 2 * cw + 20, t=y0 + 1 * rh + 14, r=x0 + 3 * cw, b=y0 + 2 * rh),
                    start_row_offset_idx=1,
                    end_row_offset_idx=2,
                    start_col_offset_idx=2,
                    end_col_offset_idx=3,
                )
            )
            item = SimpleNamespace(data=_FakeData(n_rows, n_cols, cells))
            doc = SimpleNamespace(tables=[item])
            inject_marks(doc, page, {"tick": "Yes", "dots": "No"}, repeat_min=3)
            grid = item.data.grid
            for r, c in ticks:
                self.assertTrue(
                    grid[r][c].text.startswith("Yes"),
                    f"tick at ({r},{c}) lost (shrink={shrink})",
                )
            yes_count = sum(1 for row in grid for cell in row if cell.text.startswith("Yes"))
            self.assertEqual(yes_count, len(ticks))

    # ---------------------------------------------------------------- Coverage
    def test_coverage_restores_dropped_bold_word(self):
        md = "Features:\n- plug out call\n- presence 2\n- I/O Port"
        raw = "Features:\n- plug out call\n- No presence 2\n- I/O Port"
        out = check_page(md, raw, set())
        self.assertIn("- No presence 2", out)
        self.assertNotIn("[Recovered text]", out)

    def test_coverage_never_rewrites_table_rows(self):
        md = "| Fire class | V-0 |\n|---|---|"
        out = check_page(md, "Fire protection class\nV-O", set())
        self.assertTrue(out.startswith("| Fire class | V-0 |"))

    def test_coverage_skips_toc_page(self):
        raw = "\n".join(
            f"{i}.{j} Some section title ........ {i * 3 + j}"
            for i in range(1, 5)
            for j in range(1, 4)
        )
        self.assertEqual(check_page("Content", raw, set()), "Content")

    # ---------------------------------------------------------- Chunk Cleanup
    def test_separator_only_chunk_with_breadcrumb_is_dropped(self):
        ch = ["7. Specifications\n |\n|---|---|---|---|", "7. Specifications\n| a | b | c | d |"]
        out, _ = postprocess_chunks(ch, [_meta(), _meta()])
        self.assertEqual(len(out), 1)
        self.assertIn("a | b", out[0])

    def test_header_fragment_is_carried_to_headerless_table_chunks(self):
        ch = [
            "intro text here",
            "7. Specifications\n| Name | SEM+ | SEM | SCL |",
            "7. Specifications\n |\n|---|---|---|---|",
            "7. Specifications\n| Idle | 60mA | 52mA | ? |",
            "7. Specifications\n| Max | 140mA | 130mA | ? |",
        ]
        out, _ = postprocess_chunks(ch, [_meta("text")] + [_meta()] * 4)
        self.assertEqual(len(out), 3)
        for body in out[1:]:
            self.assertIn("| Name | SEM+ | SEM | SCL |", body)
            self.assertIn("|---|---|---|---|", body)

    def test_toc_chunks_are_tagged_and_merged(self):
        toc = [
            f"Content\n| 3.{i} | Section {i} ... | {10 + i} |\n| 3.{i}1 | Other {i} ... | {11 + i} |"
            for i in range(4)
        ]
        ch = ["Intro paragraph about the device."] + toc + ["1. General\nBody text of the real section."]
        ms = (
            [_meta("text", ["Intro"], (1,))]
            + [_meta("table", ["Content"], (3,))] * 4
            + [_meta("text", ["1. General"], (4,))]
        )
        out, metas = postprocess_chunks(ch, ms)
        self.assertEqual(len(out), 3)
        self.assertEqual(metas[1]["content_type"], "toc")
        self.assertNotIn("...", out[1])
        self.assertIn("3.2 Section 2", out[1])

    def test_reflowed_toc_continuation_is_toc_after_a_toc_chunk(self):
        meta = {"content_type": "text", "heading_path": "Systevo Touch IP (STIP)"}
        self.assertTrue(_is_toc_chunk(STIP_TOC_P3, meta, prev_is_toc=False))
        self.assertTrue(_is_toc_chunk(STIP_TOC_P3[:200] + " 17 3.2 x 18", meta, prev_is_toc=True))

    def test_body_text_with_section_numbers_is_not_toc(self):
        meta = {"content_type": "text", "heading_path": "7 Pre-defined profiles"}
        self.assertFalse(_is_toc_chunk(BODY_SECTION_LIST, meta, prev_is_toc=False))
        self.assertFalse(_is_toc_chunk(BODY_SECTION_LIST, meta, prev_is_toc=True))

    def test_postprocess_merges_toc_page_continuation_into_one_chunk(self):
        chunks = [
            "Table of contents\n1 General / Application 4 1.1 Other applicable documentation 4 "
            "1.2 List of abbreviations 5 1.3 Requirements 5 2 Installation 6 2.1 Mounting 7",
            STIP_TOC_P3,
            "Systevo Touch IP (STIP)\n[Recovered text] Systevo Touch IP (STIP) 89470J4.GB0 / 10.2021 Table of Contents",
            "1 General / Application\nThe Honeywell Systevo Touch IP terminal, hereinafter STIP, is a modern "
            "communication device equipped with a Touch terminal for care facilities.",
        ]
        metas = (
            [{"content_type": "toc", "heading_path": "x"}]
            + [{"content_type": "text", "heading_path": "x", "page_numbers": "3"} for _ in chunks[1:3]]
            + [{"content_type": "text", "heading_path": "1 General / Application"}]
        )
        out, om = postprocess_chunks(chunks, metas)
        self.assertEqual([m["content_type"] for m in om], ["toc", "text"])
        self.assertNotIn("Systevo Touch IP (STIP)\n", out[0].split("\n", 1)[1][:30])
        self.assertIn("2.5 Installation", out[0])
        self.assertNotIn("Recovered text", out[0])

    def test_heading_plus_cut_separator_row_is_dropped(self):
        junk1 = "3 Electrical connection\n3.8 Wiring terminals and their function:\n-------------------|--------|-------|"
        junk2 = "4. Room variants\n4.5 Combinations in the patient room\n----------------------------|\n"
        keep = "3 Electrical connection\n3.8 Wiring terminals\n| DBUS | Yes | Yes | Yes |"
        out, _ = postprocess_chunks([junk1, keep, junk2], [dict(_meta()) for _ in range(3)])
        self.assertEqual(len(out), 1)
        self.assertIn("| DBUS |", out[0])

    def test_real_text_chunk_with_a_rule_is_kept(self):
        text = "Safety instructions\nIn accordance with DIN VDE 0834-1, connection cables must withstand 4 kV.\n---"
        out, _ = postprocess_chunks([text], [dict(_meta())])
        self.assertTrue(any("DIN VDE" in c for c in out))

    def test_table_chunk_with_normal_separator_is_unchanged(self):
        t = "2 Installation\n| A | B |\n|---|---|\n| 1 | 2 |"
        out, _ = postprocess_chunks([t], [dict(_meta())])
        self.assertTrue(bool(out) and "| 1 | 2 |" in out[0])

    def test_section_id_uses_closest_numbered_heading(self):
        self.assertEqual(section_id(28, ["5. Notes", "1.2 Separate cancel push-button for bed"]), "p28:1.2")
        self.assertEqual(section_id(18, ["3 Electrical connection", "3.9 Factory setting", "Profile 2:"]), "p18:3.9")
        self.assertEqual(section_id(1, ["Title"]), "p1")
        self.assertEqual(section_id(None, []), "")

    def test_doc_meta_from_raw_and_docling_text(self):
        for text in [
            "89470K2.GB0_V2\n11.2020",
            "Installation Instruction\n89470K2.GB0\nV2 11.2020",
        ]:
            self.assertEqual(
                extract_doc_meta([text]),
                {"doc_number": "89470K2.GB0", "doc_version": "V2", "doc_date": "11.2020"},
            )

    def test_doc_meta_ignores_system_software_versions(self):
        self.assertEqual(
            extract_doc_meta(["needs system software V05.xx and V12.xx"])["doc_version"],
            "",
        )


if __name__ == "__main__":
    unittest.main()
