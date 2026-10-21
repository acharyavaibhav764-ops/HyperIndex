import unittest
from unittest.mock import MagicMock, patch

from core.chunker import _doc_meta, _flatten_meta
from core.retriever import Retriever


class TestPdfChunkerRetriever(unittest.TestCase):
    """Unit tests for Chroma scalar metadata flattening, in-page synthetic headings, and retrieval ToC filtering."""

    def test_flatten_meta_converts_lists_and_drops_none_page(self):
        """_flatten_meta converts list fields to strings and omits page=None for Chroma."""
        raw_meta = {
            "document_id": "doc123",
            "page": None,
            "page_numbers": [1, 2, 3],
            "heading_path": ["3 Electrical connection", "3.8 Terminals"],
            "content_type": "table",
            "chunk_index": 0,
            "is_valid": True,
        }

        flat = _flatten_meta(raw_meta)
        self.assertNotIn("page", flat)
        self.assertEqual(flat["page_numbers"], "1,2,3")
        self.assertEqual(flat["heading_path"], "3 Electrical connection > 3.8 Terminals")
        self.assertEqual(flat["content_type"], "table")
        self.assertEqual(flat["chunk_index"], 0)
        self.assertTrue(flat["is_valid"])

    def test_flatten_meta_preserves_scalar_page(self):
        """_flatten_meta preserves integer page numbers."""
        flat = _flatten_meta({"page": 5, "page_numbers": "5"})
        self.assertEqual(flat["page"], 5)
        self.assertEqual(flat["page_numbers"], "5")

    @patch("core.retriever.chromadb")
    def test_retriever_query_filters_toc_by_default(self, mock_chroma):
        """Retriever.retrieve applies where={'content_type': {'$ne': 'toc'}} when include_toc=False."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chroma.HttpClient.return_value = mock_client
        mock_chroma.PersistentClient.return_value = mock_client

        mock_embeddings = MagicMock()
        retriever = Retriever(embeddings=mock_embeddings)

        mock_collection.query.return_value = {
            "documents": [["Chunk 1", "Chunk 2"]],
            "metadatas": [[{"content_type": "text"}, {"content_type": "table"}]],
            "distances": [[0.1, 0.2]],
        }

        res = retriever.retrieve("device specifications", k=3, include_toc=False)

        mock_collection.query.assert_called_once_with(
            query_texts=["device specifications"],
            n_results=3,
            include=["documents", "metadatas", "distances"],
            where={"content_type": {"$ne": "toc"}},
        )
        self.assertIn("documents", res)

    @patch("core.retriever.chromadb")
    def test_retriever_query_includes_toc_when_requested(self, mock_chroma):
        """Retriever.retrieve omits the where filter when include_toc=True."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chroma.HttpClient.return_value = mock_client
        mock_chroma.PersistentClient.return_value = mock_client

        mock_embeddings = MagicMock()
        retriever = Retriever(embeddings=mock_embeddings)

        mock_collection.query.return_value = {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }

        retriever.retrieve("table of contents", k=5, include_toc=True)

        mock_collection.query.assert_called_once_with(
            query_texts=["table of contents"],
            n_results=5,
            include=["documents", "metadatas", "distances"],
            where=None,
        )

    @patch("core.retriever.chromadb")
    def test_retriever_query_graceful_fallback_for_legacy_collections(self, mock_chroma):
        """Retriever.retrieve falls back to unfiltered query if where filter raises an exception."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chroma.HttpClient.return_value = mock_client
        mock_chroma.PersistentClient.return_value = mock_client

        mock_embeddings = MagicMock()
        retriever = Retriever(embeddings=mock_embeddings)

        mock_collection.query.side_effect = [
            Exception("Chroma error: where clause failed"),
            {"documents": [["Fallback chunk"]], "metadatas": [[{}]], "distances": [[0.1]]},
        ]

        res = retriever.retrieve("query", k=2, include_toc=False)

        self.assertEqual(mock_collection.query.call_count, 2)
        second_call_kwargs = mock_collection.query.call_args_list[1][1]
        self.assertNotIn("where", second_call_kwargs)
        self.assertEqual(res["documents"], [["Fallback chunk"]])


if __name__ == "__main__":
    unittest.main()
