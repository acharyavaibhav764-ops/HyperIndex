from abc import ABC, abstractmethod

from docling_core.types.doc import DoclingDocument


class BaseParser(ABC):
    """
    Abstract base for all document parsers in the parsing architecture.

    Every concrete parser must:
    - Declare which file extensions it supports via ``can_handle``.
    - Implement ``parse`` to return a structured ``DoclingDocument`` from raw bytes.
    """

    @abstractmethod
    def can_handle(self, ext: str) -> bool:
        """Return True if this parser supports the given file extension.

        Args:
            ext: Lowercase, dot-prefixed extension, e.g. ``'.txt'``.

        Returns:
            bool: True when this parser should be used for the given extension.
        """
        ...

    @abstractmethod
    def parse(self, file_bytes: bytes, filename: str, **kwargs) -> DoclingDocument:
        """Parse raw file bytes into a Docling document.

        Args:
            file_bytes: Raw binary content of the uploaded file.
            filename:   Original filename, used to infer format when needed.
            **kwargs:   Extension point for parser-specific options.

        Returns:
            DoclingDocument: Structured document ready for chunking.
        """
        ...
