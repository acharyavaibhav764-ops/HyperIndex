from typing import Any

import chromadb

from config import settings
from .embeddings import Embeddings


class Retriever:
    """
    Manage ChromaDB vector persistence and semantic query retrieval.
    
    Attributes:
        embeddings - Embeddings function
        chroma_client
        collection_name
        collection

    Methods:
        chroma_location()
        upsert()
        retrieve()
    """

    def __init__(self, embeddings: Embeddings | None = None) -> None:
        self.embeddings = embeddings or Embeddings()

        chroma_host = settings.chroma_host
        if chroma_host:
            self.chroma_client = chromadb.HttpClient(
                host=chroma_host,
                port=settings.chroma_port,
            )
        else:
            self.chroma_client = chromadb.PersistentClient(
                path=settings.chroma_path
            )

        self.collection_name = settings.chroma_collection
        self.collection = self.chroma_client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
            embedding_function=self.embeddings.function,
        )

    @property
    def chroma_location(self) -> str:
        """Return the Chroma endpoint URL"""

        if settings.chroma_host:
            return f"http://{settings.chroma_host}:{settings.chroma_port}"
        return settings.chroma_path

    def upsert(
        self,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        """Persist chunk IDs, text, metadata, and embeddings to ChromaDB."""

        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )

    def retrieve(self, query: str, k: int = 5, *, include_toc: bool = False) -> dict[str, Any]:
        """Query ChromaDB for the top-k most semantically similar chunks.

        Args:
            query:       The query string.
            k:           Number of results to return.
            include_toc: When False (default), excludes chunks with
                         ``content_type=toc`` from results (v5.9 WP2).
        """
        where: dict | None = None
        if not include_toc:
            where = {"content_type": {"$ne": "toc"}}

        try:
            return self.collection.query(
                query_texts=[query],
                n_results=k,
                include=["documents", "metadatas", "distances"],
                where=where,
            )
        except Exception:
            # Fallback: old collections may lack content_type metadata.
            return self.collection.query(
                query_texts=[query],
                n_results=k,
                include=["documents", "metadatas", "distances"],
            )
