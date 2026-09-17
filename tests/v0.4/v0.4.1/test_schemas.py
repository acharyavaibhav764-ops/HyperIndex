import unittest
from pydantic import ValidationError

from schemas import (
    DocumentIngestItem,
    DocumentIngestResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    SourceItem,
)


class TestV041Schemas(unittest.TestCase):
    def test_document_ingest_item(self):
        item = DocumentIngestItem(
            document_id="doc-123",
            filename="honeywell_manual.pdf",
            size_bytes=2048,
            collection="honeywell_docs",
            total_chunks=12,
            status="indexed",
        )
        self.assertEqual(item.document_id, "doc-123")
        self.assertEqual(item.filename, "honeywell_manual.pdf")
        self.assertEqual(item.size_bytes, 2048)
        self.assertEqual(item.collection, "honeywell_docs")
        self.assertEqual(item.total_chunks, 12)
        self.assertEqual(item.status, "indexed")

    def test_document_ingest_item_defaults(self):
        item = DocumentIngestItem(
            document_id="doc-456",
            filename="spec.docx",
            size_bytes=1024,
            collection="honeywell_docs",
            total_chunks=5,
        )
        self.assertEqual(item.status, "indexed")

    def test_document_ingest_response(self):
        item = DocumentIngestItem(
            document_id="doc-123",
            filename="honeywell_manual.pdf",
            size_bytes=2048,
            collection="honeywell_docs",
            total_chunks=12,
        )
        response = DocumentIngestResponse(
            message="Documents uploaded and indexed successfully",
            count=1,
            documents=[item],
        )
        self.assertEqual(response.count, 1)
        self.assertEqual(len(response.documents), 1)
        self.assertEqual(response.documents[0].document_id, "doc-123")

    def test_document_ingest_missing_fields(self):
        with self.assertRaises(ValidationError):
            DocumentIngestItem(
                document_id="doc-123",
                filename="manual.pdf",
            )


if __name__ == "__main__":
    unittest.main()

