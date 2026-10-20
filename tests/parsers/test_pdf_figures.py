import unittest
from docling_core.types.doc import DoclingDocument, PictureDescriptionData

from core.parsers.pdf.transforms.figures import inject_figure_cards


class TestPdfFigures(unittest.TestCase):
    """Unit tests for figure card processing and caption sanitization."""

    def test_repetitive_caption_suppression(self):
        """Repetitive hallucinated captions are suppressed to empty string."""
        doc = DoclingDocument(name="figure_doc")
        pic = doc.add_picture(caption=None)
        
        # Attach repetitive hallucinated description with required provenance field
        pic.annotations.append(
            PictureDescriptionData(
                provenance="test_vlm",
                text="sensor diagram sensor diagram sensor diagram sensor diagram"
            )
        )

        inject_figure_cards(doc)
        # Verify text was cleared or sanitized
        self.assertEqual(pic.annotations[0].text, "")


if __name__ == "__main__":
    unittest.main()
