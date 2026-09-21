"""
tests/parsing_arch/v2/test_serialize_fix.py

Regression tests for the v2 HybridChunker contextualize() fix.

Guards two gaps that were found during real-document testing:

Gap A — chunk.text (body only) silently drops section/slide titles.
         Fixed by using chunker.contextualize(chunk) in _split_docling().
         These tests assert that slide/section title text appears in the
         chunk output.

Gap B — Slides with a title and no body produce zero raw chunks from
         HybridChunker.  The chunker therefore drops them entirely, even
         after Gap A is fixed.  Fixed by walking doc.texts post-chunking
         and injecting synthetic chunks for uncovered TITLE/SECTION_HEADER
         items.  These tests assert that heading-only slides produce ≥1 chunk.
"""
import io
import sys

import pytest
from pptx import Presentation
import docx as _docx

from docling_core.types.doc import DoclingDocument
from docling.document_converter import DocumentConverter
from docling_core.types.io import DocumentStream
from core.chunker import Chunker


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_pptx_with_heading_only_slide() -> bytes:
    """3 slides: body+heading, heading-only (no body), body+heading."""
    prs = Presentation()
    layouts = prs.slide_layouts

    for title_text, body_text in [
        ("Architecture Overview", "Upload -> Parse -> Embed -> ChromaDB."),
        ("Proposed Outcomes", ""),           # heading-only slide — no body
        ("Conclusion", "The system works."),
    ]:
        slide = prs.slides.add_slide(layouts[0])
        slide.shapes.title.text = title_text
        try:
            ph = slide.placeholders[1]
            ph.text = body_text
        except (IndexError, KeyError):
            pass

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _make_docx_with_sections() -> bytes:
    """DOCX with headings at multiple levels and body paragraphs."""
    doc = _docx.Document()
    doc.add_heading("Honeywell System Overview", level=1)
    doc.add_paragraph(
        "The building management system monitors all facility zones continuously."
    )
    doc.add_heading("Zone Monitoring Details", level=2)
    doc.add_paragraph("Temperature, humidity and occupancy sensors report every 30s.")
    doc.add_heading("Appendix", level=1)       # heading with no body below it
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _parse_and_chunk(file_bytes: bytes, filename: str, file_id: str):
    stream = DocumentStream(name=filename, stream=io.BytesIO(file_bytes))
    doc = DocumentConverter().convert(stream).document
    return Chunker().split(doc, file_id, filename)


# ---------------------------------------------------------------------------
# Gap A — slide/section titles must appear in chunk text
# ---------------------------------------------------------------------------

class TestGapA_TitlesInChunkText:
    """chunker.contextualize() must include heading text in the chunk content."""

    def test_pptx_slide_titles_in_chunks(self):
        chunks, _, _ = _parse_and_chunk(
            _make_pptx_with_heading_only_slide(), "slides.pptx", "file-ga01"
        )
        combined = "\n".join(chunks)
        assert "Architecture Overview" in combined, (
            "Slide title 'Architecture Overview' must appear in chunk output. "
            "Gap A fix: use contextualize() instead of chunk.text."
        )
        assert "Conclusion" in combined, (
            "Slide title 'Conclusion' must appear in chunk output."
        )

    def test_docx_section_headings_in_chunks(self):
        chunks, _, _ = _parse_and_chunk(
            _make_docx_with_sections(), "report.docx", "file-ga02"
        )
        combined = "\n".join(chunks)
        assert "Honeywell System Overview" in combined, (
            "DOCX heading 'Honeywell System Overview' must appear in chunks."
        )
        assert "Zone Monitoring Details" in combined, (
            "DOCX heading 'Zone Monitoring Details' must appear in chunks."
        )

    def test_chunk_text_not_just_body(self):
        """A body-bearing slide's chunk text must include the title, not just the body."""
        chunks, _, _ = _parse_and_chunk(
            _make_pptx_with_heading_only_slide(), "slides.pptx", "file-ga03"
        )
        # Find the chunk containing the Architecture slide body
        arch_chunks = [c for c in chunks if "Upload" in c or "Parse" in c]
        assert arch_chunks, "Expected at least one chunk from the Architecture slide body."
        # The title should be in the same chunk, not stripped out
        assert any("Architecture Overview" in c for c in arch_chunks), (
            "Slide title should be in the same chunk as its body text."
        )


# ---------------------------------------------------------------------------
# Gap B — heading-only slides must produce ≥1 chunk
# ---------------------------------------------------------------------------

class TestGapB_HeadingOnlySlides:
    """Heading-only slides (no body) must not be silently dropped."""

    def test_heading_only_slide_produces_chunk(self):
        chunks, _, _ = _parse_and_chunk(
            _make_pptx_with_heading_only_slide(), "slides.pptx", "file-gb01"
        )
        combined = "\n".join(chunks)
        assert "Proposed Outcomes" in combined, (
            "Heading-only slide 'Proposed Outcomes' must produce at least one chunk. "
            "Gap B fix: inject synthetic chunks for uncovered TITLE/SECTION_HEADER items."
        )

    def test_heading_only_pptx_chunk_count(self):
        """3-slide PPTX (2 body + 1 heading-only) must produce ≥3 chunks."""
        chunks, _, _ = _parse_and_chunk(
            _make_pptx_with_heading_only_slide(), "slides.pptx", "file-gb02"
        )
        assert len(chunks) >= 3, (
            f"Expected ≥3 chunks (one per slide), got {len(chunks)}. "
            "The heading-only slide may have been dropped."
        )

    def test_docx_trailing_heading_produces_chunk(self):
        """'Appendix' heading at the end of a DOCX with no body must appear in chunks."""
        chunks, _, _ = _parse_and_chunk(
            _make_docx_with_sections(), "report.docx", "file-gb03"
        )
        combined = "\n".join(chunks)
        assert "Appendix" in combined, (
            "Trailing heading 'Appendix' (no body below it) must appear in chunks."
        )

    def test_chunk_ids_sequential_after_synthetic(self):
        """Synthetic chunks must have sequential chunk_index in metadata."""
        _, metadatas, chunk_ids = _parse_and_chunk(
            _make_pptx_with_heading_only_slide(), "slides.pptx", "file-gb04"
        )
        for i, meta in enumerate(metadatas):
            assert meta["chunk_index"] == i, (
                f"chunk_index must be sequential; index {i} has chunk_index={meta['chunk_index']}"
            )
        assert chunk_ids[0] == "file-gb04_c0"
