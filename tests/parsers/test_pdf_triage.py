import unittest
import fitz  # PyMuPDF

from core.parsers.pdf.triage import PageRoute, PageTriager


class TestPdfTriage(unittest.TestCase):
    """Unit tests for PDF page triage classification."""

    def setUp(self):
        self.triager = PageTriager(min_text_chars_for_text_route=100)

    def test_triage_text_page(self):
        """A text-heavy page with no tables or images routes to TEXT."""
        doc = fitz.open()
        page = doc.new_page()
        # Add paragraphs of text exceeding 100 characters
        page.insert_text(
            (72, 72),
            "This is a long technical text documentation paragraph about Honeywell thermostat controllers. "
            "It describes temperature regulation, communication protocols, sensor diagnostics, and hardware specs."
        )

        routes = self.triager.triage_page(page)
        self.assertEqual(routes, [PageRoute.TEXT])
        doc.close()

    def test_triage_image_page(self):
        """A page with an image and sparse text routes to IMAGE."""
        doc = fitz.open()
        page = doc.new_page()
        # Insert a tiny dummy pixmap image
        pix = fitz.Pixmap(fitz.csRGB, (0, 0, 50, 50), 1)
        page.insert_image(fitz.Rect(72, 72, 172, 172), pixmap=pix)
        page.insert_text((72, 200), "Figure 1: Sensor")  # short text < 100 chars

        routes = self.triager.triage_page(page)
        self.assertIn(PageRoute.IMAGE, routes)
        doc.close()


if __name__ == "__main__":
    unittest.main()

