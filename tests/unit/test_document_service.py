import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from qdrant_client import QdrantClient, models
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from db.database import Base
from db.models.document import Document
from services.document_service import DocumentService


class TestDocumentService(unittest.TestCase):
    """Unit tests for DocumentService multi-store orchestration with SQLite in-memory."""

    def setUp(self):
        # 1. Setup in-memory SQLite database
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self.db: Session = self.SessionLocal()

        # 2. Setup mock Qdrant retriever and MinIO uploader
        self.mock_retriever = MagicMock()
        self.mock_client = MagicMock()
        self.mock_retriever.client = self.mock_client
        self.mock_retriever.collection_name = "test_collection"

        self.mock_uploader = MagicMock()
        self.mock_uploader.bucket_name = "test-honeywell-bucket"
        self.mock_s3_client = MagicMock()
        self.mock_uploader.client = self.mock_s3_client

        # 3. Instantiate DocumentService
        self.service = DocumentService(
            db=self.db,
            retriever=self.mock_retriever,
            uploader=self.mock_uploader,
        )

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def _seed_document(
        self,
        document_id: str = "doc-1",
        product_id: str = "product-A",
        filename: str = "sample.pdf",
        sha256: str = "hash123",
        size_bytes: int = 1024,
        created_at: datetime | None = None,
    ) -> Document:
        doc = Document(
            document_id=document_id,
            product_id=product_id,
            filename=filename,
            sha256=sha256,
            size_bytes=size_bytes,
            created_at=created_at or datetime.now(timezone.utc),
        )
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)
        return doc

    def test_list_documents_filtering_by_product_id(self):
        self._seed_document(document_id="d1", product_id="prodA", filename="a1.pdf", sha256="h1")
        self._seed_document(document_id="d2", product_id="prodA", filename="a2.pdf", sha256="h2")
        self._seed_document(document_id="d3", product_id="prodB", filename="b1.pdf", sha256="h3")

        # Mock Qdrant returning 5 chunks per document
        self.mock_client.count.return_value = models.CountResult(count=5)

        response = self.service.list_documents(product_id="prodA")
        self.assertEqual(response.total_count, 2)
        self.assertEqual(len(response.documents), 2)
        self.assertTrue(all(d.product_id == "prodA" for d in response.documents))
        self.assertEqual(response.documents[0].total_chunks, 5)

    def test_list_documents_name_search_substring(self):
        self._seed_document(document_id="d1", filename="Honeywell_Installation_Guide.pdf", sha256="h1")
        self._seed_document(document_id="d2", filename="Circuit_Schematic.pdf", sha256="h2")
        self.mock_client.count.return_value = models.CountResult(count=1)

        response = self.service.list_documents(name_search="installation")
        self.assertEqual(response.total_count, 1)
        self.assertEqual(response.documents[0].filename, "Honeywell_Installation_Guide.pdf")

    def test_list_documents_pagination_skip_and_limit(self):
        for i in range(5):
            self._seed_document(document_id=f"doc-{i}", filename=f"file_{i}.pdf", sha256=f"hash_{i}")
        self.mock_client.count.return_value = models.CountResult(count=0)

        response = self.service.list_documents(limit=2, skip=1)
        self.assertEqual(response.total_count, 5)
        self.assertEqual(len(response.documents), 2)
        self.assertEqual(response.limit, 2)
        self.assertEqual(response.skip, 1)

    def test_get_document_success(self):
        doc = self._seed_document(document_id="target-doc", filename="target.pdf")
        self.mock_client.count.return_value = models.CountResult(count=2)

        detail = self.service.get_document("target-doc")
        self.assertEqual(detail.document_id, "target-doc")
        self.assertEqual(detail.filename, "target.pdf")
        self.assertEqual(detail.total_chunks, 2)
        self.assertEqual(detail.status, "indexed")
        self.mock_client.count.assert_called_once_with(
            collection_name="test_collection",
            count_filter=models.Filter(must=[models.FieldCondition(
                key="document_id", match=models.MatchValue(value="target-doc"),
            )]),
            exact=True,
        )

    def test_get_document_not_found_raises_404(self):
        with self.assertRaises(HTTPException) as ctx:
            self.service.get_document("non-existent-doc")
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("not found", ctx.exception.detail.lower())

    def test_get_document_chunks_transparency(self):
        self._seed_document(document_id="doc-with-chunks", filename="specs.pdf")

        # Qdrant response with text and metadata payloads
        self.mock_client.scroll.return_value = ([
            models.Record(id=i, payload={
                "chunk_id": f"doc_c{i}", "text": f"Chunk {i} text content",
                "page": i + 1, "chunk_index": i, "product_id": "p1",
            }) for i in range(2)
        ], None)
        self.mock_client.count.return_value = models.CountResult(count=2)

        chunks_res = self.service.get_document_chunks("doc-with-chunks", limit=10, offset=0)
        self.assertEqual(chunks_res.document_id, "doc-with-chunks")
        self.assertEqual(chunks_res.total_chunks, 2)
        self.assertEqual(len(chunks_res.chunks), 2)
        self.assertEqual(chunks_res.chunks[0].chunk_id, "doc_c0")
        self.assertEqual(chunks_res.chunks[0].text, "Chunk 0 text content")
        self.assertEqual(chunks_res.chunks[0].page, 1)
        self.assertEqual(chunks_res.chunks[1].page, 2)
        self.assertNotIn("text", chunks_res.chunks[0].metadata)
        self.assertIsNone(self.mock_client.scroll.call_args.kwargs["offset"])

    def test_update_document_metadata_syncs_sqlite_and_qdrant(self):
        self._seed_document(document_id="update-doc", product_id="old-prod")

        self.mock_client.count.return_value = models.CountResult(count=2)

        updated = self.service.update_document_metadata("update-doc", "new-prod")
        self.assertEqual(updated.product_id, "new-prod")

        # Verify SQLite row was updated
        db_doc = self.db.query(Document).filter_by(document_id="update-doc").first()
        self.assertEqual(db_doc.product_id, "new-prod")

        # Verify Qdrant set_payload was called with updated metadata
        self.mock_client.set_payload.assert_called_once_with(
            collection_name="test_collection",
            payload={"product_id": "new-prod"},
            points=models.Filter(must=[models.FieldCondition(
                key="document_id", match=models.MatchValue(value="update-doc"),
            )]),
            wait=True,
        )
        self.assertEqual(updated.total_chunks, 2)
        self.mock_client.scroll.assert_not_called()

    def test_delete_document_strict_cascade_sequence(self):
        self._seed_document(document_id="cascade-doc")
        self.mock_client.count.return_value = models.CountResult(count=3)

        sequence = MagicMock()
        sequence.attach_mock(self.mock_client.delete, "vectors")
        sequence.attach_mock(self.mock_s3_client.delete_object, "storage")
        with patch.object(self.db, "commit", wraps=self.db.commit) as commit:
            sequence.attach_mock(commit, "sql_commit")
            res = self.service.delete_document("cascade-doc")
        self.assertEqual([call[0] for call in sequence.mock_calls], ["vectors", "sql_commit", "storage"])

        # 1. Verify Qdrant vectors deleted
        self.mock_client.delete.assert_called_once_with(
            collection_name="test_collection",
            points_selector=models.FilterSelector(filter=models.Filter(must=[models.FieldCondition(
                key="document_id", match=models.MatchValue(value="cascade-doc"),
            )])),
            wait=True,
        )
        self.assertEqual(res.deleted_chunks, 3)

        # 2. Verify SQLite row deleted
        db_doc = self.db.query(Document).filter_by(document_id="cascade-doc").first()
        self.assertIsNone(db_doc)
        self.assertTrue(res.database_removed)

        # 3. Verify MinIO binary deleted
        self.mock_s3_client.delete_object.assert_called_once_with(
            Bucket="test-honeywell-bucket",
            Key="cascade-doc",
        )
        self.assertTrue(res.storage_removed)
        self.assertEqual(res.status, "deleted")

    def test_delete_document_liberates_sha256_hash(self):
        unique_hash = "f7c3bc1d808e04732adf679965ccc34ca7ae3441"
        self._seed_document(document_id="hash-doc", sha256=unique_hash)
        self.mock_client.count.return_value = models.CountResult(count=1)

        # Document exists before deletion
        pre_check = self.db.query(Document).filter_by(sha256=unique_hash).first()
        self.assertIsNotNone(pre_check)

        # Delete document
        self.service.delete_document("hash-doc")

        # Hash is now liberated (duplicate check will pass for re-upload)
        post_check = self.db.query(Document).filter_by(sha256=unique_hash).first()
        self.assertIsNone(post_check)

    def test_missing_documents_do_not_call_qdrant(self):
        for operation in (
            lambda: self.service.get_document_chunks("missing"),
            lambda: self.service.update_document_metadata("missing", "new"),
            lambda: self.service.delete_document("missing"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                operation()
            self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(self.mock_client.mock_calls, [])

    def test_delete_failure_preserves_sql_and_storage(self):
        self._seed_document()
        self.mock_client.count.return_value = models.CountResult(count=1)
        self.mock_client.delete.side_effect = RuntimeError("Qdrant unavailable")
        with self.assertRaises(RuntimeError):
            self.service.delete_document("doc-1")
        self.assertIsNotNone(self.db.get(Document, "doc-1"))
        self.mock_s3_client.delete_object.assert_not_called()

    def test_delete_without_vectors_and_storage_failure(self):
        self._seed_document()
        self.mock_client.count.return_value = models.CountResult(count=0)
        self.mock_s3_client.delete_object.side_effect = RuntimeError("MinIO unavailable")
        result = self.service.delete_document("doc-1")
        self.assertEqual(result.deleted_chunks, 0)
        self.assertTrue(result.database_removed)
        self.assertFalse(result.storage_removed)
        self.mock_client.delete.assert_not_called()

    def test_real_qdrant_pagination_and_document_isolation(self):
        from core.retriever import Retriever

        client = QdrantClient(":memory:")
        self.addCleanup(client.close)
        embeddings = MagicMock()
        embeddings.embed.return_value = [[1.0, 0.0]]
        retriever = Retriever(embeddings, client, "test_collection")
        service = DocumentService(self.db, retriever, self.mock_uploader)
        for document_id, count in [("target", 260), ("other", 2)]:
            self._seed_document(document_id=document_id, sha256=document_id)
            retriever.upsert(
                [f"{document_id}_c{i}" for i in range(count)],
                [f"Text {i}" for i in range(count)],
                [{"document_id": document_id, "chunk_index": i, "page": 1,
                  "product_id": "old", "page_numbers": [1, 2]} for i in range(count)],
                [[1.0, 0.0]] * count,
            )

        full = service.get_document_chunks("target", limit=300)
        for offset in (0, 1, 256, 259, 260, 500):
            with self.subTest(offset=offset):
                page = service.get_document_chunks("target", limit=2, offset=offset)
                self.assertEqual(page.total_chunks, 260)
                self.assertEqual(page.chunks, full.chunks[offset:offset + 2])
        updated = service.update_document_metadata("target", "new")
        self.assertEqual(updated.total_chunks, 260)
        chunks = service.get_document_chunks("target", limit=300).chunks
        self.assertTrue(all(chunk.metadata["product_id"] == "new" for chunk in chunks))
        self.assertEqual(chunks[0].metadata["page_numbers"], [1, 2])
        self.assertEqual(chunks[0].text, full.chunks[0].text)
        self.assertEqual(service.get_document_chunks("other").chunks[0].metadata["product_id"], "old")
        result = service.delete_document("target")
        self.assertEqual(result.deleted_chunks, 260)
        self.assertEqual(client.count("test_collection").count, 2)
        self.assertIsNone(self.db.get(Document, "target"))
        self.assertIsNotNone(self.db.get(Document, "other"))

    def test_chunk_payload_fallback(self):
        self._seed_document()
        self.mock_client.count.return_value = models.CountResult(count=1)
        self.mock_client.scroll.return_value = ([models.Record(id=42, payload=None)], None)
        chunk = self.service.get_document_chunks("doc-1").chunks[0]
        self.assertEqual(chunk.chunk_id, "42")
        self.assertEqual(chunk.text, "")
        self.assertEqual(chunk.metadata, {})


if __name__ == "__main__":
    unittest.main()
