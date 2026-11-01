from __future__ import annotations

import logging
from typing import Any, Callable
from sentence_transformers import SentenceTransformer

from core import pipeline_config

logger = logging.getLogger(__name__)

DEFAULT_FALLBACK_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


# NOTE(transitional-v1.0): SentenceTransformerCallable is a standalone wrapper
# created to satisfy ChromaDB's required collection callback protocol.
# In Qdrant v5.0 (after Chroma is fully deprecated), this wrapper will be collapsed
# directly into Embeddings to eliminate redundant list conversions.
class SentenceTransformerCallable:
    """
    Callable class for configuring the embedding model and also implementing embedding function

    Attributes:
        model_name: Identifier of the embedding model.
        device: Target execution device ('cpu', 'cuda', etc.).
        _model: Attach the real embedding model to class after resolving from model_name

    Methods:
        __call__()
    """

    def __init__(self, model_name: str, device: str = "cpu") -> None:
        self.model_name = model_name
        self.device = device
        logger.info("Loading SentenceTransformer model %r on device %r", model_name, device)
        self._model = SentenceTransformer(model_name, device=device)

    def __call__(self, input: list[str]) -> list[list[float]]:
        """Generate normalized vector embeddings for direct invocation or database callbacks."""
        
        if not input:
            return []
        embeddings = self._model.encode(
            input,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        
        return [
            item.tolist() if hasattr(item, "tolist") else list(item)
            for item in embeddings
        ]


class Embeddings:
    """
    Generate vector embeddings for text chunks using configurable models.

    Attributes:
        model_name: Identifier of the embedding model.
        device: Target execution device ('cpu', 'cuda', etc.).
        function: Callable class implementing the embedding function

    Methods:
        embed()
        _resolve_embedding_function()
    """

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
    ) -> None:
        self.model_name = model_name or pipeline_config.pipeline_settings.embedding_model
        self.device = device or pipeline_config.pipeline_settings.embedding_device
        self.function = self._resolve_embedding_function(self.model_name, self.device)

    def _resolve_embedding_function(self, model_name: str, device: str) -> Callable[[list[str]], list[list[float]]]:
        """Resolve model name to a SentenceTransformerCallable with fallback handling."""

        try:
            return SentenceTransformerCallable(model_name=model_name, device=device)
        except Exception as err:
            logger.warning(
                "Could not load SentenceTransformer for %r (%s). Falling back to %r.",
                model_name,
                err,
                DEFAULT_FALLBACK_MODEL,
            )
            return SentenceTransformerCallable(model_name=DEFAULT_FALLBACK_MODEL, device=device)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate vector embeddings for a list of text strings."""
        
        if not texts:
            return []
        raw = self.function(texts)
        return [
            item.tolist() if hasattr(item, "tolist") else list(item)
            for item in raw
        ]
