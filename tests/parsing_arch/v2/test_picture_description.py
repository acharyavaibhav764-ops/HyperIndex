"""
tests/parsing_arch/v2/test_picture_description.py

Tests for the v2 picture description feature.

These tests cover:
- With ENABLE_PICTURE_DESCRIPTION=false (default): pipeline unchanged, no
  [Figure description] chunks produced, all existing tests pass.
- With ENABLE_PICTURE_DESCRIPTION=true: pipeline uses VLM; at least one
  [Figure description] chunk is produced for DOCX and PPTX files that contain
  real embedded raster images.

Note: the VLM tests are marked with @pytest.mark.slow and skipped by default
(they require the SmolVLM model download on first run ~500MB and GPU/CPU time).
Run explicitly with: py -m pytest tests/parsing_arch/v2/test_picture_description.py -v -m slow
"""
import io
import os
import struct
import zlib

import pytest
import docx as _docx
from pptx import Presentation
from pptx.util import Inches

from docling_core.types.doc import DoclingDocument
from docling.document_converter import DocumentConverter
from docling_core.types.io import DocumentStream
from parsers.docling_parser import DoclingParser
from core.chunker import Chunker


# ---------------------------------------------------------------------------
# Helpers — generate a minimal valid PNG in memory (1x1 white pixel)
# ---------------------------------------------------------------------------

def _minimal_png() -> bytes:
    """Return a valid 1×1 white PNG as bytes (no Pillow required)."""
    def chunk(name: bytes, data: bytes) -> bytes:
        c = name + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat_raw = b"\x00\xff\xff\xff"   # filter byte + RGB white pixel
    idat = chunk(b"IDAT", zlib.compress(idat_raw))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def _make_docx_with_image() -> bytes:
    """DOCX with one heading, one paragraph, and one embedded PNG."""
    doc = _docx.Document()
    doc.add_heading("Image Test Document", level=1)
    doc.add_paragraph("This document contains an embedded image.")
    png = io.BytesIO(_minimal_png())
    doc.add_picture(png)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_pptx_with_image() -> bytes:
    """PPTX with two slides; slide 2 has an embedded PNG."""
    prs = Presentation()
    slide1 = prs.slides.add_slide(prs.slide_layouts[0])
    slide1.shapes.title.text = "Slide 1 — Text Only"
    slide1.placeholders[1].text = "No image here."

    slide2 = prs.slides.add_slide(prs.slide_layouts[6])  # blank layout
    png_buf = io.BytesIO(_minimal_png())
    slide2.shapes.add_picture(png_buf, Inches(1), Inches(1), Inches(3), Inches(3))

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Default behaviour (ENABLE_PICTURE_DESCRIPTION=false)
# ---------------------------------------------------------------------------

class TestPictureDescriptionDisabled:
    """When picture description is off, the pipeline must be unchanged."""

    def test_docx_no_figure_description_chunks_by_default(self, monkeypatch):
        monkeypatch.setenv("ENABLE_PICTURE_DESCRIPTION", "false")
        # Re-import settings so the env var takes effect for this test
        import importlib, config as cfg
        importlib.reload(cfg)
        from config import settings as s
        assert not s.enable_picture_description

        parser = DoclingParser()
        doc = parser.parse(_make_docx_with_image(), "test.docx")
        chunker = Chunker()
        chunks, _, _ = chunker.split(doc, "file-pd01", "test.docx")
        figure_chunks = [c for c in chunks if "[Figure description]" in c]
        assert figure_chunks == [], (
            "No [Figure description] chunks expected when ENABLE_PICTURE_DESCRIPTION=false."
        )

    def test_pptx_no_figure_description_chunks_by_default(self, monkeypatch):
        monkeypatch.setenv("ENABLE_PICTURE_DESCRIPTION", "false")
        import importlib, config as cfg
        importlib.reload(cfg)
        from config import settings as s
        assert not s.enable_picture_description

        parser = DoclingParser()
        doc = parser.parse(_make_pptx_with_image(), "test.pptx")
        chunker = Chunker()
        chunks, _, _ = chunker.split(doc, "file-pd02", "test.pptx")
        figure_chunks = [c for c in chunks if "[Figure description]" in c]
        assert figure_chunks == [], (
            "No [Figure description] chunks expected when ENABLE_PICTURE_DESCRIPTION=false."
        )

    def test_all_existing_docx_chunks_still_present(self, monkeypatch):
        """Text content must not regress when picture description is disabled."""
        monkeypatch.setenv("ENABLE_PICTURE_DESCRIPTION", "false")
        import importlib, config as cfg
        importlib.reload(cfg)

        parser = DoclingParser()
        doc = parser.parse(_make_docx_with_image(), "test.docx")
        chunker = Chunker()
        chunks, _, _ = chunker.split(doc, "file-pd03", "test.docx")
        combined = "\n".join(chunks)
        assert "Image Test Document" in combined
        assert "embedded image" in combined


# ---------------------------------------------------------------------------
# Task 8 & 9 — Injection boundary tests (fast, no VLM inference needed)
# ---------------------------------------------------------------------------

class TestPictureDescriptionInjection:
    """Verify special token stripping (Task 8) and failure logging (Task 9)."""

    def test_strip_special_tokens_from_annotation(self):
        """Task 8: Special tokens like <end_of_utterance> must be stripped."""
        from docling_core.types.doc import PictureDescriptionData
        from parsers.docling_parser import _inject_picture_descriptions

        doc = DoclingDocument(name="token_test")
        pic = doc.add_picture(parent=None)
        pic.annotations.append(
            PictureDescriptionData(
                text="This is a chart.<end_of_utterance>  ",
                provenance="smolvlm",
            )
        )

        _inject_picture_descriptions(doc)

        injected_texts = [t.text for t in doc.texts]
        assert injected_texts == ["[Figure description] This is a chart."]

        # Confirm through full chunking pipeline that no token tags appear
        chunker = Chunker()
        chunks, metadatas, _ = chunker.split(doc, "f_tok", "test.docx")
        for chunk in chunks:
            assert "<end_of_utterance>" not in chunk
            assert "<" not in chunk and ">" not in chunk
            assert chunk.startswith("[Figure description]")
        assert metadatas[0]["source"] == "image_description"

    def test_strip_truncated_special_tokens(self):
        """Task 11: Truncated/mid-cut tokens like <end_of_utteranc must be stripped."""
        from docling_core.types.doc import PictureDescriptionData
        from parsers.docling_parser import _inject_picture_descriptions

        doc = DoclingDocument(name="truncated_token_test")
        pic = doc.add_picture(parent=None)
        pic.annotations.append(
            PictureDescriptionData(
                text="Thankyou!<end_of_utteranc",
                provenance="smolvlm",
            )
        )

        _inject_picture_descriptions(doc)

        injected_texts = [t.text for t in doc.texts]
        assert injected_texts == ["[Figure description] Thankyou!"]

        chunker = Chunker()
        chunks, metadatas, _ = chunker.split(doc, "f_trunc", "test.pptx")
        assert chunks[0] == "[Figure description] Thankyou!"
        assert metadatas[0]["source"] == "image_description"

    def test_picture_description_failure_does_not_leak_into_chunks(self, caplog):
        """Task 9: Failed injection logs warning with self_ref without leaking into chunks."""
        import logging
        from unittest.mock import patch
        from docling_core.types.doc import PictureDescriptionData
        from parsers.docling_parser import _inject_picture_descriptions

        doc = DoclingDocument(name="failure_test")
        pic = doc.add_picture(parent=None)
        pic.annotations.append(
            PictureDescriptionData(
                text="Some description text",
                provenance="smolvlm",
            )
        )

        with caplog.at_level(logging.WARNING):
            with patch.object(DoclingDocument, "add_text", side_effect=RuntimeError("Simulated write error")):
                _inject_picture_descriptions(doc)

        # Warning was logged with picture's self_ref
        assert any(
            f"Picture description failed for {pic.self_ref}: Simulated write error" in r.message
            for r in caplog.records
        )

        # doc.texts should be empty, nothing leaked
        assert len(doc.texts) == 0



# ---------------------------------------------------------------------------
# VLM-enabled behaviour (ENABLE_PICTURE_DESCRIPTION=true)
# Marked @pytest.mark.slow — skipped by default, run explicitly.
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestPictureDescriptionEnabled:
    """When ENABLE_PICTURE_DESCRIPTION=true, VLM descriptions must appear in chunks."""

    def test_docx_figure_description_chunk_present(self, monkeypatch):
        monkeypatch.setenv("ENABLE_PICTURE_DESCRIPTION", "true")
        import importlib, config as cfg
        importlib.reload(cfg)
        from config import settings as s
        assert s.enable_picture_description

        parser = DoclingParser()
        doc = parser.parse(_make_docx_with_image(), "test.docx")
        chunker = Chunker()
        chunks, metadatas, _ = chunker.split(doc, "file-pde01", "test.docx")
        figure_chunks = [c for c in chunks if "[Figure description]" in c]
        assert len(figure_chunks) >= 1, (
            "Expected ≥1 [Figure description] chunk when ENABLE_PICTURE_DESCRIPTION=true. "
            "If this fails: (a) check if LibreOffice is required for image extraction, "
            "(b) check if the VLM produced a non-empty description."
        )

    def test_pptx_figure_description_chunk_present(self, monkeypatch):
        monkeypatch.setenv("ENABLE_PICTURE_DESCRIPTION", "true")
        import importlib, config as cfg
        importlib.reload(cfg)

        parser = DoclingParser()
        doc = parser.parse(_make_pptx_with_image(), "test.pptx")
        chunker = Chunker()
        chunks, _, _ = chunker.split(doc, "file-pde02", "test.pptx")
        figure_chunks = [c for c in chunks if "[Figure description]" in c]
        assert len(figure_chunks) >= 1, (
            "Expected ≥1 [Figure description] chunk when ENABLE_PICTURE_DESCRIPTION=true."
        )

    def test_figure_description_metadata_present(self, monkeypatch):
        """figure description chunks must have file_id and filename metadata."""
        monkeypatch.setenv("ENABLE_PICTURE_DESCRIPTION", "true")
        import importlib, config as cfg
        importlib.reload(cfg)

        parser = DoclingParser()
        doc = parser.parse(_make_docx_with_image(), "test.docx")
        chunker = Chunker()
        chunks, metadatas, chunk_ids = chunker.split(doc, "file-pde03", "test.docx")

        for meta in metadatas:
            assert meta["file_id"] == "file-pde03"
            assert meta["filename"] == "test.docx"
            assert "chunk_index" in meta
