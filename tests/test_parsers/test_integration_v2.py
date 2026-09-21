"""
Phase 4 integration tests — end-to-end v2 pipeline.

Tests the full pipeline without any live HTTP endpoints or database calls:
  Raw Bytes (.docx / .pptx) → ParserRouter → DoclingDocument → Chunker.split()
  → (chunks, metadatas, chunk_ids)
"""
import io

import docx
import pytest
from pptx import Presentation

from docling_core.types.doc import DoclingDocument
from parsers.router import ParserRouter
from core.chunker import Chunker


# ---------------------------------------------------------------------------
# Fixture helpers — build larger docs to produce multiple chunks
# ---------------------------------------------------------------------------

LONG_BODY = (
    "The Honeywell Building Management System continuously monitors all facility zones. "
    "Temperature readings, humidity levels, and occupancy patterns are collected every 30 seconds. "
    "Anomaly detection algorithms run every five minutes and trigger maintenance alerts automatically. "
) * 15  # enough text to produce multiple chunks


def _make_long_docx_bytes() -> bytes:
    doc = docx.Document()
    doc.add_heading("Honeywell Facility Operations Report", level=1)
    doc.add_heading("Zone Monitoring Overview", level=2)
    doc.add_paragraph(LONG_BODY)
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
        slide.placeholders[1].text = f"Slide {i + 1}: {LONG_BODY[:200]}"
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# DOCX pipeline tests
# ---------------------------------------------------------------------------

class TestEndToEndDocxPipelineV2:
    def test_docx_pipeline_produces_chunks(self):
        """Full pipeline: .docx bytes → DoclingDocument → chunks."""
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

    def test_docx_chunk_ids_sequential(self):
        router = ParserRouter()
        chunker = Chunker()
        doc = router.parse(_make_long_docx_bytes(), "facility_report.docx")
        _, metadatas, chunk_ids = chunker.split(doc, "file-d002", "facility_report.docx")

        assert chunk_ids[0] == "file-d002_c0"
        for i, meta in enumerate(metadatas):
            assert meta["chunk_index"] == i

    def test_docx_chunk_ids_unique(self):
        router = ParserRouter()
        chunker = Chunker()
        doc = router.parse(_make_long_docx_bytes(), "facility_report.docx")
        _, _, chunk_ids = chunker.split(doc, "file-d003", "facility_report.docx")
        assert len(chunk_ids) == len(set(chunk_ids))

    def test_docx_heading_text_in_chunks(self):
        """Document heading text must appear somewhere in the chunked output."""
        router = ParserRouter()
        chunker = Chunker()
        doc = router.parse(_make_long_docx_bytes(), "facility_report.docx")
        chunks, _, _ = chunker.split(doc, "file-d004", "facility_report.docx")
        combined = " ".join(chunks)
        assert "Honeywell" in combined or "Facility" in combined


# ---------------------------------------------------------------------------
# PPTX pipeline tests
# ---------------------------------------------------------------------------

class TestEndToEndPptxPipelineV2:
    def test_pptx_pipeline_produces_chunks(self):
        """Full pipeline: .pptx bytes → DoclingDocument → chunks."""
        router = ParserRouter()
        chunker = Chunker()

        doc = router.parse(_make_long_pptx_bytes(), "slides.pptx")
        assert isinstance(doc, DoclingDocument)

        chunks, metadatas, chunk_ids = chunker.split(doc, "file-p001", "slides.pptx")

        assert len(chunks) > 0
        assert len(chunks) == len(metadatas) == len(chunk_ids)

    def test_pptx_metadata_populated(self):
        router = ParserRouter()
        chunker = Chunker()
        doc = router.parse(_make_long_pptx_bytes(), "slides.pptx")
        _, metadatas, _ = chunker.split(doc, "file-p001", "slides.pptx")

        for meta in metadatas:
            assert meta["file_id"] == "file-p001"
            assert meta["filename"] == "slides.pptx"

    def test_pptx_chunk_ids_sequential(self):
        router = ParserRouter()
        chunker = Chunker()
        doc = router.parse(_make_long_pptx_bytes(), "slides.pptx")
        _, metadatas, chunk_ids = chunker.split(doc, "file-p002", "slides.pptx")

        assert chunk_ids[0] == "file-p002_c0"
        for i, meta in enumerate(metadatas):
            assert meta["chunk_index"] == i

    def test_pptx_slide_title_in_chunks(self):
        """Slide title text must appear in the chunked output."""
        router = ParserRouter()
        chunker = Chunker()
        doc = router.parse(_make_long_pptx_bytes(), "slides.pptx")
        chunks, _, _ = chunker.split(doc, "file-p003", "slides.pptx")
        combined = " ".join(chunks)
        assert "Honeywell" in combined or "Zone" in combined
