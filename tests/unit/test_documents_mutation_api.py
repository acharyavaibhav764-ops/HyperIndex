import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from api.deps import get_document_service, get_uploader
from main import app
from schemas.document import (
    DeleteDocumentResponse,
    DocumentDescription,
)
from services.document_service import DocumentService


class TestDocumentsMutationApi(unittest.TestCase):
    """Integration tests for CRUD v3.0 mutating endpoints (PATCH and DELETE)."""

    def setUp(self):
        self.mock_document_service = MagicMock(spec=DocumentService)
        self.mock_uploader = MagicMock()
        self.mock_uploader.ensure_bucket.return_value = None

        app.dependency_overrides[get_document_service] = lambda: self.mock_document_service
        app.dependency_overrides[get_uploader] = lambda: self.mock_uploader

        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_update_document_metadata_success(self):
        """PATCH /api/v1/documents/{document_id} updates metadata and returns 200."""
        now = datetime.now(timezone.utc)
        updated_doc = DocumentDescription(
            document_id="doc-mut-1",
            filename="honeywell_sensor.pdf",
            product_id="new-product-group",
            size_bytes=4096,
            sha256="hash123",
            total_chunks=10,
            status="indexed",
            created_at=now,
        )
        self.mock_document_service.update_document_metadata.return_value = updated_doc

        response = self.client.patch(
            "/api/v1/documents/doc-mut-1",
            json={"product_id": "new-product-group"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["document_id"], "doc-mut-1")
        self.assertEqual(data["product_id"], "new-product-group")
        self.mock_document_service.update_document_metadata.assert_called_once_with(
            document_id="doc-mut-1",
            product_id="new-product-group",
        )

    def test_update_document_metadata_not_found(self):
        """PATCH /api/v1/documents/{document_id} returns 404 when document does not exist."""
        self.mock_document_service.update_document_metadata.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document with ID 'not-found-id' not found",
        )

        response = self.client.patch(
            "/api/v1/documents/not-found-id",
            json={"product_id": "new-product-group"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.json()["detail"].lower())

    def test_update_document_metadata_validation_error(self):
        """PATCH /api/v1/documents/{document_id} returns 422 on empty or invalid product_id."""
        response = self.client.patch(
            "/api/v1/documents/doc-mut-1",
            json={"product_id": ""},
        )
        self.assertEqual(response.status_code, 422)

    def test_delete_document_success(self):
        """DELETE /api/v1/documents/{document_id} executes cascade and returns 200."""
        delete_resp = DeleteDocumentResponse(
            document_id="doc-del-1",
            status="deleted",
            deleted_chunks=15,
            database_removed=True,
            storage_removed=True,
        )
        self.mock_document_service.delete_document.return_value = delete_resp

        response = self.client.delete("/api/v1/documents/doc-del-1")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["document_id"], "doc-del-1")
        self.assertEqual(data["status"], "deleted")
        self.assertEqual(data["deleted_chunks"], 15)
        self.assertTrue(data["database_removed"])
        self.assertTrue(data["storage_removed"])
        self.mock_document_service.delete_document.assert_called_once_with(document_id="doc-del-1")

    def test_delete_document_not_found(self):
        """DELETE /api/v1/documents/{document_id} returns 404 when document does not exist."""
        self.mock_document_service.delete_document.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document with ID 'missing-id' not found",
        )

        response = self.client.delete("/api/v1/documents/missing-id")
        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.json()["detail"].lower())


if __name__ == "__main__":
    unittest.main()

