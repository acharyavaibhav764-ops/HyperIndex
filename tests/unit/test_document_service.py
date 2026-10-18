import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from fastapi import HTTPException
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

        # 2. Setup mock Chroma retriever and MinIO uploader
        self.mock_retriever = MagicMock()
        self.mock_collection = MagicMock()
        self.mock_retriever.collection = self.mock_collection

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

        # Mock Chroma returning 5 chunks per document
        self.mock_collection.get.return_value = {"ids": ["c1", "c2", "c3", "c4", "c5"]}

        response = self.service.list_documents(product_id="prodA")
        self.assertEqual(response.total_count, 2)
        self.assertEqual(len(response.documents), 2)
        self.assertTrue(all(d.product_id == "prodA" for d in response.documents))
        self.assertEqual(response.documents[0].total_chunks, 5)

    def test_list_documents_name_search_substring(self):
        self._seed_document(document_id="d1", filename="Honeywell_Installation_Guide.pdf", sha256="h1")
        self._seed_document(document_id="d2", filename="Circuit_Schematic.pdf", sha256="h2")
        self.mock_collection.get.return_value = {"ids": ["c1"]}

        response = self.service.list_documents(name_search="installation")
        self.assertEqual(response.total_count, 1)
        self.assertEqual(response.documents[0].filename, "Honeywell_Installation_Guide.pdf")

    def test_list_documents_pagination_skip_and_limit(self):
        for i in range(5):
            self._seed_document(document_id=f"doc-{i}", filename=f"file_{i}.pdf", sha256=f"hash_{i}")
        self.mock_collection.get.return_value = {"ids": []}

        response = self.service.list_documents(limit=2, skip=1)
        self.assertEqual(response.total_count, 5)
        self.assertEqual(len(response.documents), 2)
        self.assertEqual(response.limit, 2)
        self.assertEqual(response.skip, 1)

    def test_get_document_success(self):
        doc = self._seed_document(document_id="target-doc", filename="target.pdf")
        self.mock_collection.get.return_value = {"ids": ["c1", "c2"]}

        detail = self.service.get_document("target-doc")
        self.assertEqual(detail.document_id, "target-doc")
        self.assertEqual(detail.filename, "target.pdf")
        self.assertEqual(detail.total_chunks, 2)
        self.assertEqual(detail.status, "indexed")

    def test_get_document_not_found_raises_404(self):
        with self.assertRaises(HTTPException) as ctx:
            self.service.get_document("non-existent-doc")
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("not found", ctx.exception.detail.lower())

    def test_get_document_chunks_transparency(self):
        self._seed_document(document_id="doc-with-chunks", filename="specs.pdf")

        # Chroma response with documents and metadatas
        self.mock_collection.get.side_effect = [
            # First call for paginated chunks
            {
                "ids": ["doc_c0", "doc_c1"],
                "documents": ["Chunk 0 text content", "Chunk 1 text content"],
                "metadatas": [
                    {"page": 1, "chunk_index": 0, "product_id": "p1"},
                    {"page": 2, "chunk_index": 1, "product_id": "p1"},
                ],
            },
            # Second call for total chunk count
            {"ids": ["doc_c0", "doc_c1"]},
        ]

        chunks_res = self.service.get_document_chunks("doc-with-chunks", limit=10, offset=0)
        self.assertEqual(chunks_res.document_id, "doc-with-chunks")
        self.assertEqual(chunks_res.total_chunks, 2)
        self.assertEqual(len(chunks_res.chunks), 2)
        self.assertEqual(chunks_res.chunks[0].chunk_id, "doc_c0")
        self.assertEqual(chunks_res.chunks[0].text, "Chunk 0 text content")
        self.assertEqual(chunks_res.chunks[0].page, 1)
        self.assertEqual(chunks_res.chunks[1].page, 2)

    def test_update_document_metadata_syncs_sqlite_and_chroma(self):
        self._seed_document(document_id="update-doc", product_id="old-prod")

        self.mock_collection.get.return_value = {
            "ids": ["c0", "c1"],
            "metadatas": [
                {"document_id": "update-doc", "page": 1, "product_id": "old-prod"},
                {"document_id": "update-doc", "page": 2, "product_id": "old-prod"},
            ],
        }

        updated = self.service.update_document_metadata("update-doc", "new-prod")
        self.assertEqual(updated.product_id, "new-prod")

        # Verify SQLite row was updated
        db_doc = self.db.query(Document).filter_by(document_id="update-doc").first()
        self.assertEqual(db_doc.product_id, "new-prod")

        # Verify Chroma collection.update was called with updated metadata
        self.mock_collection.update.assert_called_once_with(
            ids=["c0", "c1"],
            metadatas=[
                {"document_id": "update-doc", "page": 1, "product_id": "new-prod"},
                {"document_id": "update-doc", "page": 2, "product_id": "new-prod"},
            ],
        )

    def test_delete_document_strict_cascade_sequence(self):
        self._seed_document(document_id="cascade-doc")
        self.mock_collection.get.return_value = {"ids": ["chunk1", "chunk2", "chunk3"]}

        res = self.service.delete_document("cascade-doc")

        # 1. Verify Chroma vectors deleted
        self.mock_collection.delete.assert_called_once_with(where={"document_id": "cascade-doc"})
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
        self.mock_collection.get.return_value = {"ids": ["c1"]}

        # Document exists before deletion
        pre_check = self.db.query(Document).filter_by(sha256=unique_hash).first()
        self.assertIsNotNone(pre_check)

        # Delete document
        self.service.delete_document("hash-doc")

        # Hash is now liberated (duplicate check will pass for re-upload)
        post_check = self.db.query(Document).filter_by(sha256=unique_hash).first()
        self.assertIsNone(post_check)


if __name__ == "__main__":
    unittest.main()

