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


class TestApiV1PureServices(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)
        self.mock_ingestion_service = MagicMock(spec=IngestionService)
        self.mock_rag_service = MagicMock(spec=RAGService)
        app.dependency_overrides[get_ingestion_service] = lambda: self.mock_ingestion_service
        app.dependency_overrides[get_rag_service] = lambda: self.mock_rag_service

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_health_check(self):
        """Verify health check endpoint returns 200 with status ok."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "version": "1.0.0"})

    def test_documents_ingest_pipeline(self):
        """Verify document upload & ingestion pipeline via pure dependency injection."""
        mock_response = DocumentIngestResponse(
            message="Documents uploaded and indexed successfully",
            count=1,
            documents=[
                DocumentIngestItem(
                    document_id="doc-uuid-pure-1",
                    filename="sample.pdf",
                    size_bytes=2048,
                    collection="test_collection",
                    total_chunks=5,
                    status="indexed",
                )
            ],
        )
        self.mock_ingestion_service.ingest_files.return_value = mock_response

        files = [("files", ("sample.pdf", b"%PDF-1.4 dummy", "application/pdf"))]
        response = self.client.post("/api/v1/documents", files=files)

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["documents"][0]["document_id"], "doc-uuid-pure-1")
        self.assertEqual(data["documents"][0]["filename"], "sample.pdf")
        self.mock_ingestion_service.ingest_files.assert_called_once()

    def test_documents_error_handling(self):
        """Verify error handlers for validation and storage failures during ingestion."""
        # Validation error
        self.mock_ingestion_service.ingest_files.side_effect = ValueError("Invalid format")
        files = [("files", ("bad.txt", b"bad", "text/plain"))]
        response = self.client.post("/api/v1/documents", files=files)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "Invalid format"})

        # Storage error
        self.mock_ingestion_service.ingest_files.side_effect = StorageError("MinIO connection failed")
        response = self.client.post("/api/v1/documents", files=files)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "MinIO connection failed"})

    def test_query_pipeline(self):
        """Verify query pipeline via pure dependency injection."""
        mock_response = QueryResponse(
            question="What is Honeywell Forge?",
            answer="Honeywell Forge is an enterprise performance management software.",
            model="qwen2.5:0.5b",
            sources=[
                SourceItem(metadata={"source": "forge_overview.pdf", "page": 1}, distance=0.08)
            ],
        )
        self.mock_rag_service.answer_question.return_value = mock_response

        response = self.client.post("/api/v1/query", json={"question": "What is Honeywell Forge?"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["question"], "What is Honeywell Forge?")
        self.assertEqual(data["answer"], "Honeywell Forge is an enterprise performance management software.")
        self.assertEqual(data["model"], "qwen2.5:0.5b")
        self.assertEqual(len(data["sources"]), 1)
        self.mock_rag_service.answer_question.assert_called_once_with("What is Honeywell Forge?")

    def test_query_error_handling(self):
        """Verify error handlers for empty questions and generation errors."""
        # Empty question
        response = self.client.post("/api/v1/query", json={"question": "   "})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "Question must not be empty"})

        # Generation error
        self.mock_rag_service.answer_question.side_effect = GenerationError("Ollama failed")
        response = self.client.post("/api/v1/query", json={"question": "Valid query?"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Ollama failed"})

    def test_openapi_contracts(self):
        """Validate OpenAPI schema reflects only pure v1 modern endpoints."""
        schema = app.openapi()
        paths = schema.get("paths", {})

        # Ensure pure v1 routes exist
        self.assertIn("/health", paths)
        self.assertIn("/api/v1/documents", paths)
        self.assertIn("/api/v1/query", paths)

        # Ensure no legacy prototype routes exist
        self.assertNotIn("/upload", paths)
        self.assertNotIn("/chunk-and-embed/{file_id}", paths)
        self.assertNotIn("/generate", paths)


if __name__ == "__main__":
    unittest.main()

