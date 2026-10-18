from __future__ import annotations

import logging
from typing import Any
from chromadb.utils.embedding_functions import (
    DefaultEmbeddingFunction,
    SentenceTransformerEmbeddingFunction,
)

from core import pipeline_config

logger = logging.getLogger(__name__)


class Embeddings:
    """
    Generate vector embeddings for text chunks using configurable models.

    Attributes:
        model_name: Identifier of the embedding model.
        device: Target execution device ('cpu', 'cuda', etc.).
        function: Callable implementing ChromaDB's embedding protocol.

    Methods:
        embed(texts): Generate vector embeddings for a list of strings.
    """

    def __init__(
        self,
        model_name: str | None = None,
        embedding_function: Any = None,
        device: str | None = None,
    ) -> None:
        
        self.model_name = model_name or pipeline_config.pipeline_settings.embedding_model
        self.device = device or pipeline_config.pipeline_settings.embedding_device

        if embedding_function is not None:
            self.function = embedding_function
        else:
            self.function = self._resolve_embedding_function(self.model_name, self.device)

    def _resolve_embedding_function(self, model_name: str, device: str) -> Any:
        """Resolve model name to a ChromaDB-compatible embedding function."""

        default_aliases = {
            "all-minilm-l6-v2",
            "sentence-transformers/all-minilm-l6-v2",
            "default",
        }
        if model_name.strip().lower() in default_aliases:
            logger.info("Using built-in ONNX DefaultEmbeddingFunction for %s", model_name)
            return DefaultEmbeddingFunction()

        try:
            logger.info("Resolving SentenceTransformer model %r on device %r", model_name, device)
            return SentenceTransformerEmbeddingFunction(
                model_name=model_name,
                device=device,
            )
        except (ImportError, ValueError, Exception) as err:
            logger.warning(
                "Could not load SentenceTransformer for %r (%s). Falling back to DefaultEmbeddingFunction.",
                model_name,
                err,
            )
            return DefaultEmbeddingFunction()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate vector embeddings for a list of text strings."""

        if not texts:
            return []
        raw = self.function(texts)
        return [
            item.tolist() if hasattr(item, "tolist") else list(item)
            for item in raw
        ]
