import unittest

from schemas import (
    ChunkItem,
    DocumentIndexResponse,
    DocumentUploadItem,
    DocumentUploadResponse,
)


class TestDocumentSchemas(unittest.TestCase):
    def test_document_upload_item(self):
        item = DocumentUploadItem(document_id="doc-123", filename="manual.pdf", size_bytes=2048)
        self.assertEqual(item.document_id, "doc-123")
        self.assertEqual(item.filename, "manual.pdf")
        self.assertEqual(item.size_bytes, 2048)

        # Test string coercion for integer size_bytes
        item_coerced = DocumentUploadItem(document_id="doc-123", filename="manual.pdf", size_bytes="4096")
        self.assertEqual(item_coerced.size_bytes, 4096)

    def test_document_upload_response(self):
        item = DocumentUploadItem(document_id="doc-1", filename="spec.docx", size_bytes=1000)
        response = DocumentUploadResponse(
            message="Documents uploaded successfully",
            count=1,
            documents=[item],
        )
        self.assertEqual(response.message, "Documents uploaded successfully")
        self.assertEqual(response.count, 1)
        self.assertEqual(len(response.documents), 1)
        self.assertEqual(response.documents[0].document_id, "doc-1")

    def test_chunk_item(self):
        chunk = ChunkItem(chunk_id="doc-1_c0", text="Section 1 text", metadata={"page": 1})
        self.assertEqual(chunk.chunk_id, "doc-1_c0")
        self.assertEqual(chunk.text, "Section 1 text")
        self.assertEqual(chunk.metadata["page"], 1)

    def test_document_index_response(self):
        response = DocumentIndexResponse(
            document_id="doc-abc",
            filename="guide.pdf",
            collection="my_documents",
            total_chunks=10,
            indexed_chunks=10,
        )
        self.assertEqual(response.document_id, "doc-abc")
        self.assertEqual(response.filename, "guide.pdf")
        self.assertEqual(response.collection, "my_documents")
        self.assertEqual(response.total_chunks, 10)
        self.assertEqual(response.indexed_chunks, 10)


if __name__ == "__main__":
    unittest.main()

