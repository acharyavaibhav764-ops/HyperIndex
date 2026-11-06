from typing import Any
from uuid import NAMESPACE_DNS, uuid5

from qdrant_client import QdrantClient, models

from config import settings
from .embeddings import Embeddings
from .pipeline_config import pipeline_settings


class Retriever:
    """
    Manage Qdrant vector persistence and semantic query retrieval.
    
    Attributes:
        embeddings
        client
        collection_name
        vector_size

    Methods:
        chunk_id_to_uuid()
        upsert()
        retrieve()
    """

    def __init__(
        self,
        embeddings: Embeddings | None = None,
        client: QdrantClient | None = None,
        collection_name: str | None = None,
    ) -> None:
        self.embeddings = embeddings or Embeddings()
        self.collection_name = collection_name or settings.qdrant_collection

        if client is not None:
            self.client = client
        elif settings.qdrant_host:
            self.client = QdrantClient(
                host=settings.qdrant_host,
                port=settings.qdrant_port,
            )
        elif settings.qdrant_path:
            self.client = QdrantClient(path=settings.qdrant_path)
        else:
            self.client = QdrantClient(":memory:")

        self.vector_size = len(self.embeddings.embed(["probe"])[0])
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """Create the collection or validate its vector configuration."""

        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.vector_size,
                    distance=models.Distance.COSINE,
                ),
            )
            return

        vectors = self.client.get_collection(self.collection_name).config.params.vectors
        if (
            not isinstance(vectors, models.VectorParams)
            or vectors.size != self.vector_size
            or vectors.distance != models.Distance.COSINE
        ):
            raise ValueError("Qdrant collection must match the embedding dimension and use cosine distance")

    @staticmethod
    def chunk_id_to_uuid(chunk_id: str) -> str:
        """Map a chunk ID to a deterministic Qdrant point UUID."""

        return str(uuid5(NAMESPACE_DNS, chunk_id))

    def upsert(
        self,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        """Persist chunk IDs, text, metadata, and embeddings to Qdrant."""

        if not (len(ids) == len(documents) == len(metadatas) == len(embeddings)):
            raise ValueError("Chunk IDs, documents, metadata, and embeddings must have equal lengths")
        if not ids:
            return
        if any(len(vector) != self.vector_size for vector in embeddings):
            raise ValueError("Embedding dimensions must match the Qdrant collection")

        points = [
            models.PointStruct(
                id=self.chunk_id_to_uuid(chunk_id),
                vector=vector,
                payload={**(metadata or {}), "text": text, "chunk_id": chunk_id},
            )
            for chunk_id, text, metadata, vector in zip(ids, documents, metadatas, embeddings)
        ]
        self.client.upsert(
            collection_name=self.collection_name,
            points=points,
            wait=True,
        )

    def retrieve(self, query: str, k: int | None = None) -> dict[str, Any]:
        """Query Qdrant for the top-k most semantically similar chunks."""

        target_k = k if k is not None else pipeline_settings.retrieval_k
        if target_k < 1:
            raise ValueError("Retrieval limit must be positive")
        result = self.client.query_points(
            collection_name=self.collection_name,
            query=self.embeddings.embed([query])[0],
            limit=target_k,
            with_payload=True,
        )
        documents = []
        metadatas = []
        distances = []
        for point in result.points:
            payload = dict(point.payload or {})
            documents.append(payload.pop("text", ""))
            metadatas.append(payload)
            distances.append(max(0.0, 1.0 - point.score))

        return {"documents": [documents], "metadatas": [metadatas], "distances": [distances]}
