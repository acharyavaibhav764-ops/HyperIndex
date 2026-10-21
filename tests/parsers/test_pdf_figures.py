import unittest
from types import SimpleNamespace

import fitz
from docling_core.types.doc import DoclingDocument, PictureDescriptionData

from core.parsers.pdf.transforms.figures import inject_figure_cards, process_pictures


class TestPdfFigures(unittest.TestCase):
    """Unit tests for figure card processing, caption sanitization, and diagram text extraction."""

    def test_repetitive_caption_suppression(self):
        """Repetitive hallucinated captions are suppressed to empty string."""
        doc = DoclingDocument(name="figure_doc")
        pic = doc.add_picture(caption=None)

        # Attach repetitive hallucinated description
        pic.annotations.append(
            PictureDescriptionData(
                provenance="test_vlm",
                text="sensor diagram sensor diagram sensor diagram sensor diagram",
            )
        )

        inject_figure_cards(doc)
        # Verify text was cleared
        self.assertEqual(pic.annotations[0].text, "")

    def test_process_pictures_extracts_labels_and_numbers(self):
        """process_pictures synthesizes figure cards containing diagram callouts and spec numbers."""
        doc = fitz.open()
        page = doc.new_page(width=600, height=800)

        # Draw an image placeholder (diagram)
        pm = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 150, 150))
        pm.set_rect(pm.irect, (120, 120, 120))
        diag_rect = fitz.Rect(50, 100, 250, 300)
        page.insert_image(diag_rect, pixmap=pm)

        # Add callout labels inside diagram
        page.insert_text((60, 120), "1 Terminal connector")
        page.insert_text((60, 150), "2 Status LED")
        page.insert_text((60, 180), "Part 79CM307Z1")

        mock_pic = SimpleNamespace(
            bbox=SimpleNamespace(l=50, t=100, r=250, b=300),
            image=None,
            caption_text=lambda doc=None: "",
        )
        mock_doc = SimpleNamespace(pictures=[mock_pic], tables=[])

        cards = process_pictures(
            mock_doc,
            page,
            heading_path=["3 Installation", "3.2 Mounting"],
            page_no=3,
            mode="labels_only",
        )

        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual(card["figure_id"], "fig_p3_0")
        self.assertIn("Section: 3 Installation > 3.2 Mounting", card["text"])
        self.assertIn("79CM307Z1", card["text"])
        self.assertIn("Terminal", card["text"])

    def test_table_rects_exclude_embedded_icons(self):
        """Icons inside detected tables are excluded from standalone figure card processing."""
        doc = fitz.open()
        page = doc.new_page(width=600, height=800)

        # Insert image inside table boundary
        pm = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40))
        pm.set_rect(pm.irect, (30, 150, 40))
        icon_rect = fitz.Rect(100, 100, 140, 140)
        page.insert_image(icon_rect, pixmap=pm)

        mock_pic = SimpleNamespace(
            bbox=SimpleNamespace(l=100, t=100, r=140, b=140),
            image=None,
            caption_text=lambda doc=None: "",
        )
        table_item = SimpleNamespace(
            bbox=SimpleNamespace(l=90, t=90, r=300, b=300)
        )
        mock_doc = SimpleNamespace(pictures=[mock_pic], tables=[table_item])

        cards = process_pictures(
            mock_doc,
            page,
            heading_path=[],
            page_no=1,
            mode="labels_only",
        )

        # Icon inside table should be filtered out
        self.assertEqual(len(cards), 0)


if __name__ == "__main__":
    unittest.main()
