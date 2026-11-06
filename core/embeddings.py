from __future__ import annotations

import logging
from typing import Callable
from sentence_transformers import SentenceTransformer

from core import pipeline_config

logger = logging.getLogger(__name__)

DEFAULT_FALLBACK_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class Embeddings:
    """
    Generate vector embeddings for text chunks using configurable models.

    Attributes:
        model_name: Identifier of the embedding model.
        device: Target execution device ('cpu', 'cuda', etc.).
        function: Callable alias for embed()

    Methods:
        embed()
        _load_model()
    """

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
    ) -> None:
        self.model_name = model_name or pipeline_config.pipeline_settings.embedding_model
        self.device = device or pipeline_config.pipeline_settings.embedding_device
        self._model = self._load_model(self.model_name, self.device)
        self.function: Callable[[list[str]], list[list[float]]] = self.embed

    def _load_model(self, model_name: str, device: str) -> SentenceTransformer:
        """Load SentenceTransformer model with fallback handling."""

        try:
            logger.info("Loading SentenceTransformer model %r on device %r", model_name, device)
            return SentenceTransformer(model_name, device=device)
        except Exception as err:
            logger.warning(
                "Could not load SentenceTransformer for %r (%s). Falling back to %r.",
                model_name,
                err,
                DEFAULT_FALLBACK_MODEL,
            )
            return SentenceTransformer(DEFAULT_FALLBACK_MODEL, device=device)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate vector embeddings for a list of text strings."""
        
        if not texts:
            return []
        raw = self._model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return [
            item.tolist() if hasattr(item, "tolist") else list(item)
            for item in raw
        ]
