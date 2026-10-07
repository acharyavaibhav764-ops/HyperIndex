import unittest
from pydantic import ValidationError

import schemas
from schemas import (
    DocumentIngestItem,
    DocumentIngestResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    SourceItem,
)


class TestV042PureSchemas(unittest.TestCase):
    def test_document_ingest_item(self):
        item = DocumentIngestItem(
            document_id="doc-999",
            filename="honeywell_spec.pdf",
            size_bytes=4096,
            collection="honeywell_docs",
            total_chunks=8,
            status="indexed",
        )
        self.assertEqual(item.document_id, "doc-999")
        self.assertEqual(item.filename, "honeywell_spec.pdf")
        self.assertEqual(item.size_bytes, 4096)
        self.assertEqual(item.collection, "honeywell_docs")
        self.assertEqual(item.total_chunks, 8)
        self.assertEqual(item.status, "indexed")

    def test_document_ingest_response(self):
        item = DocumentIngestItem(
            document_id="doc-999",
            filename="honeywell_spec.pdf",
            size_bytes=4096,
            collection="honeywell_docs",
            total_chunks=8,
        )
        response = DocumentIngestResponse(
            message="Documents uploaded and indexed successfully",
            count=1,
            documents=[item],
        )
        self.assertEqual(response.count, 1)
        self.assertEqual(response.documents[0].document_id, "doc-999")

    def test_legacy_schemas_are_purged(self):
        """Verify prototype schemas are completely removed from the schemas package."""
        self.assertFalse(hasattr(schemas, "FileUploadItem"))
        self.assertFalse(hasattr(schemas, "FileUploadResponse"))
        self.assertFalse(hasattr(schemas, "FileIndexResponse"))
        self.assertFalse(hasattr(schemas, "ChunkItem"))


if __name__ == "__main__":
    unittest.main()

