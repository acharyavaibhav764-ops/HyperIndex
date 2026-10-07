"""
Unit tests — TextParser implementation.

Verifies:
- Plain-text files are parsed and produce a non-empty DoclingDocument.
- Markdown headings appear as section-level items in the document.
- Non-UTF8 byte streams decode gracefully (Latin-1 fallback).
- Empty files return a minimal valid DoclingDocument without raising.
- can_handle returns True for supported extensions only.
"""
import pytest
from docling_core.types.doc import DoclingDocument

from core.parsers.text import TextParser


@pytest.fixture(scope="module")
def parser() -> TextParser:
    return TextParser()


class TestTextParserCanHandle:
    def test_txt_supported(self, parser):
        assert parser.can_handle(".txt") is True

    def test_text_supported(self, parser):
        assert parser.can_handle(".text") is True

    def test_md_supported(self, parser):
        assert parser.can_handle(".md") is True

    def test_markdown_supported(self, parser):
        assert parser.can_handle(".markdown") is True

    def test_case_insensitive(self, parser):
        assert parser.can_handle(".TXT") is True
        assert parser.can_handle(".MD") is True

    def test_pdf_not_supported(self, parser):
        assert parser.can_handle(".pdf") is False

    def test_docx_not_supported(self, parser):
        assert parser.can_handle(".docx") is False


class TestTextParserParse:
    def test_plain_text_returns_document(self, parser):
        """Plain text bytes produce a DoclingDocument."""
        content = b"Hello world. This is a test document."
        doc = parser.parse(content, "sample.txt")
        assert isinstance(doc, DoclingDocument)

    def test_plain_text_contains_body_text(self, parser):
        """Parsed document exports text that includes the source content."""
        content = b"The quick brown fox jumps over the lazy dog."
        doc = parser.parse(content, "sample.txt")
        exported = doc.export_to_markdown()
        assert "quick brown fox" in exported

    def test_markdown_heading_preserved(self, parser):
        """Markdown # heading must appear in the exported representation."""
        content = b"# Section Title\n\nSome paragraph text here."
        doc = parser.parse(content, "doc.md")
        assert isinstance(doc, DoclingDocument)
        exported = doc.export_to_markdown()
        assert "Section Title" in exported

    def test_latin1_bytes_decode_gracefully(self, parser):
        """Latin-1 encoded bytes (non-UTF8) should not raise an exception."""
        content = "Caf\xe9 au lait".encode("latin-1")  # \xe9 = é in Latin-1
        doc = parser.parse(content, "sample.txt")
        assert isinstance(doc, DoclingDocument)

    def test_empty_file_returns_document(self, parser):
        """An empty byte string must not raise and must return a DoclingDocument."""
        doc = parser.parse(b"", "empty.txt")
        assert isinstance(doc, DoclingDocument)

