"""Core package exports."""
from .chunker import Chunker
from .embeddings import Embeddings
from .generator import GenerationError, Generator
from .parsers import (
    BaseParser,
    DoclingParser,
    LibreOfficeConversionError,
    LibreOfficeConverter,
    LibreOfficeNotFoundError,
    ParserRouter,
    TextParser,
    UnsupportedFileError,
)
from .retriever import Retriever
from .uploader import StorageError, Uploader

# Backward-compatibility alias
Parser = ParserRouter

__all__ = [
    "BaseParser",
    "Chunker",
    "DoclingParser",
    "Embeddings",
    "GenerationError",
    "Generator",
    "LibreOfficeConversionError",
    "LibreOfficeConverter",
    "LibreOfficeNotFoundError",
    "Parser",
    "ParserRouter",
    "Retriever",
    "StorageError",
    "TextParser",
    "Uploader",
    "UnsupportedFileError",
]


