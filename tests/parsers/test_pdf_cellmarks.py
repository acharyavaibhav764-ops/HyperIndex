import unittest
from unittest.mock import MagicMock

from docling_core.types.doc import BoundingBox, DoclingDocument

from core.parsers.pdf.transforms.cellmarks import _inside, inject_marks, scan_legend


class TestPdfCellmarks(unittest.TestCase):
    """Unit tests for availability marks and legend discovery in tables."""

    def test_scan_legend_detection(self):
        """scan_legend correctly identifies availability legend definitions."""
        page_texts = [
            "Honeywell Model 500 Features",
            "Notes: [check] = available, [dot] = unavailable",
        ]
        legend = scan_legend(page_texts)
        self.assertIsNotNone(legend)
        self.assertEqual(legend.get("tick"), "Yes")
        self.assertEqual(legend.get("dots"), "No")

    def test_inside_bounding_box_collision(self):
        """_inside correctly identifies image inside cell boundaries."""
        # Cell: (100, 100, 200, 200)
        # Image: (120, 120, 140, 140) -> inside
        self.assertTrue(_inside(120, 120, 140, 140, 100, 100, 200, 200))

        # Image far away: (300, 300, 320, 320) -> outside
        self.assertFalse(_inside(300, 300, 320, 320, 100, 100, 200, 200))


if __name__ == "__main__":
    unittest.main()

