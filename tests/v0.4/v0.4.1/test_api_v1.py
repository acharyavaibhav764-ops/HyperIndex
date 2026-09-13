import unittest
from fastapi.testclient import TestClient

from main import app


class TestApiV1Contracts(unittest.TestCase):
    def setUp(self):
        # Disable lifespan during unit contract tests to avoid external MinIO/Chroma dependencies
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "version": "1.0.0"})

    def test_upload_documents_missing_body(self):
        response = self.client.post("/api/v1/documents")
        self.assertEqual(response.status_code, 422)

    def test_upload_documents_empty_file(self):
        response = self.client.post(
            "/api/v1/documents",
            files=[("files", ("empty.txt", b"", "text/plain"))],
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("empty", response.json().get("detail", "").lower())

    def test_query_validation_error_empty(self):
        response = self.client.post("/api/v1/query", json={"question": ""})
        self.assertEqual(response.status_code, 422)
        errors = response.json().get("detail", [])
        self.assertTrue(any("question" in str(err) for err in errors))

    def test_query_validation_error_missing(self):
        response = self.client.post("/api/v1/query", json={})
        self.assertEqual(response.status_code, 422)

    def test_upload_status_code_contract(self):
        schema = app.openapi()
        upload_post = schema["paths"]["/api/v1/documents"]["post"]
        self.assertIn("201", upload_post["responses"])
        self.assertIn("DocumentUploadResponse", str(upload_post["responses"]["201"]))

    def test_index_document_openapi_contract(self):
        schema = app.openapi()
        index_post = schema["paths"]["/api/v1/documents/{document_id}/index"]["post"]
        self.assertIn("200", index_post["responses"])
        self.assertIn("DocumentIndexResponse", str(index_post["responses"]["200"]))

    def test_openapi_v1_routes(self):
        schema = app.openapi()
        paths = schema.get("paths", {})
        components = schema.get("components", {}).get("schemas", {})

        # Assert v1 paths exist
        self.assertIn("/health", paths)
        self.assertIn("/api/v1/documents", paths)
        self.assertIn("/api/v1/documents/{document_id}/index", paths)
        self.assertIn("/api/v1/query", paths)

        # Assert tags
        self.assertEqual(paths["/health"]["get"]["tags"], ["Health"])
        self.assertEqual(paths["/api/v1/documents"]["post"]["tags"], ["Documents"])
        self.assertEqual(paths["/api/v1/documents/{document_id}/index"]["post"]["tags"], ["Documents"])
        self.assertEqual(paths["/api/v1/query"]["post"]["tags"], ["Query"])

        # Assert Document schemas exist in OpenAPI components
        self.assertIn("DocumentUploadItem", components)
        self.assertIn("DocumentUploadResponse", components)
        self.assertIn("DocumentIndexResponse", components)


if __name__ == "__main__":
    unittest.main()

