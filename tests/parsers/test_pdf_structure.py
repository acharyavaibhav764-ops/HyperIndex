import unittest
from collections import Counter
from docling_core.types.doc import (
    BoundingBox,
    DocItemLabel,
    DoclingDocument,
    ProvenanceItem,
    TableData,
)

from core.parsers.pdf.transforms.structure import (
    blacklist_headings,
    bind_captions,
    dedupe_echoes,
    relevel_headings,
    repair_headings,
    repair_pdf_headings,
    repair_pdf_structure,
    tag_toc_structures,
)


def _prov(page_no: int) -> list[ProvenanceItem]:
    return [ProvenanceItem(page_no=page_no, bbox=BoundingBox(l=0, t=0, r=0, b=0), charspan=(0, 0))]


class TestPdfStructure(unittest.TestCase):
    """Unit tests for heading freeze fix, section level normalization, and AST structure repairs."""

    def test_heading_freeze_repaired_on_later_pages(self):
        """TitleItem on page > 1 is converted to SectionHeaderItem, fixing the heading freeze."""
        doc = DoclingDocument(name="test_doc")

        # Page 1 main document title
        t1 = doc.add_text(label=DocItemLabel.TITLE, text="Honeywell Manual Main Title")
        t1.prov = _prov(1)

        # Page 2 subsection erroneously tagged as TitleItem by per-page font heuristic
        t2 = doc.add_text(label=DocItemLabel.TITLE, text="3.2 Wiring Instructions")
        t2.prov = _prov(2)

        repair_headings(doc)

        # Page 1 stays TitleItem
        self.assertEqual(doc.texts[0].label, DocItemLabel.TITLE)

        # Page 2 is converted to SectionHeaderItem with level 2 (from "3.2")
        self.assertEqual(doc.texts[1].label, DocItemLabel.SECTION_HEADER)
        self.assertEqual(getattr(doc.texts[1], "level", None), 2)

    def test_pseudo_heading_demotion(self):
        """Action buttons erroneously labeled as headings are demoted to plain Text."""
        doc = DoclingDocument(name="test_doc")
        btn = doc.add_text(label=DocItemLabel.SECTION_HEADER, text="Click here to order parts")
        btn.prov = _prov(1)

        repair_headings(doc)
        self.assertEqual(doc.texts[0].label, DocItemLabel.TEXT)

    def test_tag_toc_structures(self):
        """Table of Contents lines with dot leaders are tagged with [TOC]."""
        doc = DoclingDocument(name="test_doc")
        toc_line = doc.add_text(label=DocItemLabel.PARAGRAPH, text="Safety Information ........ 12")
        toc_line.prov = _prov(1)

        tag_toc_structures(doc)
        self.assertTrue(doc.texts[0].text.startswith("[TOC]"))

    def test_cross_page_boilerplate_demotion(self):
        """Verbatim headers repeating on >= 3 distinct pages are demoted to PARAGRAPH."""
        doc = DoclingDocument(name="test_doc")

        h1 = doc.add_text(label=DocItemLabel.SECTION_HEADER, text="Honeywell Confidential Manual")
        h1.prov = _prov(1)

        h2 = doc.add_text(label=DocItemLabel.SECTION_HEADER, text="Honeywell Confidential Manual")
        h2.prov = _prov(2)

        h3 = doc.add_text(label=DocItemLabel.SECTION_HEADER, text="Honeywell Confidential Manual")
        h3.prov = _prov(3)

        repair_pdf_headings(doc, min_page_repeats=3)

        for item in doc.texts:
            self.assertEqual(item.label, DocItemLabel.PARAGRAPH)

    def test_misplaced_number_relocation(self):
        """Headings with embedded section numbers are relocated to the front with level."""
        doc = DoclingDocument(name="test_doc")
        h = doc.add_text(label=DocItemLabel.SECTION_HEADER, text="Greasing 6.4 the Groove")
        h.prov = _prov(2)

        repair_pdf_headings(doc)
        self.assertEqual(doc.texts[0].text, "6.4 Greasing the Groove")
        self.assertEqual(getattr(doc.texts[0], "level", None), 2)

    def test_bind_captions_to_tables(self):
        """Floating labels like 'Day 2' directly preceding a table are bound as table captions."""
        doc = DoclingDocument(name="test_doc")

        caption_label = doc.add_text(label=DocItemLabel.TEXT, text="Day 2")
        caption_label.prov = _prov(1)

        table = doc.add_table(data=TableData(num_rows=2, num_cols=2, table_cells=[]))
        table.prov = _prov(1)

        bind_captions(doc)
        self.assertTrue(hasattr(table, "caption_text"))
        self.assertEqual(table.caption_text(doc=doc), "Day 2")

    def test_dedupe_echoes_blanks_duplicate(self):
        """Body paragraphs that only repeat an adjacent heading are blanked."""
        doc = DoclingDocument(name="test_doc")

        h = doc.add_text(label=DocItemLabel.SECTION_HEADER, text="Safety Warnings")
        h.prov = _prov(1)

        p = doc.add_text(label=DocItemLabel.PARAGRAPH, text="Safety Warnings")
        p.prov = _prov(1)

        dedupe_echoes(doc)
        self.assertEqual(doc.texts[1].text, "")

    def test_blacklist_template_headings(self):
        """Template headings like Titelseite and GB Version are blanked."""
        doc = DoclingDocument(name="test_doc")

        h1 = doc.add_text(label=DocItemLabel.SECTION_HEADER, text="Titelseite")
        h1.prov = _prov(1)

        h2 = doc.add_text(label=DocItemLabel.SECTION_HEADER, text="GB Version")
        h2.prov = _prov(1)

        blacklist_headings(doc)
        self.assertEqual(doc.texts[0].text, "")
        self.assertEqual(doc.texts[1].text, "")


if __name__ == "__main__":
    unittest.main()
