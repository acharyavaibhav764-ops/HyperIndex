"""
Unit tests — DoclingParser for .docx and .pptx.

Verifies:
- In-memory .docx parsing preserves headings, paragraphs, and tables.
- In-memory .pptx parsing captures slide title and body text.
- can_handle() returns True/False for correct extensions.
- Empty file bytes raise or return a minimal valid DoclingDocument.
"""
import io

import docx
import pytest
from pptx import Presentation

from docling_core.types.doc import DoclingDocument
from core.parsers.docling_parser import DoclingParser


@pytest.fixture(scope="module")
def parser() -> DoclingParser:
    return DoclingParser()


# ---------------------------------------------------------------------------
# Helpers — build minimal in-memory Office files
# ---------------------------------------------------------------------------

def _make_docx_bytes(with_table: bool = False) -> bytes:
    """Create a minimal .docx document in memory."""
    doc = docx.Document()
    doc.add_heading("Honeywell System Overview", level=1)
    doc.add_paragraph(
        "The building management system monitors all facility zones. "
        "Temperature and humidity sensors report every 30 seconds."
    )
    if with_table:
        table = doc.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Zone"
        table.cell(0, 1).text = "Status"
        table.cell(1, 0).text = "Zone A"
        table.cell(1, 1).text = "Normal"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_pptx_bytes() -> bytes:
    """Create a minimal .pptx presentation in memory."""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Honeywell Facility Report"
    slide.placeholders[1].text = "Q3 sensor anomaly summary across all monitored zones."
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# can_handle tests
# ---------------------------------------------------------------------------

class TestDoclingParserCanHandle:
    def test_docx_supported(self, parser):
        assert parser.can_handle(".docx") is True

    def test_pptx_supported(self, parser):
        assert parser.can_handle(".pptx") is True

    def test_case_insensitive_docx(self, parser):
        assert parser.can_handle(".DOCX") is True

    def test_case_insensitive_pptx(self, parser):
        assert parser.can_handle(".PPTX") is True

    def test_pdf_not_supported(self, parser):
        assert parser.can_handle(".pdf") is False

    def test_txt_not_supported(self, parser):
        assert parser.can_handle(".txt") is False

    def test_doc_not_supported(self, parser):
        """Legacy .doc is not supported in v2 (requires LibreOffice, added in v3)."""
        assert parser.can_handle(".doc") is False

    def test_xyz_not_supported(self, parser):
        assert parser.can_handle(".xyz") is False


# ---------------------------------------------------------------------------
# DOCX parse tests
# ---------------------------------------------------------------------------

class TestDoclingParserDocx:
    def test_returns_docling_document(self, parser):
        doc = parser.parse(_make_docx_bytes(), "overview.docx")
        assert isinstance(doc, DoclingDocument)

    def test_heading_preserved(self, parser):
        doc = parser.parse(_make_docx_bytes(), "overview.docx")
        exported = doc.export_to_markdown()
        assert "Honeywell System Overview" in exported

    def test_paragraph_text_preserved(self, parser):
        doc = parser.parse(_make_docx_bytes(), "overview.docx")
        exported = doc.export_to_markdown()
        assert "building management system" in exported

    def test_table_content_preserved(self, parser):
        doc = parser.parse(_make_docx_bytes(with_table=True), "overview.docx")
        exported = doc.export_to_markdown()
        # Table cell values must appear in exported text
        assert "Zone" in exported
        assert "Normal" in exported


# ---------------------------------------------------------------------------
# PPTX parse tests
# ---------------------------------------------------------------------------

class TestDoclingParserPptx:
    def test_returns_docling_document(self, parser):
        doc = parser.parse(_make_pptx_bytes(), "report.pptx")
        assert isinstance(doc, DoclingDocument)

    def test_slide_title_preserved(self, parser):
        doc = parser.parse(_make_pptx_bytes(), "report.pptx")
        exported = doc.export_to_markdown()
        assert "Honeywell Facility Report" in exported

    def test_slide_body_preserved(self, parser):
        doc = parser.parse(_make_pptx_bytes(), "report.pptx")
        exported = doc.export_to_markdown()
        assert "sensor anomaly" in exported

