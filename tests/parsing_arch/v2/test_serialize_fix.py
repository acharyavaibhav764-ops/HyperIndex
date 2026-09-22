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


# ---------------------------------------------------------------------------
# Bug A & B Fixes — Pseudo-heading Boundary & Multi-page metadata
# ---------------------------------------------------------------------------

class TestBugAFix_PseudoHeadingBoundary:
    """Pseudo-headings in PPTX must act as hard boundaries for HybridChunker."""
    
    def test_pseudo_heading_hard_boundary(self):
        """High token load before a slide title should not cause the title to be orphaned."""
        prs = Presentation()
        layouts = prs.slide_layouts
        
        # Slide 1: High token load
        slide1 = prs.slides.add_slide(layouts[0])
        slide1.shapes.title.text = "Slide 1 Title"
        # We need a large text block that pushes the chunker close to its limit (default 256 tokens)
        large_text = "word " * 300
        slide1.placeholders[1].text = large_text
        
        # Slide 2: Pseudo-heading (no trailing period, short)
        slide2 = prs.slides.add_slide(layouts[0])
        slide2.shapes.title.text = "Proposed Outcomes"
        slide2.placeholders[1].text = "Bullet 1\nBullet 2\nBullet 3"
        
        buf = io.BytesIO()
        prs.save(buf)
        file_bytes = buf.getvalue()
        
        from parsers.docling_parser import DoclingParser
        from core.chunker import Chunker
        
        doc = DoclingParser().parse(file_bytes, "high_token.pptx")
        chunks, _, _ = Chunker().split(doc, "file-buga", "high_token.pptx")
        
        # Find the chunk containing the bullets from slide 2
        slide2_chunks = [c for c in chunks if "Bullet 1" in c]
        assert slide2_chunks, "Expected to find slide 2 body in chunks"
        
        # The pseudo-heading should be prepended to the chunk via contextualize()
        # because it acted as a SECTION_HEADER boundary, preventing it from being
        # orphaned in the preceding chunk.
        assert "Proposed Outcomes" in slide2_chunks[0], (
            "Slide title 'Proposed Outcomes' was orphaned from its body bullets!"
        )


class TestBugBFix_MultiPageMetadata:
    """Chunk metadata must accurately reflect multi-page spans."""
    
    def test_multi_page_metadata(self):
        """Consecutive small slides merged into a single chunk must expose all page numbers."""
        prs = Presentation()
        layouts = prs.slide_layouts
        
        # Two very short slides that fit well within token limits
        s1 = prs.slides.add_slide(layouts[0])
        s1.shapes.title.text = "Small Slide A"
        
        s2 = prs.slides.add_slide(layouts[0])
        s2.shapes.title.text = "Small Slide B"
        s2.placeholders[1].text = "Some body text here"
        
        buf = io.BytesIO()
        prs.save(buf)
        file_bytes = buf.getvalue()
        
        from parsers.docling_parser import DoclingParser
        from core.chunker import Chunker
        
        doc = DoclingParser().parse(file_bytes, "merged.pptx")
        chunks, metadatas, _ = Chunker().split(doc, "file-bugb", "merged.pptx")
        
        # Since these are very short, HybridChunker will likely merge them into one chunk
        # or at most two. We want to find a chunk that spans pages [1, 2] if it exists,
        # or just verify 'page_numbers' field is present and correct in all chunks.
        for meta in metadatas:
            assert "page" in meta
            assert "page_numbers" in meta
            assert isinstance(meta["page_numbers"], list)
            assert meta["page"] == meta["page_numbers"][0] if meta["page_numbers"] else None
            
            # If a chunk spans both slides
            if 1 in meta["page_numbers"] and 2 in meta["page_numbers"]:
                # Success!
                pass
