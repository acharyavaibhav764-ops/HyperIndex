import unittest

from core.chunk_cleanup import (
    _collapse_sep_rows,
    _is_toc_chunk,
    _strip_dot_runs,
    extract_doc_meta,
    postprocess_chunks,
    section_id,
    strip_markup,
)


def _meta(ct="table", hp=None, pages=(30,)):
    return {
        "content_type": ct,
        "heading_path": hp or ["7. Specifications"],
        "page_numbers": list(pages),
    }


class TestPdfChunkCleanup(unittest.TestCase):
    """Unit tests for chunk-level sanitization, header carrying, ToC merging, and metadata."""

    def test_strip_markup_and_collapse_separators(self):
        """strip_markup and _collapse_sep_rows normalize markdown noise."""
        raw = "### Heading\n**Bold Text** and *italic*\n|   col1   |   col2   |\n|:---------|:---------|"
        stripped = strip_markup(raw)
        self.assertNotIn("###", stripped)
        self.assertNotIn("**", stripped)
        self.assertIn("Bold Text", stripped)

        collapsed = _collapse_sep_rows("| col1 | col2 |\n|-----------|-----------|")
        self.assertIn("|---|---|", collapsed)

    def test_strip_dot_runs(self):
        """_strip_dot_runs collapses 4+ dots to ellipsis."""
        self.assertEqual(_strip_dot_runs("Section 1 ........ 15"), "Section 1 ... 15")

    def test_separator_only_chunk_with_breadcrumb_is_dropped(self):
        """Separator-only junk chunks are removed by postprocess_chunks."""
        chunks = [
            "7. Specifications\n |\n|---|---|---|---|",
            "7. Specifications\n| a | b | c | d |",
        ]
        out, _ = postprocess_chunks(chunks, [_meta(), _meta()])
        self.assertEqual(len(out), 1)
        self.assertIn("a | b", out[0])

    def test_header_fragment_is_carried_to_headerless_table_chunks(self):
        """A single header row is carried over into continuation table chunks."""
        chunks = [
            "intro text here",
            "7. Specifications\n| Name | SEM+ | SEM | SCL |",
            "7. Specifications\n |\n|---|---|---|---|",
            "7. Specifications\n| Idle | 60mA | 52mA | ? |",
            "7. Specifications\n| Max | 140mA | 130mA | ? |",
        ]
        out, _ = postprocess_chunks(chunks, [_meta("text")] + [_meta()] * 4)
        self.assertEqual(len(out), 3)
        for body in out[1:]:
            self.assertIn("| Name | SEM+ | SEM | SCL |", body)
            self.assertIn("|---|---|---|---|", body)

    def test_toc_chunks_are_tagged_and_merged(self):
        """Consecutive ToC chunks are collapsed into a single compact toc chunk."""
        toc = [
            f"Content\n| 3.{i} | Section {i} ... | {10 + i} |\n| 3.{i}1 | Other {i} ... | {11 + i} |"
            for i in range(4)
        ]
        chunks = ["Intro paragraph about the device."] + toc + ["1. General\nBody text of the real section."]
        metas = (
            [_meta("text", ["Intro"], (1,))]
            + [_meta("table", ["Content"], (3,))] * 4
            + [_meta("text", ["1. General"], (4,))]
        )
        out, out_metas = postprocess_chunks(chunks, metas)
        self.assertEqual(len(out), 3)
        self.assertEqual(out_metas[1]["content_type"], "toc")
        self.assertNotIn("...", out[1])
        self.assertIn("3.2 Section 2", out[1])

    def test_section_id_uses_closest_numbered_heading(self):
        """section_id builds page-anchored identifiers using the nearest numbered section."""
        self.assertEqual(
            section_id(28, ["5. Notes", "1.2 Separate cancel push-button for bed"]),
            "p28:1.2",
        )
        self.assertEqual(
            section_id(18, ["3 Electrical connection", "3.9 Factory setting", "Profile 2:"]),
            "p18:3.9",
        )
        self.assertEqual(section_id(1, ["Title"]), "p1")
        self.assertEqual(section_id(None, []), "")

    def test_doc_meta_from_raw_and_docling_text(self):
        """extract_doc_meta extracts doc_number, doc_version, and doc_date."""
        text1 = "89470K2.GB0_V2\n11.2020"
        meta1 = extract_doc_meta([text1])
        self.assertEqual(meta1["doc_number"], "89470K2.GB0")
        self.assertEqual(meta1["doc_version"], "V2")
        self.assertEqual(meta1["doc_date"], "11.2020")

        text2 = "Installation Instruction\n89470K2.GB0\nV2 11.2020"
        meta2 = extract_doc_meta([text2])
        self.assertEqual(meta2["doc_number"], "89470K2.GB0")
        self.assertEqual(meta2["doc_version"], "V2")
        self.assertEqual(meta2["doc_date"], "11.2020")

    def test_doc_meta_ignores_system_software_versions(self):
        """extract_doc_meta ignores software version strings (e.g. V05.xx)."""
        meta = extract_doc_meta(["needs system software V05.xx and V12.xx"])
        self.assertEqual(meta["doc_version"], "")

    def test_heading_plus_cut_separator_row_is_dropped(self):
        """Breadcrumbs followed by cut separator fragments are dropped."""
        junk1 = "3 Electrical connection\n3.8 Wiring terminals and their function:\n-------------------|--------|-------|"
        keep = "3 Electrical connection\n3.8 Wiring terminals\n| DBUS | Yes | Yes | Yes |"
        out, _ = postprocess_chunks([junk1, keep], [_meta(), _meta()])
        self.assertEqual(len(out), 1)
        self.assertIn("| DBUS |", out[0])


if __name__ == "__main__":
    unittest.main()

