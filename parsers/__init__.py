"""
parsers package shim — forwards to core.parsers.
"""
from core.parsers import (
    BaseParser,
    DoclingParser,
    LibreOfficeConversionError,
    LibreOfficeConverter,
    LibreOfficeNotFoundError,
    ParserRouter,
    PdfPageRouter,
    TextParser,
    UnsupportedFileError,
)

__all__ = [
    "BaseParser",
    "DoclingParser",
    "LibreOfficeConversionError",
    "LibreOfficeConverter",
    "LibreOfficeNotFoundError",
    "ParserRouter",
    "PdfPageRouter",
    "TextParser",
    "UnsupportedFileError",
]

