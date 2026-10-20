import unittest

from core.parsers.pdf.transforms.glyphs import normalize_glyphs, strip_glyphs


class TestPdfGlyphs(unittest.TestCase):
    """Unit tests for Wingdings and symbol font glyph normalization."""

    def test_table_cell_check_and_cross_replacement(self):
        """Table cells containing only Wingdings checkmark or cross glyphs become 'Yes' or 'No'."""
        table_md = (
            "| Feature | Standard | Advanced |\n"
            "| --- | --- | --- |\n"
            "| Auto-Tune | \uf0fc | \uf0fb |\n"
            "| Diagnostics | \uf0fe | \uf0fd |\n"
        )
        normalized = normalize_glyphs(table_md)
        self.assertIn("| Yes |", normalized)
        self.assertIn("| No |", normalized)
        self.assertNotIn("\uf0fc", normalized)
        self.assertNotIn("\uf0fb", normalized)

    def test_running_text_arrow_and_bullets(self):
        """Wingdings arrows and bullets map to standard Unicode characters."""
        text = "Step 1 \uf0e8 Step 2 \uf0b7 Point A"
        normalized = normalize_glyphs(text)
        self.assertIn("→", normalized)
        self.assertIn("•", normalized)
        self.assertNotIn("\uf0e8", normalized)

    def test_strip_glyphs(self):
        """strip_glyphs removes all Private Use Area code points completely."""
        raw = "Temperature sensor \uf0fc specification \uf0b7 Honeywell"
        stripped = strip_glyphs(raw)
        self.assertEqual(stripped, "Temperature sensor  specification  Honeywell")


if __name__ == "__main__":
    unittest.main()

