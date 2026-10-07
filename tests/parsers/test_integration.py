"""
Integration tests — end-to-end multi-format parsing pipeline.

Tests the full pipeline without hitting any live HTTP endpoints or database:
  Raw Bytes (.txt / .md / .docx / .pptx) ➔ ParserRouter ➔ DoclingDocument ➔ Chunker.split()
  ➔ (chunks, metadatas, chunk_ids)
"""
import io

import docx
import pytest
from docling_core.types.doc import DoclingDocument
from pptx import Presentation

from core.chunker import Chunker
from core.parsers.router import ParserRouter

# ---------------------------------------------------------------------------
# Test Fixtures & Document Generators
# ---------------------------------------------------------------------------

LONG_TEXT = (
    "The Honeywell Building Management System continuously monitors all facility zones. "
    "Temperature readings, humidity levels, and occupancy patterns are analyzed. "
    "Anomaly detection algorithms run every five minutes and trigger maintenance alerts automatically. "
) * 15


def _make_long_docx_bytes() -> bytes:
    doc = docx.Document()
    doc.add_heading("Honeywell Facility Operations Report", level=1)
    doc.add_heading("Zone Monitoring Overview", level=2)
    doc.add_paragraph(LONG_TEXT)
    table = doc.add_table(rows=3, cols=3)
    table.cell(0, 0).text = "Zone"
    table.cell(0, 1).text = "Temperature"
    table.cell(0, 2).text = "Status"
    table.cell(1, 0).text = "Zone A"
    table.cell(1, 1).text = "22°C"
    table.cell(1, 2).text = "Normal"
    table.cell(2, 0).text = "Zone B"
    table.cell(2, 1).text = "25°C"
    table.cell(2, 2).text = "Warning"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_long_pptx_bytes() -> bytes:
    prs = Presentation()
    for i, text in enumerate([
        "Honeywell Facility Overview",
        "Zone Monitoring Details",
        "Anomaly Detection Summary",
    ]):
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        slide.shapes.title.text = text
        slide.placeholders[1].text = f"Slide {i + 1}: {LONG_TEXT[:200]}"
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# TXT & MD Pipeline Tests
# ---------------------------------------------------------------------------

class TestEndToEndTextPipeline:
    def test_txt_pipeline(self):
        """Full pipeline: .txt bytes ➔ DoclingDocument ➔ chunks."""
        router = ParserRouter()
        chunker = Chunker()

        doc = router.parse(LONG_TEXT.encode("utf-8"), "report.txt")
        assert isinstance(doc, DoclingDocument)

        chunks, metadatas, chunk_ids = chunker.split(doc, "file-001", "report.txt")

        assert len(chunks) > 0
        assert len(chunks) == len(metadatas) == len(chunk_ids)
        assert all(meta["file_id"] == "file-001" for meta in metadatas)
        assert all(meta["filename"] == "report.txt" for meta in metadatas)
        assert chunk_ids[0] == "file-001_c0"

    def test_md_pipeline(self):
        """Full pipeline: .md bytes ➔ DoclingDocument ➔ chunks."""
        md_content = "# Report\n\n" + LONG_TEXT
        router = ParserRouter()
        chunker = Chunker()

        doc = router.parse(md_content.encode("utf-8"), "report.md")
        assert isinstance(doc, DoclingDocument)

        chunks, metadatas, chunk_ids = chunker.split(doc, "file-002", "report.md")

        assert len(chunks) > 0
        combined = " ".join(chunks)
        assert "Report" in combined or "Honeywell" in combined

    def test_chunk_index_is_sequential(self):
        """chunk_index in metadata must be 0-based sequential integers."""
        router = ParserRouter()
        chunker = Chunker()
        doc = router.parse(LONG_TEXT.encode(), "seq_test.txt")
        _, metadatas, _ = chunker.split(doc, "file-003", "seq_test.txt")
        for i, meta in enumerate(metadatas):
            assert meta["chunk_index"] == i

    def test_chunk_ids_unique(self):
        """All chunk IDs must be unique."""
        router = ParserRouter()
        chunker = Chunker()
        doc = router.parse(LONG_TEXT.encode(), "unique_test.txt")
        _, _, chunk_ids = chunker.split(doc, "file-004", "unique_test.txt")
        assert len(chunk_ids) == len(set(chunk_ids))


# ---------------------------------------------------------------------------
# DOCX & PPTX Pipeline Tests
# ---------------------------------------------------------------------------

class TestEndToEndOfficePipeline:
    def test_docx_pipeline_produces_chunks(self):
        """Full pipeline: .docx bytes ➔ DoclingDocument ➔ chunks."""
        router = ParserRouter()
        chunker = Chunker()

        doc = router.parse(_make_long_docx_bytes(), "facility_report.docx")
        assert isinstance(doc, DoclingDocument)

        chunks, metadatas, chunk_ids = chunker.split(doc, "file-d001", "facility_report.docx")

        assert len(chunks) > 0
        assert len(chunks) == len(metadatas) == len(chunk_ids)

    def test_docx_metadata_populated(self):
        router = ParserRouter()
        chunker = Chunker()
        doc = router.parse(_make_long_docx_bytes(), "facility_report.docx")
        _, metadatas, _ = chunker.split(doc, "file-d001", "facility_report.docx")

        for meta in metadatas:
            assert meta["file_id"] == "file-d001"
            assert meta["filename"] == "facility_report.docx"
            assert "chunk_index" in meta

    def test_docx_heading_text_in_chunks(self):
        """Document heading text must appear somewhere in the chunked output."""
        router = ParserRouter()
        chunker = Chunker()
        doc = router.parse(_make_long_docx_bytes(), "facility_report.docx")
        chunks, _, _ = chunker.split(doc, "file-d004", "facility_report.docx")
        combined = " ".join(chunks)
        assert "Honeywell" in combined or "Facility" in combined

    def test_pptx_pipeline_produces_chunks(self):
        """Full pipeline: .pptx bytes ➔ DoclingDocument ➔ chunks."""
        router = ParserRouter()
        chunker = Chunker()

        doc = router.parse(_make_long_pptx_bytes(), "slides.pptx")
        assert isinstance(doc, DoclingDocument)

        chunks, metadatas, chunk_ids = chunker.split(doc, "file-p001", "slides.pptx")

        assert len(chunks) > 0
        assert len(chunks) == len(metadatas) == len(chunk_ids)

    def test_pptx_slide_title_in_chunks(self):
        """Slide title text must appear in the chunked output."""
        router = ParserRouter()
        chunker = Chunker()
        doc = router.parse(_make_long_pptx_bytes(), "slides.pptx")
        chunks, _, _ = chunker.split(doc, "file-p003", "slides.pptx")
        combined = " ".join(chunks)
        assert "Honeywell" in combined or "Zone" in combined

