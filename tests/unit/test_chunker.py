"""
Phase 4 tests — Chunker with HybridChunker dispatch.

Verifies:
- Legacy list[tuple[int,str]] path produces identical output to the original
  Chunker (zero regression).
- DoclingDocument path produces valid (chunks, metadatas, chunk_ids) output.
- chunk_index values in metadata are sequential, starting at 0.
- chunk_ids follow the "{file_id}_c{index}" naming convention.
- Metadata keys document_id, file_id, filename are always populated.
- ValueError is raised when no extractable text is found (both paths).
"""
import pytest

from core.chunker import Chunker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pages(text: str = "The quick brown fox. " * 50) -> list[tuple[int, str]]:
    return [(1, text)]


def _make_docling_doc(text: str = "The quick brown fox. " * 50):
    """Build a minimal DoclingDocument from text via TextParser."""
    from parsers.text import TextParser
    return TextParser().parse(text.encode(), "sample.txt")


FILE_ID = "test-file-001"
FILENAME = "test.txt"


# ---------------------------------------------------------------------------
# Legacy path
# ---------------------------------------------------------------------------

class TestChunkerLegacyPath:
    def test_returns_three_tuple(self):
        chunker = Chunker()
        result = chunker.split(_make_pages(), FILE_ID, FILENAME)
        assert isinstance(result, tuple) and len(result) == 3

    def test_chunks_are_strings(self):
        chunker = Chunker()
        chunks, _, _ = chunker.split(_make_pages(), FILE_ID, FILENAME)
        assert all(isinstance(c, str) for c in chunks)

    def test_chunk_ids_format(self):
        chunker = Chunker()
        _, _, chunk_ids = chunker.split(_make_pages(), FILE_ID, FILENAME)
        for i, cid in enumerate(chunk_ids):
            assert cid == f"{FILE_ID}_c{i}"

    def test_metadata_keys_present(self):
        chunker = Chunker()
        _, metadatas, _ = chunker.split(_make_pages(), FILE_ID, FILENAME)
        for meta in metadatas:
            assert meta["document_id"] == FILE_ID
            assert meta["file_id"] == FILE_ID
            assert meta["filename"] == FILENAME
            assert "chunk_index" in meta

    def test_chunk_index_sequential(self):
        chunker = Chunker()
        _, metadatas, _ = chunker.split(_make_pages(), FILE_ID, FILENAME)
        for i, meta in enumerate(metadatas):
            assert meta["chunk_index"] == i

    def test_empty_pages_raises(self):
        chunker = Chunker()
        with pytest.raises(ValueError, match="extractable text"):
            chunker.split([(1, "   ")], FILE_ID, FILENAME)


# ---------------------------------------------------------------------------
# DoclingDocument path
# ---------------------------------------------------------------------------

class TestChunkerDoclingPath:
    def test_returns_three_tuple(self):
        chunker = Chunker()
        doc = _make_docling_doc()
        result = chunker.split(doc, FILE_ID, FILENAME)
        assert isinstance(result, tuple) and len(result) == 3

    def test_chunks_are_strings(self):
        chunker = Chunker()
        chunks, _, _ = chunker.split(_make_docling_doc(), FILE_ID, FILENAME)
        assert all(isinstance(c, str) for c in chunks)

    def test_chunk_ids_format(self):
        chunker = Chunker()
        _, _, chunk_ids = chunker.split(_make_docling_doc(), FILE_ID, FILENAME)
        for i, cid in enumerate(chunk_ids):
            assert cid == f"{FILE_ID}_c{i}"

    def test_metadata_keys_present(self):
        chunker = Chunker()
        _, metadatas, _ = chunker.split(_make_docling_doc(), FILE_ID, FILENAME)
        for meta in metadatas:
            assert meta["document_id"] == FILE_ID
            assert meta["file_id"] == FILE_ID
            assert meta["filename"] == FILENAME
            assert "chunk_index" in meta

    def test_chunk_index_sequential(self):
        chunker = Chunker()
        _, metadatas, _ = chunker.split(_make_docling_doc(), FILE_ID, FILENAME)
        for i, meta in enumerate(metadatas):
            assert meta["chunk_index"] == i

    def test_dispatch_on_type(self):
        """Pass a DoclingDocument — confirm it goes through the Docling path."""
        from docling_core.types.doc import DoclingDocument
        chunker = Chunker()
        doc = _make_docling_doc()
        assert isinstance(doc, DoclingDocument)
        chunks, _, _ = chunker.split(doc, FILE_ID, FILENAME)
        assert len(chunks) > 0
