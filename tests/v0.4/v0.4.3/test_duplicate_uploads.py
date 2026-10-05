from io import BytesIO
import unittest
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.database import Base
from db.models import Document
from services.ingestion_service import IngestionService


class FakeFile:
    def __init__(self, filename: str, content: bytes) -> None:
        self.filename = filename
        self.content_type = "text/plain"
        self.file = BytesIO(content)

    def read(self) -> bytes:
        return self.file.read()

    def seek(self, position: int) -> None:
        self.file.seek(position)


class FakeUploader:
    def __init__(self) -> None:
        self.upload_calls = 0
        self.contents: dict[str, bytes] = {}

    def upload_files(self, files: list[FakeFile]) -> list[dict[str, object]]:
        uploaded = []
        for file in files:
            document_id = str(uuid4())
            content = file.file.getvalue()
            self.contents[document_id] = content
            self.upload_calls += 1
            uploaded.append(
                {
                    "document_id": document_id,
                    "filename": file.filename,
                    "size_bytes": len(content),
                }
            )
        return uploaded

    def download_file(self, document_id: str) -> tuple[bytes, str]:
        return self.contents[document_id], document_id


class FakeParser:
    def parse(self, content: bytes, filename: str) -> list[dict[str, object]]:
        return [{"text": content.decode(), "page": 1}]


class FakeChunker:
    def split(
        self, pages: list[dict[str, object]], document_id: str, filename: str
    ) -> tuple[list[str], list[dict[str, object]], list[str]]:
        return (
            [pages[0]["text"]],
            [{"source": filename, "page": 1, "document_id": document_id}],
            [f"{document_id}_chunk_0"],
        )


class FakeEmbeddings:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3]]


class FakeRetriever:
    collection_name = "test"

    def upsert(self, **kwargs: object) -> None:
        pass


class TestDuplicateUploads(unittest.TestCase):
    def setUp(self) -> None:
        self.uploader = FakeUploader()
        self.parser = FakeParser()
        self.chunker = FakeChunker()
        self.embeddings = FakeEmbeddings()
        self.retriever = FakeRetriever()

        self.engine = create_engine("sqlite://", poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        session_factory = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self.db = session_factory()

        self.service = IngestionService(
            uploader=self.uploader,
            parser=self.parser,
            chunker=self.chunker,
            embeddings=self.embeddings,
            retriever=self.retriever,
            db=self.db,
        )

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_identical_files_in_one_request_are_only_stored_once(self) -> None:
        content = b"same exact document bytes"
        response = self.service.ingest_files(
            [
                FakeFile("manual-a.txt", content),
                FakeFile("manual-b.txt", content),
                FakeFile("manual-c.txt", content),
            ],
            product_id="product-test",
        )

        self.assertEqual(
            [item.status for item in response.documents],
            ["indexed", "duplicate", "duplicate"],
        )
        self.assertEqual(len({item.document_id for item in response.documents}), 1)
        self.assertEqual(self.uploader.upload_calls, 1)
        self.assertEqual(self.db.query(Document).count(), 1)

    def test_same_file_can_be_uploaded_for_different_products(self) -> None:
        content = b"same exact bytes for two products"
        first_response = self.service.ingest_files(
            [FakeFile("manual.txt", content)], product_id="product-a"
        )
        second_response = self.service.ingest_files(
            [FakeFile("manual.txt", content)], product_id="product-b"
        )

        self.assertEqual(first_response.documents[0].status, "indexed")
        self.assertEqual(second_response.documents[0].status, "indexed")
        self.assertNotEqual(
            first_response.documents[0].document_id,
            second_response.documents[0].document_id,
        )
        self.assertEqual(self.uploader.upload_calls, 2)
        self.assertEqual(self.db.query(Document).count(), 2)


if __name__ == "__main__":
    unittest.main()