import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from api.deps import get_document_service, get_uploader
from main import app
from schemas.document import (
    ChunkDescription,
    DocumentDescription,
    GetDocumentChunksResponse,
    GetDocumentsResponse,
)
from services.document_service import DocumentService


class TestDocumentsReadApi(unittest.TestCase):
    """Integration tests for CRUD v2.0 read endpoints in api/v1/endpoints/documents.py."""

    def setUp(self):
        self.mock_document_service = MagicMock(spec=DocumentService)
        self.mock_uploader = MagicMock()
        self.mock_uploader.ensure_bucket.return_value = None

        app.dependency_overrides[get_document_service] = lambda: self.mock_document_service
        app.dependency_overrides[get_uploader] = lambda: self.mock_uploader

        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_list_documents_empty(self):
        """GET /api/v1/documents returns empty list when no documents match."""
        mock_response = GetDocumentsResponse(
            documents=[],
            total_count=0,
            limit=50,
            skip=0,
        )
        self.mock_document_service.list_documents.return_value = mock_response

        response = self.client.get("/api/v1/documents")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total_count"], 0)
        self.assertEqual(data["documents"], [])
        self.assertEqual(data["limit"], 50)
        self.assertEqual(data["skip"], 0)

    def test_list_documents_with_query_params(self):
        """GET /api/v1/documents passes query filters correctly to DocumentService."""
        now = datetime.now(timezone.utc)
        doc1 = DocumentDescription(
            document_id="doc-123",
            filename="honeywell_manual.pdf",
            product_id="thermostat_v1",
            size_bytes=1024,
            sha256="abc123hash",
            total_chunks=12,
            status="indexed",
            created_at=now,
        )
        self.mock_document_service.list_documents.return_value = GetDocumentsResponse(
            documents=[doc1],
            total_count=1,
            limit=10,
            skip=5,
        )

        response = self.client.get(
            "/api/v1/documents",
            params={
                "product_id": "thermostat_v1",
                "name_search": "manual",
                "limit": 10,
                "skip": 5,
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total_count"], 1)
        self.assertEqual(len(data["documents"]), 1)
        self.assertEqual(data["documents"][0]["document_id"], "doc-123")
        self.assertEqual(data["documents"][0]["filename"], "honeywell_manual.pdf")
        self.mock_document_service.list_documents.assert_called_once_with(
            product_id="thermostat_v1",
            name_search="manual",
            status=None,
            uploaded_after=None,
            uploaded_before=None,
            limit=10,
            skip=5,
        )

    def test_get_document_success(self):
        """GET /api/v1/documents/{document_id} returns document metadata."""
        now = datetime.now(timezone.utc)
        doc = DocumentDescription(
            document_id="doc-456",
            filename="specifications.pdf",
            product_id="sensor_a",
            size_bytes=2048,
            sha256="def456hash",
            total_chunks=8,
            status="indexed",
            created_at=now,
        )
        self.mock_document_service.get_document.return_value = doc

        response = self.client.get("/api/v1/documents/doc-456")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["document_id"], "doc-456")
        self.assertEqual(data["filename"], "specifications.pdf")
        self.assertEqual(data["product_id"], "sensor_a")
        self.assertEqual(data["total_chunks"], 8)
        self.mock_document_service.get_document.assert_called_once_with(document_id="doc-456")

    def test_get_document_not_found(self):
        """GET /api/v1/documents/{document_id} returns 404 for non-existent document."""
        self.mock_document_service.get_document.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document with ID 'non-existent' not found",
        )

        response = self.client.get("/api/v1/documents/non-existent")
        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.json()["detail"].lower())

    def test_get_document_chunks_success(self):
        """GET /api/v1/documents/{document_id}/chunks returns chunk details and text."""
        chunk1 = ChunkDescription(
            chunk_id="doc-789_c0",
            chunk_index=0,
            page=1,
            text="First paragraph of Honeywell documentation.",
            metadata={"filename": "doc.pdf", "page": 1, "product_id": "p1"},
        )
        chunk2 = ChunkDescription(
            chunk_id="doc-789_c1",
            chunk_index=1,
            page=2,
            text="Second paragraph of Honeywell documentation.",
            metadata={"filename": "doc.pdf", "page": 2, "product_id": "p1"},
        )
        self.mock_document_service.get_document_chunks.return_value = GetDocumentChunksResponse(
            document_id="doc-789",
            filename="doc.pdf",
            total_chunks=2,
            chunks=[chunk1, chunk2],
        )

        response = self.client.get("/api/v1/documents/doc-789/chunks?limit=20&offset=0")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["document_id"], "doc-789")
        self.assertEqual(data["total_chunks"], 2)
        self.assertEqual(len(data["chunks"]), 2)
        self.assertEqual(data["chunks"][0]["chunk_id"], "doc-789_c0")
        self.assertEqual(data["chunks"][0]["text"], "First paragraph of Honeywell documentation.")
        self.mock_document_service.get_document_chunks.assert_called_once_with(
            document_id="doc-789",
            limit=20,
            offset=0,
        )

    def test_get_document_chunks_not_found(self):
        """GET /api/v1/documents/{document_id}/chunks returns 404 if document does not exist."""
        self.mock_document_service.get_document_chunks.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document with ID 'missing' not found",
        )

        response = self.client.get("/api/v1/documents/missing/chunks")
        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.json()["detail"].lower())

    def test_schema_isolation_cleanliness(self):
        """Verify that DocumentIngestItem and DocumentIngestResponse are purged from schemas.document."""
        import schemas.document as doc_schema

        self.assertFalse(
            hasattr(doc_schema, "DocumentIngestItem"),
            "DocumentIngestItem should no longer be present in schemas.document",
        )
        self.assertFalse(
            hasattr(doc_schema, "DocumentIngestResponse"),
            "DocumentIngestResponse should no longer be present in schemas.document",
        )


if __name__ == "__main__":
    unittest.main()

