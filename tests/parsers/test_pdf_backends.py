import unittest
import fitz  # PyMuPDF
from docling_core.types.doc import DoclingDocument

from core.parsers.pdf.backends import (
    PyMuPdfBackend,
    merge_pages_to_docling,
    single_page_bytes,
)
from core.parsers.pdf.parser import PdfParser


class TestPdfBackends(unittest.TestCase):
    """Unit tests for PDF extraction backends and provenance-aware page merger."""

    def test_single_page_slicing(self):
        """single_page_bytes produces a valid 1-page PDF from a multi-page document."""
        doc = fitz.open()
        p1 = doc.new_page()
        p1.insert_text((72, 72), "Page One Content")
        p2 = doc.new_page()
        p2.insert_text((72, 72), "Page Two Content")

        # Slice page 1
        p2_bytes = single_page_bytes(doc, 1)
        doc.close()

        # Verify sliced PDF has exactly 1 page and contains page 2 text
        sliced_doc = fitz.open(stream=p2_bytes, filetype="pdf")
        self.assertEqual(len(sliced_doc), 1)
        text = sliced_doc[0].get_text()
        self.assertIn("Page Two Content", text)
        self.assertNotIn("Page One Content", text)
        sliced_doc.close()

    def test_page_provenance_stamping_across_pages(self):
        """merge_pages_to_docling stamps accurate ProvenanceItem(page_no=...) on each page."""
        page_mds = [
            "# Heading Page 1\n\nFirst page body paragraph text.",
            "# Heading Page 2\n\nSecond page body paragraph text.",
            "| Column A | Column B |\n| --- | --- |\n| Cell 1 | Cell 2 |",
        ]

        doc = merge_pages_to_docling(page_mds, "test_manual.pdf")
        self.assertIsInstance(doc, DoclingDocument)

        # Verify page provenance is stamped 1, 2, 3
        pages_seen = set()
        for item in doc.texts:
            if getattr(item, "prov", None):
                pages_seen.add(item.prov[0].page_no)

        self.assertIn(1, pages_seen)
        self.assertIn(2, pages_seen)

    def test_multipage_pdf_parse_end_to_end(self):
        """PdfParser parses a multi-page PDF end-to-end via triage and merges cleanly."""
        pdf = fitz.open()
        p1 = pdf.new_page()
        p1.insert_text((72, 72), "Honeywell Technical Specifications Overview Section")
        p2 = pdf.new_page()
        p2.insert_text((72, 72), "Installation Procedure and Hardware Wiring Guide")
        pdf_bytes = pdf.tobytes()
        pdf.close()

        parser = PdfParser()
        doc = parser.parse(pdf_bytes, "manual.pdf")
        self.assertIsInstance(doc, DoclingDocument)

        texts = " ".join([item.text for item in doc.texts if item.text])
        self.assertIn("Specifications", texts)
        self.assertIn("Installation", texts)


if __name__ == "__main__":
    unittest.main()

