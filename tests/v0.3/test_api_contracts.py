import unittest
from fastapi.testclient import TestClient

from main import app


class TestApiContracts(unittest.TestCase):
    def setUp(self):
        # Disable lifespan during unit contract tests to avoid external MinIO/Chroma dependencies
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_health_endpoint_contract(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data, {"status": "ok", "version": "1.0.0"})

    def test_generate_validation_error_empty_question(self):
        response = self.client.post("/generate", json={"question": ""})
        self.assertEqual(response.status_code, 422)
        errors = response.json().get("detail", [])
        self.assertTrue(any("question" in str(err) for err in errors))

    def test_generate_validation_error_missing_body(self):
        response = self.client.post("/generate", json={})
        self.assertEqual(response.status_code, 422)

    def test_openapi_schema_definitions(self):
        schema = app.openapi()
        components = schema.get("components", {}).get("schemas", {})

        # Ensure all models are formally registered in OpenAPI
        self.assertIn("FileUploadItem", components)
        self.assertIn("FileUploadResponse", components)
        self.assertIn("FileIndexResponse", components)
        self.assertIn("QueryRequest", components)
        self.assertIn("QueryResponse", components)
        self.assertIn("HealthResponse", components)

        # Verify /health route response schema binding
        health_responses = schema["paths"]["/health"]["get"]["responses"]["200"]
        self.assertIn("$ref", str(health_responses))
        self.assertIn("HealthResponse", str(health_responses))

        # Verify /upload route response schema binding
        upload_responses = schema["paths"]["/upload"]["post"]["responses"]["200"]
        self.assertIn("$ref", str(upload_responses))
        self.assertIn("FileUploadResponse", str(upload_responses))

        # Verify /chunk-and-embed/{file_id} route response schema binding
        chunk_responses = schema["paths"]["/chunk-and-embed/{file_id}"]["post"]["responses"]["200"]
        self.assertIn("$ref", str(chunk_responses))
        self.assertIn("FileIndexResponse", str(chunk_responses))

        # Verify /generate route response and request schema bindings
        gen_post = schema["paths"]["/generate"]["post"]
        self.assertIn("QueryRequest", str(gen_post["requestBody"]))
        self.assertIn("QueryResponse", str(gen_post["responses"]["200"]))


if __name__ == "__main__":
    unittest.main()
