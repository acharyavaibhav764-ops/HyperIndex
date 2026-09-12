import os
from typing import Any

import chromadb
from .embeddings import Embeddings


class Retriever:
    """Manage ChromaDB vector persistence and semantic query retrieval."""

    def __init__(self, embeddings: Embeddings | None = None) -> None:
        self.embeddings = embeddings or Embeddings()

        chroma_host = os.getenv("CHROMA_HOST")
        if chroma_host:
            self.chroma_client = chromadb.HttpClient(
                host=chroma_host,
                port=int(os.getenv("CHROMA_PORT", "8000")),
            )
        else:
            self.chroma_client = chromadb.PersistentClient(
                path=os.getenv("CHROMA_PATH", "./chroma_data")
            )

        self.collection_name = os.getenv("CHROMA_COLLECTION", "my_documents")
        self.collection = self.chroma_client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
            embedding_function=self.embeddings.function,
        )

    @property
    def chroma_location(self) -> str:
        """Return the Chroma endpoint URL or local data directory path."""
        if os.getenv("CHROMA_HOST"):
            return f"http://{os.getenv('CHROMA_HOST')}:{os.getenv('CHROMA_PORT', '8000')}"
        return os.getenv("CHROMA_PATH", "./chroma_data")

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

    def retrieve(self, query: str, k: int = 5) -> dict[str, Any]:
        """Query ChromaDB for the top-k most semantically similar chunks."""
        return self.collection.query(
            query_texts=[query],
            n_results=k,
            include=["documents", "metadatas", "distances"],
        )
