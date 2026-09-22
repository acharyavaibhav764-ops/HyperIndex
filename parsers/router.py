from pathlib import PurePath

from docling_core.types.doc import DoclingDocument

from .base import BaseParser
from .docling_parser import DoclingParser
from .libreoffice_converter import LibreOfficeConverter
from .text import TextParser


class UnsupportedFileError(ValueError):
    """Raised when no registered parser can handle the given file extension."""


class ParserRouter:
    """
    Route incoming files to the correct :class:`BaseParser` by file extension.

    In v1 only ``.txt`` and ``.md`` are supported. Additional parsers are
    registered by passing them to :meth:`register`.

    Usage::

        router = ParserRouter()
        doc: DoclingDocument = router.parse(file_bytes, "report.md")

    Attributes:
        _parsers: Ordered list of registered :class:`BaseParser` instances.
    """

    def __init__(self) -> None:
        """Create a router and auto-register the built-in parsers.

        v1: TextParser for .txt / .md
        v2: DoclingParser for .docx / .pptx
        v3: LibreOfficeConverter for .doc / .ppt
        """
        self._parsers: list[BaseParser] = []
        # v1: register TextParser for .txt / .md
        self.register(TextParser())
        # v2: register DoclingParser for .docx / .pptx
        self.register(DoclingParser())
        # v3: register LibreOfficeConverter for .doc / .ppt
        self.register(LibreOfficeConverter())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, parser: BaseParser) -> None:
        """Register a parser at the end of the resolution order.

        Args:
            parser: Any :class:`BaseParser` subclass instance.
        """
        self._parsers.append(parser)

    def get_parser(self, filename_or_ext: str) -> BaseParser:
        """Return the first registered parser that handles the given extension.

        Args:
            filename_or_ext: A full filename (``'document.txt'``) or a bare
                             dot-prefixed extension (``'.txt'``).

        Returns:
            BaseParser: The matching parser instance.

        Raises:
            UnsupportedFileError: When no parser supports the extension.
        """
        ext = self._normalize_ext(filename_or_ext)
        for parser in self._parsers:
            if parser.can_handle(ext):
                return parser
        raise UnsupportedFileError(
            f"No parser registered for extension '{ext}'. "
            f"Supported: {self._supported_extensions()}"
        )

    def parse(self, file_bytes: bytes, filename: str, **kwargs) -> DoclingDocument:
        """Parse *file_bytes* by dispatching to the appropriate parser.

        Args:
            file_bytes: Raw binary content of the uploaded file.
            filename:   Original filename used for extension detection.
            **kwargs:   Forwarded to the selected parser's ``parse`` method.

        Returns:
            DoclingDocument: Structured document ready for chunking.

        Raises:
            UnsupportedFileError: When the file's extension is not supported.
        """
        parser = self.get_parser(filename)
        return parser.parse(file_bytes, filename, **kwargs)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_ext(filename_or_ext: str) -> str:
        """Extract and lower-case the file extension.

        Args:
            filename_or_ext: Full filename or bare extension string.

        Returns:
            str: Lowercase dot-prefixed extension, e.g. ``'.txt'``.
        """
        raw = PurePath(filename_or_ext).suffix or filename_or_ext
        return raw.lower()

    def _supported_extensions(self) -> list[str]:
        """Return a sorted list of all extensions supported by registered parsers."""
        exts: set[str] = set()
        for parser in self._parsers:
            for ext in getattr(parser, "SUPPORTED_EXTENSIONS", []):
                exts.add(ext)
        return sorted(exts)
