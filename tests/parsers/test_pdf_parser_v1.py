import unittest
import fitz  # PyMuPDF
from docling_core.types.doc import DoclingDocument

from core.parsers import ParserRouter, PdfParser


class TestPdfParserV1(unittest.TestCase):
    """Unit tests for PDF v1.0 Foundation and Router Registration."""

    def setUp(self):
        self.parser = PdfParser()
        self.router = ParserRouter()

    def test_can_handle_pdf(self):
        """PdfParser supports .pdf in any casing."""
        self.assertTrue(self.parser.can_handle(".pdf"))
        self.assertTrue(self.parser.can_handle(".PDF"))
        self.assertTrue(self.parser.can_handle(".Pdf"))

    def test_can_handle_non_pdf(self):
        """PdfParser rejects non-pdf file extensions."""
        self.assertFalse(self.parser.can_handle(".docx"))
        self.assertFalse(self.parser.can_handle(".txt"))
        self.assertFalse(self.parser.can_handle(".png"))
        self.assertFalse(self.parser.can_handle(".doc"))

    def test_router_registration(self):
        """ParserRouter returns an instance of PdfParser for pdf filenames/extensions."""
        parser = self.router.get_parser("document.pdf")
        self.assertIsInstance(parser, PdfParser)

        parser_caps = self.router.get_parser("DOCUMENT.PDF")
        self.assertIsInstance(parser_caps, PdfParser)

    def test_router_supported_extensions(self):
        """ParserRouter lists .pdf in supported extensions."""
        supported = self.router._supported_extensions()
        self.assertIn(".pdf", supported)

    def test_parse_minimal_pdf(self):
        """PdfParser parses a minimal valid in-memory PDF into a DoclingDocument."""
        # Create an in-memory 1-page PDF using PyMuPDF
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Honeywell Technical Document Sample Text")
        pdf_bytes = doc.tobytes()
        doc.close()

        # Parse via PdfParser
        parsed_doc = self.parser.parse(pdf_bytes, "sample.pdf")
        self.assertIsInstance(parsed_doc, DoclingDocument)

        # Check that extracted text contains expected string
        texts = [item.text for item in parsed_doc.texts if item.text]
        combined_text = " ".join(texts)
        self.assertIn("Honeywell Technical Document Sample Text", combined_text)


if __name__ == "__main__":
    unittest.main()

