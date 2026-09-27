import asyncio
from io import BytesIO
import unittest
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.v1.endpoints import documents as documents_endpoint
from db.database import Base
from db.models import DocumentVersion


class FakeFile:
    def __init__(self, filename: str, content: bytes) -> None:
        self.filename = filename
        self.content_type = "text/plain"
        self.file = BytesIO(content)

    async def read(self) -> bytes:
        return self.file.read()

    async def seek(self, position: int) -> None:
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
        return ["chunk"], [{"filename": filename, "page": 1}], [f"{document_id}_0"]


class FakeEmbeddings:
    def embed(self, chunks: list[str]) -> list[list[float]]:
        return [[0.1] for _ in chunks]


class FakeRetriever:
    collection_name = "test"

    def upsert(self, **kwargs: object) -> None:
        pass


class TestDuplicateUploads(unittest.TestCase):
    def test_identical_files_in_one_request_are_only_stored_once(self) -> None:
        original_services = (
            documents_endpoint.uploader,
            documents_endpoint.parser,
            documents_endpoint.chunker,
            documents_endpoint.embeddings,
            documents_endpoint.retriever,
        )
        uploader = FakeUploader()
        documents_endpoint.uploader = uploader
        documents_endpoint.parser = FakeParser()
        documents_endpoint.chunker = FakeChunker()
        documents_endpoint.embeddings = FakeEmbeddings()
        documents_endpoint.retriever = FakeRetriever()

        engine = create_engine("sqlite://", poolclass=StaticPool)
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        db = session_factory()

        try:
            content = b"same exact document bytes"
            response = asyncio.run(
                documents_endpoint.ingest_documents(
                    [
                        FakeFile("manual-a.txt", content),
                        FakeFile("manual-b.txt", content),
                        FakeFile("manual-c.txt", content),
                    ],
                    "product-test",
                    db,
                )
            )

            self.assertEqual(
                [item.status for item in response.documents],
                ["indexed", "duplicate", "duplicate"],
            )
            self.assertEqual(len({item.document_id for item in response.documents}), 1)
            self.assertEqual(uploader.upload_calls, 1)
            self.assertEqual(db.query(DocumentVersion).count(), 1)
        finally:
            db.close()
            engine.dispose()
            (
                documents_endpoint.uploader,
                documents_endpoint.parser,
                documents_endpoint.chunker,
                documents_endpoint.embeddings,
                documents_endpoint.retriever,
            ) = original_services