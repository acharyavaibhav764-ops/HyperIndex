import unittest
from pydantic import ValidationError

from schemas import (
    ChunkItem,
    FileIndexResponse,
    FileUploadItem,
    FileUploadResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    SourceItem,
)


class TestSchemas(unittest.TestCase):
    def test_file_upload_item(self):
        item = FileUploadItem(file_id="abc-123", filename="test.pdf", size_bytes=1024)
        self.assertEqual(item.file_id, "abc-123")
        self.assertEqual(item.filename, "test.pdf")
        self.assertEqual(item.size_bytes, 1024)

        # Test string coercion for integer size
        item_coerced = FileUploadItem(file_id="abc-123", filename="test.pdf", size_bytes="2048")
        self.assertEqual(item_coerced.size_bytes, 2048)

    def test_file_upload_response(self):
        response = FileUploadResponse(
            message="Files uploaded successfully",
            count=1,
            files=[
                FileUploadItem(file_id="file-1", filename="doc.pdf", size_bytes=500)
            ],
        )
        self.assertEqual(response.count, 1)
        self.assertEqual(len(response.files), 1)
        self.assertEqual(response.files[0].file_id, "file-1")

    def test_chunk_item(self):
        chunk = ChunkItem(chunk_id="file-1_c0", text="Sample text", metadata={"page": 1})
        self.assertEqual(chunk.chunk_id, "file-1_c0")
        self.assertEqual(chunk.text, "Sample text")
        self.assertEqual(chunk.metadata["page"], 1)

    def test_file_index_response(self):
        response = FileIndexResponse(
            file_id="file-123",
            filename="document.docx",
            collection="test_collection",
            total_chunks=15,
            indexed_chunks=15,
        )
        self.assertEqual(response.file_id, "file-123")
        self.assertEqual(response.total_chunks, 15)
        self.assertEqual(response.indexed_chunks, 15)

    def test_query_request_valid(self):
        request = QueryRequest(question="What is the operating temperature?")
        self.assertEqual(request.question, "What is the operating temperature?")

    def test_query_request_empty_validation_error(self):
        with self.assertRaises(ValidationError):
            QueryRequest(question="")

    def test_query_request_missing_field(self):
        with self.assertRaises(ValidationError):
            QueryRequest()

    def test_query_response(self):
        source = SourceItem(metadata={"filename": "doc.pdf", "page": 2}, distance=0.15)
        response = QueryResponse(
            question="What is this?",
            answer="This is a test answer.",
            model="llama3.2:3b",
            sources=[source],
        )
        self.assertEqual(response.model, "llama3.2:3b")
        self.assertEqual(len(response.sources), 1)
        self.assertEqual(response.sources[0].distance, 0.15)

    def test_health_response_defaults(self):
        response = HealthResponse()
        self.assertEqual(response.status, "ok")
        self.assertEqual(response.version, "1.0.0")

    def test_health_response_custom(self):
        response = HealthResponse(status="degraded", version="2.0.0")
        self.assertEqual(response.status, "degraded")
        self.assertEqual(response.version, "2.0.0")


if __name__ == "__main__":
    unittest.main()
