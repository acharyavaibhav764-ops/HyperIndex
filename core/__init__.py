from .chunker import Chunker
from .parser import Parser
from parsers import ParserRouter, DoclingParser

# Heavy infrastructure imports (boto3, chromadb, httpx) are deferred to avoid
# import failures in test environments that only have the parsing dependencies.
try:
    from .embeddings import Embeddings
    from .generator import GenerationError, Generator
    from .retriever import Retriever
    from .uploader import StorageError, Uploader
except ImportError:
    Embeddings = None  # type: ignore[assignment,misc]
    GenerationError = None  # type: ignore[assignment,misc]
    Generator = None  # type: ignore[assignment,misc]
    Retriever = None  # type: ignore[assignment,misc]
    StorageError = None  # type: ignore[assignment,misc]
    Uploader = None  # type: ignore[assignment,misc]

__all__ = [
    "Chunker",
    "DoclingParser",
    "Embeddings",
    "GenerationError",
    "Generator",
    "Parser",
    "ParserRouter",
    "Retriever",
    "StorageError",
    "Uploader",
]
