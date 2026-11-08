"""Core package exports."""
from .chunker import Chunker
from .dedup import MinHashDeduplicator
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
from .pipeline_config import PipelineSettings, pipeline_settings
from .retriever import Retriever
from .uploader import StorageError, Uploader, build_storage_path, make_family_id

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
    "MinHashDeduplicator",
    "Parser",
    "ParserRouter",
    "PipelineSettings",
    "pipeline_settings",
    "Retriever",
    "StorageError",
    "TextParser",
    "Uploader",
    "UnsupportedFileError",
    "build_storage_path",
    "make_family_id",
]
