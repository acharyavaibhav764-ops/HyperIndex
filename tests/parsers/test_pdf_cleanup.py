import unittest

from core.parsers.pdf.transforms.cleanup import (
    clean_markdown_page,
    strip_running_lines,
    strip_vlm_tokens,
)


class TestPdfCleanup(unittest.TestCase):
    """Unit tests for token scrubbing and boilerplate line cleanup."""

    def test_strip_vlm_tokens(self):
        """strip_vlm_tokens removes leaked generation tokens such as <end_of_utteranc>."""
        raw = "Temperature sensor overview.<end_of_utteranc>"
        cleaned = strip_vlm_tokens(raw)
        self.assertEqual(cleaned, "Temperature sensor overview.")

        raw_incomplete = "Sensor circuit diagram.<end_of_"
        cleaned_incomplete = strip_vlm_tokens(raw_incomplete)
        self.assertEqual(cleaned_incomplete, "Sensor circuit diagram.")

    def test_strip_running_lines_headers_and_footers(self):
        """strip_running_lines detects and removes recurring page headers/footers."""
        pages = [
            "Honeywell Confidential Header\n\nPage 1 Content\n\nPage 1 of 3",
            "Honeywell Confidential Header\n\nPage 2 Content\n\nPage 2 of 3",
            "Honeywell Confidential Header\n\nPage 3 Content\n\nPage 3 of 3",
        ]
        cleaned = strip_running_lines(pages)
        for page in cleaned:
            self.assertNotIn("Honeywell Confidential Header", page)
        self.assertIn("Page 1 Content", cleaned[0])
        self.assertIn("Page 2 Content", cleaned[1])
        self.assertIn("Page 3 Content", cleaned[2])

    def test_clean_markdown_page(self):
        """clean_markdown_page collapses excessive consecutive newlines and strips tokens."""
        raw = "Paragraph 1\n\n\n\n\nParagraph 2<unused0>"
        cleaned = clean_markdown_page(raw)
        self.assertEqual(cleaned, "Paragraph 1\n\nParagraph 2")


if __name__ == "__main__":
    unittest.main()

