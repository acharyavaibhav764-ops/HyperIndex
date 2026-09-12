from chromadb.utils.embedding_functions import DefaultEmbeddingFunction


class Embeddings:
    """Generate vector embeddings for text chunks."""

    def __init__(self, embedding_function: DefaultEmbeddingFunction | None = None) -> None:
        self.function = embedding_function or DefaultEmbeddingFunction()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate vector embeddings for a list of text strings."""
        return self.function(texts)
