import unittest

from core.parsers.pdf.transforms.coverage import check_page, check_page_coverage


class TestPdfCoverage(unittest.TestCase):
    """Unit tests for text coverage recovery and line-by-line fuzzy repair."""

    def test_recovered_text_appended_when_missing_from_markdown(self):
        """Important raw text lines missing from extracted markdown are recovered."""
        md = "# Section 1\n\nThis is standard extracted markdown text."
        raw_text = (
            "This is standard extracted markdown text.\n"
            "CRITICAL WARNING: Ensure device is grounded before maintenance."
        )

        recovered_md = check_page_coverage(md, raw_text)
        self.assertIn("[Recovered text]", recovered_md)
        self.assertIn(
            "CRITICAL WARNING: Ensure device is grounded before maintenance.",
            recovered_md,
        )

    def test_no_recovered_text_when_already_present(self):
        """When markdown already contains all raw lines, no recovered text block is added."""
        md = "Line One content is here.\n\nLine Two content is here."
        raw_text = "Line One content is here.\nLine Two content is here."

        result_md = check_page_coverage(md, raw_text)
        self.assertNotIn("[Recovered text]", result_md)

    def test_coverage_restores_dropped_bold_word(self):
        """check_page repairs near-matches in place without appending [Recovered text]."""
        md = "Features:\n- plug out call\n- presence 2\n- I/O Port"
        raw = "Features:\n- plug out call\n- No presence 2\n- I/O Port"
        out = check_page(md, raw, set())
        self.assertIn("- No presence 2", out)
        self.assertNotIn("[Recovered text]", out)

    def test_coverage_never_rewrites_table_rows(self):
        """Markdown table rows are protected and never rewritten by fuzzy repair."""
        md = "| Fire class | V-0 |\n|---|---|"
        raw = "Fire protection class\nV-O"
        out = check_page(md, raw, set())
        self.assertTrue(out.startswith("| Fire class | V-0 |"))

    def test_coverage_skips_toc_page(self):
        """Dense Table of Contents pages are detected and skipped without junk recovery."""
        raw = "\n".join(
            f"{i}.{j} Some section title ........ {i * 3 + j}"
            for i in range(1, 5)
            for j in range(1, 4)
        )
        self.assertEqual(check_page("Content", raw, set()), "Content")

    def test_coverage_running_lines_deduplication(self):
        """Boilerplate lines passed in running_lines are ignored and not recovered."""
        running = {"Header Honeywell 2026", "Footer Page 1"}
        md = "Body text of page"
        raw = "Header Honeywell 2026\nBody text of page\nFooter Page 1"

        out = check_page(md, raw, running)
        self.assertNotIn("[Recovered text]", out)
        self.assertNotIn("Header Honeywell 2026", out)


if __name__ == "__main__":
    unittest.main()
