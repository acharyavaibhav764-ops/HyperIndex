import unittest
from fastapi.testclient import TestClient

from main import app


class TestApiV1(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "version": "1.0.0"})

    def test_ingest_documents_empty(self):
        response = self.client.post("/api/v1/documents", files=[])
        self.assertIn(response.status_code, [400, 422])

    def test_query_validation_error_empty(self):
        response = self.client.post("/api/v1/query", json={"question": ""})
        self.assertEqual(response.status_code, 422)

    def test_query_validation_error_missing(self):
        response = self.client.post("/api/v1/query", json={})
        self.assertEqual(response.status_code, 422)

    def test_openapi_v1_routes(self):
        schema = app.openapi()
        paths = schema.get("paths", {})
        components = schema.get("components", {}).get("schemas", {})

        # Ensure modern routes exist
        self.assertIn("/health", paths)
        self.assertIn("/api/v1/documents", paths)
        self.assertIn("/api/v1/query", paths)

        # Ensure schemas are registered
        self.assertIn("DocumentIngestItem", components)
        self.assertIn("DocumentIngestResponse", components)
        self.assertIn("QueryRequest", components)
        self.assertIn("QueryResponse", components)
        self.assertIn("HealthResponse", components)

        # Check /api/v1/documents status code is 201
        doc_post = paths["/api/v1/documents"]["post"]
        self.assertIn("201", doc_post["responses"])
        self.assertIn("DocumentIngestResponse", str(doc_post["responses"]["201"]))

        # Check /api/v1/query status code is 200
        query_post = paths["/api/v1/query"]["post"]
        self.assertIn("200", query_post["responses"])
        self.assertIn("QueryResponse", str(query_post["responses"]["200"]))


if __name__ == "__main__":
    unittest.main()

