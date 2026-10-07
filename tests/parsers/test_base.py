"""
Unit tests — BaseParser abstract interface.

Verifies:
- BaseParser cannot be instantiated directly.
- Concrete subclass without required methods raises TypeError.
- Valid concrete subclass can be instantiated and called.
"""
import pytest
from docling_core.types.doc import DoclingDocument

from core.parsers.base import BaseParser


class _NoMethods(BaseParser):
    """Incomplete subclass — missing both abstract methods."""
    pass


class _ValidParser(BaseParser):
    """Minimal valid subclass for testing."""

    def can_handle(self, ext: str) -> bool:
        return ext == ".dummy"

    def parse(self, file_bytes: bytes, filename: str, **kwargs) -> DoclingDocument:
        from docling.document_converter import DocumentConverter
        result = DocumentConverter().convert_string("test", input_format=None)
        return result.document


class TestBaseParserAbstract:
    def test_cannot_instantiate_directly(self):
        """BaseParser is abstract and must not be instantiable."""
        with pytest.raises(TypeError):
            BaseParser()  # type: ignore[abstract]

    def test_incomplete_subclass_raises_on_instantiation(self):
        """Subclass missing abstract methods raises TypeError at instantiation."""
        with pytest.raises(TypeError):
            _NoMethods()

    def test_valid_subclass_instantiates(self):
        """A fully implemented subclass instantiates without error."""
        parser = _ValidParser()
        assert isinstance(parser, BaseParser)

    def test_can_handle_contract(self):
        """can_handle returns bool True/False correctly."""
        parser = _ValidParser()
        assert parser.can_handle(".dummy") is True
        assert parser.can_handle(".pdf") is False

