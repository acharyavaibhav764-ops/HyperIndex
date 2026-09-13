from __future__ import annotations

from typing import Any
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction


class Embeddings:
    """
    Generate vector embeddings for text chunks.

    Attributes:
        function - callback function for invoking embedding

    Methods:
        embed()
    """

    def __init__(self, embedding_function: Any = None) -> None:
        self.function = embedding_function or DefaultEmbeddingFunction()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate vector embeddings for a list of text strings."""

        return self.function(texts)
