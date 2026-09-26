from io import BytesIO
from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import DocumentStream
from docling_core.types.doc import DoclingDocument

from .base import BaseParser

class PdfStubParser(BaseParser):
    """
    v4 PDF Stub Parser.
    Uses Docling's default DocumentConverter for PDF extraction as a placeholder
    until v5 implements the per-page triage logic.
    """
    SUPPORTED_EXTENSIONS = {".pdf"}

    def __init__(self):
        self._converter = DocumentConverter()

    def can_handle(self, ext: str) -> bool:
        return ext.lower() in self.SUPPORTED_EXTENSIONS

    def parse(self, file_bytes: bytes, filename: str, **kwargs) -> DoclingDocument:
        """Parse raw PDF bytes into a DoclingDocument."""
        stream = BytesIO(file_bytes)
        
        # Docling 2.0+ expects DocumentStream for byte streams
        doc_stream = DocumentStream(name=filename, stream=stream)
        
        result = self._converter.convert(doc_stream)
        return result.document
