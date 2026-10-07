from pathlib import PurePath
from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import InputFormat
from docling_core.types.doc import DoclingDocument

from .base import BaseParser


class TextParser(BaseParser):
    """
    Parse plain-text

    Attributes:
        SUPPORTED_EXTENSIONS: Set of lowercase dot-prefixed extensions handled.
        _ENCODINGS: Supported encodings for text
        _converter: DocumentConverter instance for converting text documents into docling documents

    Methods:
        can_handle()
        parse()

        _decode_bytes()
    """

    SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
        {".txt", ".text", ".md", ".markdown"}
    )
    _ENCODINGS = ("utf-8", "utf-8-sig", "latin-1", "cp1252")

    def __init__(self) -> None:
        """Instantiate a shared DocumentConverter from docling library"""

        self._converter = DocumentConverter()


    # PUBLIC API

    def can_handle(self, ext: str) -> bool:
        """Return True for plaintext and Markdown extensions."""

        return ext.lower() in self.SUPPORTED_EXTENSIONS

    def parse(self, file_bytes: bytes, filename: str, **kwargs) -> DoclingDocument:
        """Decode bytes and convert to a DoclingDocument."""

        text = self._decode_bytes(file_bytes)
        result = self._converter.convert_string(
            text, format=InputFormat.MD, name=filename # Markdown is natively supported by docling
        )
        return result.document


    # PRIVATE HELPERS

    def _decode_bytes(self, data: bytes) -> str:
        """Decode data trying each supported encoding sequentially."""

        for encoding in self._ENCODINGS:
            try:
                return data.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return data.decode("utf-8", errors="replace")
