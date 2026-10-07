import unittest
from fastapi.testclient import TestClient

from main import app


class TestApiV1Pure(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "version": "1.0.0"})

    def test_legacy_endpoints_are_removed(self):
        """Verify legacy prototype endpoints return 404 Not Found."""
        self.assertEqual(self.client.post("/upload").status_code, 404)
        self.assertEqual(self.client.post("/chunk-and-embed/test-uuid").status_code, 404)
        self.assertEqual(self.client.post("/generate").status_code, 404)

    def test_openapi_pure_v1_routes(self):
        schema = app.openapi()
        paths = schema.get("paths", {})

        # Ensure pure v1 routes exist
        self.assertIn("/health", paths)
        self.assertIn("/api/v1/documents", paths)
        self.assertIn("/api/v1/query", paths)

        # Ensure no legacy routes exist in OpenAPI
        self.assertNotIn("/upload", paths)
        self.assertNotIn("/chunk-and-embed/{file_id}", paths)
        self.assertNotIn("/generate", paths)


if __name__ == "__main__":
    unittest.main()

