import io
import logging

from docling.datamodel.base_models import InputFormat
from docling.document_converter import DocumentConverter
from docling_core.types.doc import DoclingDocument
from docling_core.types.io import DocumentStream

from ..base import BaseParser

logger = logging.getLogger(__name__)


class PdfParser(BaseParser):
    """
    Parse PDF documents into a DoclingDocument.

    Attributes:
        _converter: Shared DocumentConverter instance for PDF processing.

    Methods:
        can_handle()
        parse()
    """

    SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".pdf"})

    def __init__(self) -> None:
        """Initialize parser with lazy converter instantiation to avoid startup delay."""

        self._converter: DocumentConverter | None = None

    def can_handle(self, ext: str) -> bool:
        """Return True if this parser supports the given file extension."""

        return ext.lower() in self.SUPPORTED_EXTENSIONS

    def parse(self, file_bytes: bytes, filename: str, **kwargs) -> DoclingDocument:
        """Convert raw PDF file bytes into a DoclingDocument."""
        
        stream = DocumentStream(name=filename, stream=io.BytesIO(file_bytes))

        if self._converter is None:
            self._converter = DocumentConverter(allowed_formats=[InputFormat.PDF])

        result = self._converter.convert(stream)
        return result.document

