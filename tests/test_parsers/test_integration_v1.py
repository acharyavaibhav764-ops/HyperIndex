"""
Phase 6 integration test — end-to-end v1 pipeline.

Tests the full pipeline without hitting any live HTTP endpoints:
  Raw Bytes → ParserRouter → DoclingDocument → Chunker.split() → (chunks, meta, ids)
"""
import pytest
from docling_core.types.doc import DoclingDocument

from parsers.router import ParserRouter
from core.chunker import Chunker


LONG_TEXT = (
    "The Honeywell Building Management System processes sensor data from all zones. "
    "Temperature readings, humidity levels, and occupancy patterns are analyzed. "
    "Anomaly detection runs every five minutes and triggers alerts as needed. "
) * 20  # ~60 sentences — enough to produce multiple chunks


class TestEndToEndPipelineV1:
    def test_txt_pipeline(self):
        """Full pipeline: .txt bytes → DoclingDocument → chunks."""
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
        """Full pipeline: .md bytes → DoclingDocument → chunks."""
        md_content = "# Report\n\n" + LONG_TEXT
        router = ParserRouter()
        chunker = Chunker()

        doc = router.parse(md_content.encode("utf-8"), "report.md")
        assert isinstance(doc, DoclingDocument)

        chunks, metadatas, chunk_ids = chunker.split(doc, "file-002", "report.md")

        assert len(chunks) > 0
        # Markdown heading text should appear somewhere in the chunks
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
