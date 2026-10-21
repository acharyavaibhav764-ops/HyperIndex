"""
Automated chunk-quality and golden criteria verification suite ported from verify_v5_9.py.
Validates chunk integrity, metadata compliance, absence of mojibake, and clean retrieval filtering.
"""
import re
import unittest


def check_no_junk_chunks(chunks: list[str]) -> list[str]:
    """No chunk should be separator-only or pure dots."""
    junk_re = re.compile(r"^[\s|:.-]*$")
    dots_re = re.compile(r"\.{5,}")
    fails = []
    for i, c in enumerate(chunks):
        stripped = c.strip()
        if junk_re.match(stripped):
            fails.append(f"chunk #{i}: separator-only junk")
        if dots_re.search(stripped):
            fails.append(f"chunk #{i}: contains dot-leader run: {stripped[:60]!r}")
    return fails


def check_toc_not_indexed(metas: list[dict]) -> list[str]:
    """content_type=toc chunks must not appear in search results."""
    fails = []
    for i, m in enumerate(metas):
        if m.get("content_type") == "toc":
            fails.append(f"chunk #{i}: content_type=toc present in search results")
    return fails


def check_table_headers(chunks: list[str]) -> list[str]:
    """Every chunk with a pipe-table body should have a separator row -> header."""
    fails = []
    for i, c in enumerate(chunks):
        lines = c.splitlines()
        has_body = any(l.strip().startswith("|") and "---" not in l for l in lines[2:])
        has_sep = any(re.match(r"^\|[-:| ]+\|\s*$", l) for l in lines)
        if has_body and not has_sep:
            fails.append(f"chunk #{i}: table body without header/separator")
    return fails


def check_metadata_completeness(metas: list[dict]) -> list[str]:
    """heading_path, content_type, page_numbers, section_id must be present and str."""
    required_str = ("heading_path", "content_type", "page_numbers", "section_id")
    fails = []
    for i, m in enumerate(metas):
        for key in required_str:
            val = m.get(key)
            if val is None:
                fails.append(f"chunk #{i}: missing metadata key {key!r}")
            elif not isinstance(val, str):
                fails.append(f"chunk #{i}: {key!r} is {type(val).__name__}, expected str")
    return fails


def check_encoding(chunks: list[str]) -> list[str]:
    """No mojibake characters."""
    mojibake_re = re.compile("[\u251C\u252C\u0393\u2229\u00C3\u00C2]")
    fails = []
    for i, c in enumerate(chunks):
        if mojibake_re.search(c):
            fails.append(f"chunk #{i}: contains mojibake: {c[:80]!r}")
    return fails


def check_no_classifier_labels(chunks: list[str]) -> list[str]:
    """class_hint labels must not leak into chunk text."""
    hint_re = re.compile(
        r"\b(?:Bar chart|Pie chart|Screenshot from manual|Photograph|"
        r"Wiring diagram|Table)\b",
        re.I,
    )
    fails = []
    for i, c in enumerate(chunks):
        if hint_re.search(c):
            fails.append(f"chunk #{i}: classifier label in text: {c[:80]!r}")
    return fails


class TestPdfGoldenQuality(unittest.TestCase):
    """Programmatic quality assertions checking post-processed chunk corpora."""

    def test_junk_chunk_detector_flags_empty_separators_and_dots(self):
        good = ["3. Installation\nMounting the terminal securely to wall."]
        bad = ["|---|---|---|", "Section 1 ........ 15"]
        self.assertEqual(len(check_no_junk_chunks(good)), 0)
        self.assertEqual(len(check_no_junk_chunks(bad)), 2)

    def test_toc_filter_verification(self):
        good_metas = [{"content_type": "text"}, {"content_type": "table"}]
        bad_metas = [{"content_type": "text"}, {"content_type": "toc"}]
        self.assertEqual(len(check_toc_not_indexed(good_metas)), 0)
        self.assertEqual(len(check_toc_not_indexed(bad_metas)), 1)

    def test_table_headers_verification(self):
        valid_table = [
            "3.8 Terminals\n| Pin | Function |\n|---|---|\n| 1 | DBUS |",
        ]
        invalid_table = [
            "3.8 Terminals\n| 1 | DBUS |\n| 2 | GND |",
        ]
        self.assertEqual(len(check_table_headers(valid_table)), 0)
        self.assertEqual(len(check_table_headers(invalid_table)), 1)

    def test_metadata_completeness_and_scalar_validation(self):
        valid_meta = [
            {
                "heading_path": "3 Installation > 3.8 Terminals",
                "content_type": "table",
                "page_numbers": "18,19",
                "section_id": "p18:3.8",
            }
        ]
        invalid_meta = [
            {
                "heading_path": ["3 Installation", "3.8 Terminals"],  # list instead of str
                "content_type": "table",
                "page_numbers": [18, 19],  # list instead of str
                # missing section_id
            }
        ]
        self.assertEqual(len(check_metadata_completeness(valid_meta)), 0)
        self.assertGreater(len(check_metadata_completeness(invalid_meta)), 0)

    def test_encoding_mojibake_check(self):
        clean = ["Clean technical text with 0.8 mm terminal wire diameter."]
        mojibake = ["Broken encoding with \u251c and \u00c3 symbols."]
        self.assertEqual(len(check_encoding(clean)), 0)
        self.assertEqual(len(check_encoding(mojibake)), 1)

    def test_no_classifier_labels_leakage(self):
        clean = ["Figure (page 3) | Section: 3 Installation | Numbers: 79CM307Z1"]
        leaked = ["Screenshot from manual showing device front panel"]
        self.assertEqual(len(check_no_classifier_labels(clean)), 0)
        self.assertEqual(len(check_no_classifier_labels(leaked)), 1)


if __name__ == "__main__":
    unittest.main()

