import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


class TestSwaggerDocs(unittest.TestCase):
    def test_docs_are_available_after_application_startup(self):
        with (
            patch("main.Base.metadata.create_all"),
            patch("main.get_uploader") as get_uploader,
        ):
            with TestClient(app) as client:
                docs_response = client.get("/docs")
                schema_response = client.get("/openapi.json")

        get_uploader.return_value.ensure_bucket.assert_called_once()
        self.assertEqual(docs_response.status_code, 200)
        self.assertIn("swagger-ui", docs_response.text.lower())
        self.assertEqual(schema_response.status_code, 200)
        self.assertIn("/health", schema_response.json()["paths"])


if __name__ == "__main__":
    unittest.main()
