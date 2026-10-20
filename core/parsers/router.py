from pathlib import PurePath
from docling_core.types.doc import DoclingDocument

from .base import BaseParser
from .docling_parser import DoclingParser
from .libreoffice_converter import LibreOfficeConverter
from .pdf import PdfParser
from .text import TextParser


class UnsupportedFileError(ValueError):
    """Raised when no registered parser can handle the given file extension."""


class ParserRouter:
    """
    Route incoming files to the correct BaseParser instances by file extension.

    Attributes:
        _parsers - Ordered list of registered BaseParser instances.

    Methods:
        register()
        get_parser()
        parse()

        _normalize_ext()
        _supported_extensions()   
    """

    def __init__(self) -> None:
        """Create a router and auto-register the built-in parsers."""

        self._parsers: list[BaseParser] = []
        self.register(TextParser()) # .txt / .md
        self.register(DoclingParser()) # .docx / .pptx
        self.register(LibreOfficeConverter()) # .doc / .ppt
        self.register(PdfParser()) # .pdf


    # PUBLIC API

    def register(self, parser: BaseParser) -> None:
        """Register a parser to _parsers array"""

        self._parsers.append(parser)

    def get_parser(self, filename_or_ext: str) -> BaseParser:
        """Return the first registered parser that handles the given extension."""

        ext = self._normalize_ext(filename_or_ext)
        for parser in self._parsers:
            if parser.can_handle(ext):
                return parser
        raise UnsupportedFileError(
            f"No parser registered for extension '{ext}'. "
            f"Supported: {self._supported_extensions()}"
        )

    def parse(self, file_bytes: bytes, filename: str, **kwargs) -> DoclingDocument:
        """Parse file_bytes by dispatching to the appropriate parser."""
        
        parser = self.get_parser(filename)
        return parser.parse(file_bytes, filename, **kwargs)


    # PRIVATE HELPERS

    @staticmethod
    def _normalize_ext(filename_or_ext: str) -> str:
        """Extract and lower-case the file extension."""

        raw = PurePath(filename_or_ext).suffix or filename_or_ext
        return raw.lower()

    def _supported_extensions(self) -> list[str]:
        """Return a sorted list of all extensions supported by registered parsers."""

        exts: set[str] = set()
        for parser in self._parsers:
            for ext in getattr(parser, "SUPPORTED_EXTENSIONS", []):
                exts.add(ext)
        return sorted(exts)
