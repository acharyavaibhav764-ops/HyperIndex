import unittest
from unittest.mock import MagicMock
from fastapi import UploadFile

from services.ingestion_service import IngestionService
from services.rag_service import RAGService
from schemas.document import DocumentIngestResponse
from schemas.query import QueryResponse


class TestServices(unittest.TestCase):
    def test_ingestion_service_success(self):
        mock_uploader = MagicMock()
        mock_parser = MagicMock()
        mock_chunker = MagicMock()
        mock_embeddings = MagicMock()
        mock_retriever = MagicMock()
        mock_retriever.collection_name = "test_collection"

        mock_uploader.upload_files.return_value = [
            {"document_id": "doc-123", "filename": "sample.txt", "size_bytes": 100}
        ]
        mock_uploader.download_file.return_value = (b"hello world", "sample.txt")
        mock_parser.parse.return_value = [{"text": "hello world", "page_number": 1}]
        mock_chunker.split.return_value = (
            ["hello world chunk"],
            [{"source": "sample.txt", "page": 1, "document_id": "doc-123"}],
            ["doc-123_chunk_0"],
        )
        mock_embeddings.embed.return_value = [[0.1, 0.2, 0.3]]

        service = IngestionService(
            uploader=mock_uploader,
            parser=mock_parser,
            chunker=mock_chunker,
            embeddings=mock_embeddings,
            retriever=mock_retriever,
        )

        dummy_file = MagicMock(spec=UploadFile)
        result = service.ingest_files([dummy_file])

        self.assertIsInstance(result, DocumentIngestResponse)
        self.assertEqual(result.count, 1)
        self.assertEqual(result.documents[0].document_id, "doc-123")
        self.assertEqual(result.documents[0].filename, "sample.txt")
        self.assertEqual(result.documents[0].size_bytes, 100)
        self.assertEqual(result.documents[0].collection, "test_collection")
        self.assertEqual(result.documents[0].total_chunks, 1)
        self.assertEqual(result.documents[0].status, "indexed")

        mock_uploader.upload_files.assert_called_once()
        mock_uploader.download_file.assert_called_once_with("doc-123")
        mock_parser.parse.assert_called_once_with(b"hello world", "sample.txt")
        mock_chunker.split.assert_called_once_with([{"text": "hello world", "page_number": 1}], "doc-123", "sample.txt")
        mock_embeddings.embed.assert_called_once_with(["hello world chunk"])
        mock_retriever.upsert.assert_called_once_with(
            ids=["doc-123_chunk_0"],
            documents=["hello world chunk"],
            metadatas=[{"source": "sample.txt", "page": 1, "document_id": "doc-123"}],
            embeddings=[[0.1, 0.2, 0.3]],
        )

    def test_ingestion_service_empty_files(self):
        service = IngestionService(
            uploader=MagicMock(),
            parser=MagicMock(),
            chunker=MagicMock(),
            embeddings=MagicMock(),
            retriever=MagicMock(),
        )
        with self.assertRaises(ValueError) as ctx:
            service.ingest_files([])
        self.assertEqual(str(ctx.exception), "At least one file is required")

    def test_rag_service_success(self):
        mock_retriever = MagicMock()
        mock_generator = MagicMock()
        mock_generator.model = "test-model"

        mock_retriever.retrieve.return_value = {
            "documents": [["Retrieved text content"]],
            "metadatas": [[{"source": "doc.pdf", "page": 1}]],
            "distances": [[0.15]],
        }
        mock_generator.build_prompt.return_value = "Constructed prompt"
        mock_generator.generate.return_value = "Generated answer text"

        service = RAGService(
            retriever=mock_retriever,
            generator=mock_generator,
            retrieval_k=3,
        )

        result = service.answer_question("What is Honeywell?")

        self.assertIsInstance(result, QueryResponse)
        self.assertEqual(result.question, "What is Honeywell?")
        self.assertEqual(result.answer, "Generated answer text")
        self.assertEqual(result.model, "test-model")
        self.assertEqual(len(result.sources), 1)
        self.assertEqual(result.sources[0].metadata, {"source": "doc.pdf", "page": 1})
        self.assertEqual(result.sources[0].distance, 0.15)

        mock_retriever.retrieve.assert_called_once_with("What is Honeywell?", k=3)
        mock_generator.build_prompt.assert_called_once_with("What is Honeywell?", ["Retrieved text content"], [{"source": "doc.pdf", "page": 1}])
        mock_generator.generate.assert_called_once_with("Constructed prompt")

    def test_rag_service_empty_query(self):
        service = RAGService(retriever=MagicMock(), generator=MagicMock())
        with self.assertRaises(ValueError) as ctx:
            service.answer_question("")
        self.assertEqual(str(ctx.exception), "Question must not be empty")

        with self.assertRaises(ValueError) as ctx:
            service.answer_question("   ")
        self.assertEqual(str(ctx.exception), "Question must not be empty")

    def test_rag_service_no_chunks_found(self):
        mock_retriever = MagicMock()
        mock_generator = MagicMock()

        mock_retriever.retrieve.return_value = {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }

        service = RAGService(retriever=mock_retriever, generator=mock_generator)
        with self.assertRaises(ValueError) as ctx:
            service.answer_question("Where is the data?")
        self.assertEqual(str(ctx.exception), "No indexed document chunks were found for this query")


if __name__ == "__main__":
    unittest.main()

