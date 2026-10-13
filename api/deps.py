from functools import lru_cache
from fastapi import Depends, params
from sqlalchemy.orm import Session

from config import settings
from core import (
    Chunker,
    Embeddings,
    Generator,
    ParserRouter,
    Retriever,
    Uploader,
    pipeline_settings,
)
from db.session import get_db
from services.ingestion_service import IngestionService
from services.rag_service import RAGService


# Core Component Providers (Lazy Singletons via @lru_cache)
@lru_cache
def get_uploader() -> Uploader:
    return Uploader()


@lru_cache
def get_parser() -> ParserRouter:
    return ParserRouter()


@lru_cache
def get_chunker() -> Chunker:
    return Chunker(chunk_size=pipeline_settings.chunk_size, chunk_overlap=pipeline_settings.chunk_overlap)


@lru_cache
def get_embeddings() -> Embeddings:
    return Embeddings(
        model_name=pipeline_settings.embedding_model,
        device=pipeline_settings.embedding_device,
    )


@lru_cache
def get_retriever(embeddings: Embeddings = Depends(get_embeddings)) -> Retriever:
    if isinstance(embeddings, params.Depends) or embeddings is None:
        embeddings = get_embeddings()
    return Retriever(embeddings=embeddings)


@lru_cache
def get_generator() -> Generator:
    return Generator(
        ollama_host=settings.ollama_host,
        ollama_port=settings.ollama_port,
        model=pipeline_settings.ollama_model,
        system_prompt=pipeline_settings.system_prompt,
        prompt_template=pipeline_settings.prompt_template,
    )


# Service Providers
def get_ingestion_service(
    uploader: Uploader = Depends(get_uploader),
    parser: ParserRouter = Depends(get_parser),
    chunker: Chunker = Depends(get_chunker),
    embeddings: Embeddings = Depends(get_embeddings),
    retriever: Retriever = Depends(get_retriever),
    db: Session | None = Depends(get_db),
) -> IngestionService:
    resolved_db = db if not isinstance(db, params.Depends) else None

    return IngestionService(
        uploader=uploader if not isinstance(uploader, params.Depends) else get_uploader(),
        parser=parser if not isinstance(parser, params.Depends) else get_parser(),
        chunker=chunker if not isinstance(chunker, params.Depends) else get_chunker(),
        embeddings=embeddings if not isinstance(embeddings, params.Depends) else get_embeddings(),
        retriever=retriever if not isinstance(retriever, params.Depends) else get_retriever(),
        db=resolved_db,
    )


def get_rag_service(
    retriever: Retriever = Depends(get_retriever),
    generator: Generator = Depends(get_generator),
) -> RAGService:
    return RAGService(
        retriever=retriever if not isinstance(retriever, params.Depends) else get_retriever(),
        generator=generator if not isinstance(generator, params.Depends) else get_generator(),
        retrieval_k=pipeline_settings.retrieval_k,
    )
