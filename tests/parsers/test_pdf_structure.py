import unittest
from docling_core.types.doc import (
    BoundingBox,
    DocItemLabel,
    DoclingDocument,
    ProvenanceItem,
)

from core.parsers.pdf.transforms.structure import repair_headings, tag_toc_structures


class TestPdfStructure(unittest.TestCase):
    """Unit tests for heading freeze fix, section level normalization, and ToC detection."""

    def test_heading_freeze_repaired_on_later_pages(self):
        """TitleItem on page > 1 is converted to SectionHeaderItem, fixing the heading freeze."""
        doc = DoclingDocument(name="test_doc")

        prov_p1 = ProvenanceItem(page_no=1, bbox=BoundingBox(l=0, t=0, r=0, b=0), charspan=(0, 0))
        prov_p2 = ProvenanceItem(page_no=2, bbox=BoundingBox(l=0, t=0, r=0, b=0), charspan=(0, 0))

        # Page 1 main document title
        t1 = doc.add_text(label=DocItemLabel.TITLE, text="Honeywell Manual Main Title")
        t1.prov = [prov_p1]

        # Page 2 subsection erroneously tagged as TitleItem by per-page font heuristic
        t2 = doc.add_text(label=DocItemLabel.TITLE, text="3.2 Wiring Instructions")
        t2.prov = [prov_p2]

        repair_headings(doc)

        # Page 1 stays TitleItem
        self.assertEqual(doc.texts[0].label, DocItemLabel.TITLE)

        # Page 2 is converted to SectionHeaderItem with level 2 (from "3.2")
        self.assertEqual(doc.texts[1].label, DocItemLabel.SECTION_HEADER)
        self.assertEqual(getattr(doc.texts[1], "level", None), 2)

    def test_pseudo_heading_demotion(self):
        """Action buttons erroneously labeled as headings are demoted to plain Text."""
        doc = DoclingDocument(name="test_doc")
        prov = ProvenanceItem(page_no=1, bbox=BoundingBox(l=0, t=0, r=0, b=0), charspan=(0, 0))

        btn = doc.add_text(label=DocItemLabel.SECTION_HEADER, text="Click here to order parts")
        btn.prov = [prov]

        repair_headings(doc)
        self.assertEqual(doc.texts[0].label, DocItemLabel.TEXT)

    def test_tag_toc_structures(self):
        """Table of Contents lines with dot leaders are tagged with [TOC]."""
        doc = DoclingDocument(name="test_doc")
        prov = ProvenanceItem(page_no=1, bbox=BoundingBox(l=0, t=0, r=0, b=0), charspan=(0, 0))

        toc_line = doc.add_text(label=DocItemLabel.PARAGRAPH, text="Safety Information ........ 12")
        toc_line.prov = [prov]

        tag_toc_structures(doc)
        self.assertTrue(doc.texts[0].text.startswith("[TOC]"))


if __name__ == "__main__":
    unittest.main()
