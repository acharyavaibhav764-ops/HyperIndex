import unittest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from api.deps import get_ingestion_service, get_rag_service
from core import GenerationError, StorageError
from main import app
from schemas.document import DocumentIngestItem, DocumentIngestResponse
from schemas.query import QueryResponse, SourceItem
from services.ingestion_service import IngestionService
from services.rag_service import RAGService


class TestApiV1Services(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)
        self.mock_ingestion_service = MagicMock(spec=IngestionService)
        self.mock_rag_service = MagicMock(spec=RAGService)
        app.dependency_overrides[get_ingestion_service] = lambda: self.mock_ingestion_service
        app.dependency_overrides[get_rag_service] = lambda: self.mock_rag_service

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "version": "1.0.0"})

    def test_documents_endpoint_with_mock_service(self):
        mock_response = DocumentIngestResponse(
            message="Documents uploaded and indexed successfully",
            count=1,
            documents=[
                DocumentIngestItem(
                    document_id="doc-uuid-1",
                    filename="sample.pdf",
                    size_bytes=1024,
                    collection="test_collection",
                    total_chunks=3,
                    status="indexed",
                )
            ],
        )
        self.mock_ingestion_service.ingest_files.return_value = mock_response

        files = [("files", ("sample.pdf", b"dummy content", "application/pdf"))]
        response = self.client.post("/api/v1/documents", files=files)

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["documents"][0]["document_id"], "doc-uuid-1")
        self.assertEqual(data["documents"][0]["filename"], "sample.pdf")
        self.mock_ingestion_service.ingest_files.assert_called_once()

    def test_documents_endpoint_validation_error(self):
        self.mock_ingestion_service.ingest_files.side_effect = ValueError("Invalid document structure")
        files = [("files", ("bad.pdf", b"bad content", "application/pdf"))]
        response = self.client.post("/api/v1/documents", files=files)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "Invalid document structure"})

    def test_documents_endpoint_storage_error(self):
        self.mock_ingestion_service.ingest_files.side_effect = StorageError("MinIO connection timeout")
        files = [("files", ("storage_fail.pdf", b"content", "application/pdf"))]
        response = self.client.post("/api/v1/documents", files=files)

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "MinIO connection timeout"})

    def test_query_endpoint_with_mock_service(self):
        mock_response = QueryResponse(
            question="What is this?",
            answer="This is Honeywell automated testing.",
            model="qwen2.5:0.5b",
            sources=[
                SourceItem(metadata={"source": "sample.pdf", "page": 1}, distance=0.12)
            ],
        )
        self.mock_rag_service.answer_question.return_value = mock_response

        response = self.client.post("/api/v1/query", json={"question": "What is this?"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["question"], "What is this?")
        self.assertEqual(data["answer"], "This is Honeywell automated testing.")
        self.assertEqual(data["model"], "qwen2.5:0.5b")
        self.assertEqual(len(data["sources"]), 1)
        self.mock_rag_service.answer_question.assert_called_once_with("What is this?")

    def test_query_endpoint_empty_question(self):
        response = self.client.post("/api/v1/query", json={"question": "   "})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "Question must not be empty"})

    def test_query_endpoint_generation_error(self):
        self.mock_rag_service.answer_question.side_effect = GenerationError("Ollama service unavailable")
        response = self.client.post("/api/v1/query", json={"question": "Trigger error?"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Ollama service unavailable"})


if __name__ == "__main__":
    unittest.main()

