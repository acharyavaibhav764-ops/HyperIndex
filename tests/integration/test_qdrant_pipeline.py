import io
import json
from dataclasses import replace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from fastapi import UploadFile
from fastapi.testclient import TestClient
from pptx import Presentation
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer
from sentence_transformers.models import BoW
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from tokenizers import Tokenizer, models, pre_tokenizers
from transformers import PreTrainedTokenizerFast

from api.deps import get_ingestion_service, get_rag_service
from core import Chunker, Embeddings, Generator, ParserRouter, Retriever
from core import pipeline_config
from db.database import Base
from db.models.document import Document
from main import app
from services.ingestion_service import IngestionService
from services.rag_service import RAGService


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    # Local models keep parsing and vector generation real without downloads.
    vocab = ["[UNK]", "power", "supply", "voltage", "24", "alarm", "reset", "button"]
    model_path = tmp_path / "embeddings"
    SentenceTransformer(modules=[BoW(vocab)]).save(str(model_path))
    embeddings = Embeddings(model_name=str(model_path), device="cpu")
    tokenizer = Tokenizer(models.WordLevel({word: i for i, word in enumerate(vocab)}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    chunk_tokenizer = HuggingFaceTokenizer(
        tokenizer=PreTrainedTokenizerFast(tokenizer_object=tokenizer, unk_token="[UNK]"),
        max_tokens=64,
    )
    monkeypatch.setattr(pipeline_config, "pipeline_settings", replace(
        pipeline_config.pipeline_settings,
        chunker_tokenizer=chunk_tokenizer,
        enable_picture_description=False,
    ))

    client = QdrantClient(":memory:")
    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    retriever = Retriever(embeddings, client, "pipeline_test")
    stored = {}
    uploader = MagicMock()

    def upload(files):
        file = files[0]
        document_id = str(uuid4())
        content = file.file.read()
        stored[document_id] = (content, file.filename)
        return [{"document_id": document_id, "filename": file.filename, "size_bytes": len(content)}]

    uploader.upload_files.side_effect = upload
    uploader.download_file.side_effect = lambda document_id: stored[document_id]
    ingestion = IngestionService(uploader, ParserRouter(), Chunker(), embeddings, retriever, db)
    generator = Generator()
    rag = RAGService(retriever, generator, retrieval_k=1)
    try:
        yield ingestion, rag, client, db, uploader
    finally:
        db.close()
        engine.dispose()
        client.close()


@pytest.fixture
def document_bytes():
    slides = Presentation()
    for title, text in [
        ("Power supply", "The power supply voltage is 24 volts."),
        ("Alarm reset", "Press the alarm reset button to clear the alarm."),
    ]:
        slide = slides.slides.add_slide(slides.slide_layouts[1])
        slide.shapes.title.text = title
        slide.placeholders[1].text = text
    buffer = io.BytesIO()
    slides.save(buffer)
    return buffer.getvalue()


def ingest(ingestion, content, product_id="SEM-IP"):
    return ingestion.ingest_files(
        [UploadFile(filename="manual.pptx", file=io.BytesIO(content))], product_id=product_id,
    ).documents[0]


def test_end_to_end_ingestion_and_retrieval(pipeline, document_bytes):
    ingestion, rag, client, db, _ = pipeline
    result = ingest(ingestion, document_bytes)
    assert result.status == "indexed"
    assert result.total_chunks >= 2
    assert client.count("pipeline_test").count == result.total_chunks
    points, _ = client.scroll("pipeline_test", limit=100, with_vectors=True)
    assert {point.payload["page"] for point in points} == {1, 2}
    for point in points:
        payload = point.payload
        assert payload["document_id"] == result.document_id
        assert payload["product_id"] == "SEM-IP"
        assert payload["filename"] == "manual.pptx"
        assert payload["chunk_id"] == f"{result.document_id}_c{payload['chunk_index']}"
        assert str(point.id) == rag.retriever.chunk_id_to_uuid(payload["chunk_id"])
        assert payload["text"]
        assert point.vector
    assert db.get(Document, result.document_id).product_id == "SEM-IP"

    with patch("core.generator.urlopen") as request:
        request.return_value.__enter__.return_value.read.return_value = json.dumps({
            "response": "24 volts. [Doc: manual.pptx, Page: 1]",
        }).encode()
        answer = rag.answer_question("power supply voltage")
    payload = json.loads(request.call_args.args[0].data)
    assert "24 volts" in payload["prompt"]
    assert "manual.pptx | Page 1" in payload["prompt"]
    assert "power supply voltage" in payload["prompt"]
    assert answer.answer == "24 volts. [Doc: manual.pptx, Page: 1]"
    assert len(answer.sources) == 1
    assert answer.sources[0].metadata["product_id"] == "SEM-IP"
    assert answer.sources[0].metadata["page"] == 1
    expected = rag.retriever.retrieve("power supply voltage", k=1)
    assert answer.sources[0].distance == pytest.approx(expected["distances"][0][0])
    assert 0 <= answer.sources[0].distance <= 2


def test_ingestion_duplicate_prevention_with_qdrant(pipeline, document_bytes):
    ingestion, _, client, db, uploader = pipeline
    first = ingest(ingestion, document_bytes)
    second = ingest(ingestion, document_bytes)
    assert second.status == "duplicate"
    assert second.document_id == first.document_id
    assert second.total_chunks == 0
    assert client.count("pipeline_test").count == first.total_chunks
    assert db.scalar(select(func.count()).select_from(Document)) == 1
    assert uploader.upload_files.call_count == 1
    third = ingest(ingestion, document_bytes, product_id="OTHER")
    assert third.status == "indexed"
    assert third.document_id != first.document_id
    assert client.count("pipeline_test").count == first.total_chunks + third.total_chunks


def test_rag_query_with_no_matching_vectors(pipeline):
    _, rag, _, _, _ = pipeline
    with patch("core.generator.urlopen") as request:
        with pytest.raises(ValueError, match="No indexed document chunks"):
            rag.answer_question("power supply")
        with pytest.raises(ValueError, match="Question must not be empty"):
            rag.answer_question("   ")
        request.assert_not_called()


def test_post_endpoints_with_qdrant(pipeline, document_bytes):
    ingestion, rag, _, _, _ = pipeline
    with patch.dict(app.dependency_overrides, {
        get_ingestion_service: lambda: ingestion,
        get_rag_service: lambda: rag,
    }):
        client = TestClient(app)
        try:
            upload = client.post("/api/v1/documents", data={"product_id": "SEM-IP"}, files={
                "files": ("manual.pptx", document_bytes),
            })
            assert upload.status_code == 201
            assert upload.json()["documents"][0]["collection"] == "pipeline_test"
            with patch("core.generator.urlopen") as request:
                request.return_value.__enter__.return_value.read.return_value = b'{"response":"24 volts."}'
                query = client.post("/api/v1/query", json={"question": "power supply voltage"})
            assert query.status_code == 200
            assert query.json()["sources"][0]["metadata"]["product_id"] == "SEM-IP"
            schema = client.get("/openapi.json").json()
            for path in ("/api/v1/documents", "/api/v1/query"):
                assert "Qdrant" in schema["paths"][path]["post"]["description"]
        finally:
            client.close()
