from abc import ABC, abstractmethod
from docling_core.types.doc import DoclingDocument


class BaseParser(ABC):
    """Abstract base for all document parsers in the parsing architecture."""

    @abstractmethod
    def can_handle(self, ext: str) -> bool:
        """Return True if this parser supports the given file extension."""
        ...

    @abstractmethod
    def parse(self, file_bytes: bytes, filename: str, **kwargs) -> DoclingDocument:
        """Parse raw file bytes into a Docling document based on filename"""
        ...
