"""
tests/parsing_arch/v5_2/test_heading_integrity.py

v5.2 regression tests for Fix 2: _repair_pdf_headings() post-merge pass.

Covers:
  5. test_repeated_footer_demoted_from_headings
  6. test_numbered_paragraph_promoted_to_heading
  7. test_heading_path_advances_across_pages_end_to_end
  8. test_boilerplate_threshold_respects_config

Mocking strategy: construct DoclingDocument objects directly with docling-core
types — no real PDF or converter I/O needed.
"""
import pytest
from unittest.mock import MagicMock, patch

from docling_core.types.doc import (
    DoclingDocument,
    DocItemLabel,
    ProvenanceItem,
    BoundingBox,
)

from parsers.pdf_router import _repair_pdf_headings, PdfPageRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_prov(page_no: int) -> list[ProvenanceItem]:
    return [ProvenanceItem(
        page_no=page_no,
        bbox=BoundingBox(l=0, t=0, r=0, b=0),
        charspan=(0, 10),
    )]


def _add_text(doc: DoclingDocument, text: str, label: DocItemLabel, page_no: int):
    """Append a text item via doc.add_text() (which sets self_ref and orig automatically)
    and stamp its provenance with the given page_no."""
    item = doc.add_text(label=label, text=text)
    item.prov = _make_prov(page_no)
    return item


def _add_heading(doc: DoclingDocument, text: str, page_no: int):
    item = doc.add_text(label=DocItemLabel.SECTION_HEADER, text=text)
    item.prov = _make_prov(page_no)
    return item



# ---------------------------------------------------------------------------
# Test 5 — boilerplate demotion
# ---------------------------------------------------------------------------

class TestBoilerplateDemotion:
    def test_repeated_footer_demoted_from_headings(self):
        """A SECTION_HEADER that appears on >= 3 pages (default threshold) must be
        demoted to PARAGRAPH by _repair_pdf_headings().
        """
        doc = DoclingDocument(name="test")
        footer_text = "Calisthenics Family | Calisthenics Training Guide"

        # Footer appears on 5 pages as a heading (simulating the bug)
        for pg in range(1, 6):
            _add_heading(doc, footer_text, pg)

        # Real distinct headings on some pages
        _add_heading(doc, "5.5 Mobility", 3)
        _add_heading(doc, "7.1 Strength", 7)

        _repair_pdf_headings(doc, min_page_repeats=3)

        for item in doc.texts:
            if item.text == footer_text:
                assert item.label == DocItemLabel.PARAGRAPH, (
                    f"Footer on page {item.prov[0].page_no} must be demoted to PARAGRAPH"
                )

    def test_real_headings_not_demoted_when_unique(self):
        """Headings appearing only once should NOT be demoted."""
        doc = DoclingDocument(name="test")
        _add_heading(doc, "5.5 Mobility", 3)
        _add_heading(doc, "7.1 Strength", 7)

        _repair_pdf_headings(doc, min_page_repeats=3)

        labels = {item.text: item.label for item in doc.texts}
        assert labels["5.5 Mobility"] == DocItemLabel.SECTION_HEADER
        assert labels["7.1 Strength"] == DocItemLabel.SECTION_HEADER


# ---------------------------------------------------------------------------
# Test 6 — numbered heading promotion
# ---------------------------------------------------------------------------

class TestNumberedHeadingPromotion:
    def test_numbered_paragraph_promoted_to_heading(self):
        """A PARAGRAPH reading '7.6 Specificity' (matching N.N <word>) must be
        promoted to SECTION_HEADER by _repair_pdf_headings().
        """
        doc = DoclingDocument(name="test")
        _add_text(doc, "7.6 Specificity", DocItemLabel.PARAGRAPH, page_no=10)

        _repair_pdf_headings(doc, min_page_repeats=3)

        assert doc.texts[0].label == DocItemLabel.SECTION_HEADER

    def test_deep_numbered_heading_promoted(self):
        """N.N.N.N pattern must also be promoted."""
        doc = DoclingDocument(name="test")
        _add_text(doc, "9.4.2 Proteins and Amino Acids", DocItemLabel.PARAGRAPH, page_no=22)

        _repair_pdf_headings(doc, min_page_repeats=3)

        assert doc.texts[0].label == DocItemLabel.SECTION_HEADER

    def test_long_paragraph_not_promoted(self):
        """Paragraphs >= 100 chars must not be promoted even if they start with a number."""
        doc = DoclingDocument(name="test")
        long_text = "1.1 " + "x" * 100  # >= 100 chars after the pattern
        _add_text(doc, long_text, DocItemLabel.PARAGRAPH, page_no=5)

        _repair_pdf_headings(doc, min_page_repeats=3)

        assert doc.texts[0].label == DocItemLabel.PARAGRAPH

    def test_plain_paragraph_not_promoted(self):
        """A paragraph that does not match N.N <word> stays PARAGRAPH."""
        doc = DoclingDocument(name="test")
        _add_text(doc, "This is a regular paragraph.", DocItemLabel.PARAGRAPH, page_no=1)

        _repair_pdf_headings(doc, min_page_repeats=3)

        assert doc.texts[0].label == DocItemLabel.PARAGRAPH


# ---------------------------------------------------------------------------
# Test 7 — heading path advances end-to-end across pages
# ---------------------------------------------------------------------------

class TestHeadingPathAdvances:
    def test_heading_path_advances_across_pages_end_to_end(self):
        """After _repair_pdf_headings(), no SECTION_HEADER/TITLE should appear
        for a boilerplate string that was promoting the wrong heading context.

        Simulates the freeze at '5.5 Mobility' described in the real run:
        the footer keeps appearing as SECTION_HEADER, resetting the heading
        path back to the footer text after each real section advances.
        """
        doc = DoclingDocument(name="test")
        footer = "Honeywell Tech Manual"

        # Pages 1-10: footer appears as heading on each page (bug: misclassified)
        for pg in range(1, 11):
            _add_heading(doc, footer, pg)

        # Real numbered headings on some pages
        _add_text(doc, "5.5 Mobility", DocItemLabel.PARAGRAPH, page_no=3)
        _add_text(doc, "6.1 Coordination", DocItemLabel.PARAGRAPH, page_no=6)
        _add_text(doc, "7.3 Core Strength", DocItemLabel.PARAGRAPH, page_no=9)

        _repair_pdf_headings(doc, min_page_repeats=3)

        heading_labels = {
            item.text: item.label
            for item in doc.texts
        }
        # Footer must be demoted everywhere
        assert heading_labels[footer] == DocItemLabel.PARAGRAPH

        # Numbered paragraphs must be promoted
        assert heading_labels["5.5 Mobility"] == DocItemLabel.SECTION_HEADER
        assert heading_labels["6.1 Coordination"] == DocItemLabel.SECTION_HEADER
        assert heading_labels["7.3 Core Strength"] == DocItemLabel.SECTION_HEADER


# ---------------------------------------------------------------------------
# Test 8 — boilerplate threshold respects config
# ---------------------------------------------------------------------------

class TestBoilerplateThresholdConfig:
    def test_boilerplate_threshold_respects_config(self):
        """With min_page_repeats=10, a string appearing on only 5 pages must
        NOT be demoted — confirming the threshold is actually used.
        """
        doc = DoclingDocument(name="test")
        footer_text = "Section Header On 5 Pages"

        for pg in range(1, 6):  # only 5 pages
            _add_heading(doc, footer_text, pg)

        _repair_pdf_headings(doc, min_page_repeats=10)  # threshold = 10, not 3

        for item in doc.texts:
            if item.text == footer_text:
                assert item.label == DocItemLabel.SECTION_HEADER, (
                    "Should NOT be demoted when below the threshold"
                )

    def test_boilerplate_threshold_reads_from_settings_by_default(self):
        """When min_page_repeats is None, it reads settings.pdf_boilerplate_min_page_repeats."""
        doc = DoclingDocument(name="test")
        footer_text = "Footer On 5 Pages"

        for pg in range(1, 6):
            _add_heading(doc, footer_text, pg)

        with patch("parsers.pdf_router.settings") as mock_settings:
            mock_settings.pdf_boilerplate_min_page_repeats = 10  # won't demote at 5 repeats
            _repair_pdf_headings(doc)  # no override → reads settings

        for item in doc.texts:
            if item.text == footer_text:
                assert item.label == DocItemLabel.SECTION_HEADER

    def test_exactly_at_threshold_is_demoted(self):
        """A string appearing on exactly threshold pages must be demoted (>=, not >)."""
        doc = DoclingDocument(name="test")
        footer_text = "Exactly At Threshold"

        for pg in range(1, 4):  # 3 pages — exactly equal to default threshold (3)
            _add_heading(doc, footer_text, pg)

        _repair_pdf_headings(doc, min_page_repeats=3)

        for item in doc.texts:
            if item.text == footer_text:
                assert item.label == DocItemLabel.PARAGRAPH
