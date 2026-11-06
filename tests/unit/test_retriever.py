import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

from qdrant_client import QdrantClient, models

from core.retriever import Retriever


class TestRetriever(unittest.TestCase):
    def setUp(self):
        self.client = QdrantClient(":memory:")
        self.addCleanup(self.client.close)
        self.embeddings = MagicMock()
        self.embeddings.embed.return_value = [[1.0, 0.0, 0.0]]
        self.retriever = Retriever(
            embeddings=self.embeddings,
            client=self.client,
            collection_name="test_documents",
        )

    def _upsert(self):
        self.retriever.upsert(
            ids=["doc_c0", "doc_c1", "doc_c2"],
            documents=["First chunk", "Second chunk", "Third chunk"],
            metadatas=[
                {"document_id": "doc", "chunk_index": i, "page_numbers": [1, 2]}
                for i in range(3)
            ],
            embeddings=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]],
        )

    def test_initialization_creates_collection(self):
        vectors = self.client.get_collection("test_documents").config.params.vectors
        self.assertEqual(vectors.size, 3)
        self.assertEqual(vectors.distance, models.Distance.COSINE)

    def test_chunk_id_to_uuid_is_deterministic(self):
        point_id = self.retriever.chunk_id_to_uuid("doc_c0")
        self.assertEqual(UUID(point_id).version, 5)
        self.assertEqual(point_id, self.retriever.chunk_id_to_uuid("doc_c0"))
        self.assertNotEqual(point_id, self.retriever.chunk_id_to_uuid("doc_c1"))

    def test_upsert_preserves_payload_and_is_idempotent(self):
        self._upsert()
        self.retriever.upsert(
            ["doc_c0"], ["Updated chunk"],
            [{"document_id": "doc", "page_numbers": [2, 3]}], [[1.0, 0.0, 0.0]],
        )
        self.assertEqual(self.client.count("test_documents").count, 3)
        point = self.client.retrieve(
            "test_documents", [self.retriever.chunk_id_to_uuid("doc_c0")],
        )[0]
        self.assertEqual(point.payload, {
            "document_id": "doc", "page_numbers": [2, 3],
            "chunk_id": "doc_c0", "text": "Updated chunk",
        })

    def test_retrieve_normalizes_results_and_distances(self):
        self._upsert()
        result = self.retriever.retrieve("question", k=3)
        self.assertEqual(result["documents"], [["First chunk", "Second chunk", "Third chunk"]])
        self.assertEqual(result["distances"], [[0.0, 1.0, 2.0]])
        self.assertEqual(result["metadatas"][0][0]["page_numbers"], [1, 2])
        self.assertEqual(result["metadatas"][0][0]["chunk_id"], "doc_c0")
        self.assertNotIn("text", result["metadatas"][0][0])
        self.embeddings.embed.assert_called_with(["question"])

    def test_retrieve_empty_collection(self):
        self.assertEqual(self.retriever.retrieve("question"), {
            "documents": [[]], "metadatas": [[]], "distances": [[]],
        })

    def test_retrieve_top_k_and_default_limit(self):
        self._upsert()
        self.assertEqual(len(self.retriever.retrieve("question", k=2)["documents"][0]), 2)
        with patch("core.retriever.pipeline_settings", SimpleNamespace(retrieval_k=1)):
            self.assertEqual(len(self.retriever.retrieve("question")["documents"][0]), 1)

    def test_invalid_inputs_do_not_write_points(self):
        with self.assertRaises(ValueError):
            self.retriever.upsert(["doc_c0"], [], [], [])
        with self.assertRaises(ValueError):
            self.retriever.upsert(["doc_c0"], ["text"], [{}], [[1.0, 0.0]])
        with self.assertRaises(ValueError):
            self.retriever.retrieve("question", k=0)
        self.retriever.upsert([], [], [], [])
        self.assertEqual(self.client.count("test_documents").count, 0)

    def test_existing_collection_validation(self):
        self._upsert()
        Retriever(self.embeddings, self.client, "test_documents")
        self.assertEqual(self.client.count("test_documents").count, 3)
        for name, size, distance in [
            ("wrong_size", 2, models.Distance.COSINE),
            ("wrong_distance", 3, models.Distance.DOT),
        ]:
            with self.subTest(name=name):
                self.client.create_collection(name, vectors_config=models.VectorParams(size=size, distance=distance))
                with self.assertRaises(ValueError):
                    Retriever(self.embeddings, self.client, name)

    def test_client_selection(self):
        config = SimpleNamespace(
            qdrant_host="qdrant", qdrant_port=6333,
            qdrant_path="unused", qdrant_collection="test_documents",
        )
        with patch("core.retriever.settings", config):
            with patch("core.retriever.QdrantClient", return_value=self.client) as factory:
                Retriever(self.embeddings, self.client)
                factory.assert_not_called()
                Retriever(self.embeddings)
                factory.assert_called_once_with(host="qdrant", port=6333)

            config.qdrant_host = None
            config.qdrant_path = None
            retriever = Retriever(self.embeddings)
            self.addCleanup(retriever.client.close)
            self.assertTrue(retriever.client.collection_exists("test_documents"))

            with TemporaryDirectory() as path:
                config.qdrant_path = path
                retriever = Retriever(self.embeddings)
                retriever.client.close()
                retriever = Retriever(self.embeddings)
                try:
                    self.assertTrue(retriever.client.collection_exists("test_documents"))
                finally:
                    retriever.client.close()


if __name__ == "__main__":
    unittest.main()
