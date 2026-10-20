import unittest

from core.parsers.pdf.transforms.coverage import check_page_coverage


class TestPdfCoverage(unittest.TestCase):
    """Unit tests for text coverage recovery."""

    def test_recovered_text_appended_when_missing_from_markdown(self):
        """Important raw text lines missing from extracted markdown are recovered."""
        md = "# Section 1\n\nThis is standard extracted markdown text."
        raw_text = (
            "This is standard extracted markdown text.\n"
            "CRITICAL WARNING: Ensure device is grounded before maintenance."
        )

        recovered_md = check_page_coverage(md, raw_text)
        self.assertIn("[Recovered text]", recovered_md)
        self.assertIn("CRITICAL WARNING: Ensure device is grounded before maintenance.", recovered_md)

    def test_no_recovered_text_when_already_present(self):
        """When markdown already contains all raw lines, no recovered text block is added."""
        md = "Line One content is here.\n\nLine Two content is here."
        raw_text = "Line One content is here.\nLine Two content is here."

        result_md = check_page_coverage(md, raw_text)
        self.assertNotIn("[Recovered text]", result_md)


if __name__ == "__main__":
    unittest.main()

