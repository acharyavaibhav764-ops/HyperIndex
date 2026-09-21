from pathlib import PurePath

from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import InputFormat
from docling_core.types.doc import DoclingDocument

from .base import BaseParser


class TextParser(BaseParser):
    """
    Parse plain-text (``.txt``, ``.text``) and Markdown (``.md``, ``.markdown``)
    files into a :class:`~docling_core.types.doc.DoclingDocument`.

    Text is decoded with automatic encoding fallback (UTF-8 → Latin-1 → cp1252).
    Markdown headings are preserved as native Docling section levels via Docling's
    built-in Markdown pipeline.

    Attributes:
        SUPPORTED_EXTENSIONS: Set of lowercase dot-prefixed extensions handled.
    """

    SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
        {".txt", ".text", ".md", ".markdown"}
    )
    _ENCODINGS = ("utf-8", "utf-8-sig", "latin-1", "cp1252")

    def __init__(self) -> None:
        """Instantiate a shared DocumentConverter for plaintext/Markdown."""
        self._converter = DocumentConverter()

    # ------------------------------------------------------------------
    # BaseParser interface
    # ------------------------------------------------------------------

    def can_handle(self, ext: str) -> bool:
        """Return True for plaintext and Markdown extensions.

        Args:
            ext: Lowercase, dot-prefixed extension, e.g. ``'.md'``.
        """
        return ext.lower() in self.SUPPORTED_EXTENSIONS

    def parse(self, file_bytes: bytes, filename: str, **kwargs) -> DoclingDocument:
        """Decode bytes and convert to a DoclingDocument.

        Encoding is attempted in order: UTF-8, UTF-8-BOM, Latin-1, CP1252.
        An empty byte string returns a minimal, valid (empty) DoclingDocument.

        Args:
            file_bytes: Raw binary content of the file.
            filename:   Original filename; used to choose Markdown vs plain-text
                        input format.
            **kwargs:   Unused; reserved for future parser options.

        Returns:
            DoclingDocument: Structured representation of the text content.
        """
        text = self._decode_bytes(file_bytes)

        # Docling convert_string natively parses Markdown format, which cleanly
        # represents both Markdown (.md, .markdown) and plain text (.txt, .text).
        result = self._converter.convert_string(
            text, format=InputFormat.MD, name=filename
        )
        return result.document

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _decode_bytes(self, data: bytes) -> str:
        """Decode *data* trying each encoding in :attr:`_ENCODINGS` in order.

        Falls back to UTF-8 with ``errors='replace'`` if all encodings fail.

        Args:
            data: Raw bytes to decode.

        Returns:
            str: Decoded text.
        """
        for encoding in self._ENCODINGS:
            try:
                return data.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return data.decode("utf-8", errors="replace")
