"""
Phase 3 tests — ParserRouter dispatcher.

Verifies:
- .txt and .md route to TextParser.
- Case-insensitivity (.TXT, .MD).
- UnsupportedFileError raised for unknown extensions.
- Full parse() call through router returns a DoclingDocument.
- register() allows adding a custom parser dynamically.
"""
import pytest

from docling_core.types.doc import DoclingDocument
from parsers.router import ParserRouter, UnsupportedFileError
from parsers.text import TextParser


@pytest.fixture()
def router() -> ParserRouter:
    return ParserRouter()


class TestParserRouterGetParser:
    def test_txt_routes_to_text_parser(self, router):
        parser = router.get_parser("document.txt")
        assert isinstance(parser, TextParser)

    def test_md_routes_to_text_parser(self, router):
        parser = router.get_parser("notes.md")
        assert isinstance(parser, TextParser)

    def test_case_insensitive_txt(self, router):
        parser = router.get_parser("DOC.TXT")
        assert isinstance(parser, TextParser)

    def test_case_insensitive_md(self, router):
        parser = router.get_parser("README.MD")
        assert isinstance(parser, TextParser)

    def test_bare_extension_lookup(self, router):
        """get_parser should also accept a bare extension string."""
        parser = router.get_parser(".txt")
        assert isinstance(parser, TextParser)

    def test_unsupported_extension_raises(self, router):
        with pytest.raises(UnsupportedFileError):
            router.get_parser("report.xyz")

    def test_pdf_unsupported_in_v2(self, router):
        """PDF is not yet supported in v2 — must raise UnsupportedFileError."""
        with pytest.raises(UnsupportedFileError):
            router.get_parser("file.pdf")

    def test_doc_routes_to_libreoffice_converter(self, router):
        """v3: .doc now supported via LibreOfficeConverter — must NOT raise."""
        from parsers.libreoffice_converter import LibreOfficeConverter
        parser = router.get_parser("file.doc")
        assert isinstance(parser, LibreOfficeConverter)


    # v2 additions
    def test_docx_routes_to_docling_parser(self, router):
        from parsers.docling_parser import DoclingParser
        parser = router.get_parser("report.docx")
        assert isinstance(parser, DoclingParser)

    def test_pptx_routes_to_docling_parser(self, router):
        from parsers.docling_parser import DoclingParser
        parser = router.get_parser("slides.pptx")
        assert isinstance(parser, DoclingParser)

    def test_case_insensitive_docx(self, router):
        from parsers.docling_parser import DoclingParser
        assert isinstance(router.get_parser("FILE.DOCX"), DoclingParser)

    def test_case_insensitive_pptx(self, router):
        from parsers.docling_parser import DoclingParser
        assert isinstance(router.get_parser("SLIDES.PPTX"), DoclingParser)


class TestParserRouterParse:
    def test_parse_txt_returns_document(self, router):
        doc = router.parse(b"Hello, router.", "hello.txt")
        assert isinstance(doc, DoclingDocument)

    def test_parse_md_returns_document(self, router):
        doc = router.parse(b"# Title\n\nContent here.", "notes.md")
        assert isinstance(doc, DoclingDocument)

    def test_parse_unsupported_raises(self, router):
        with pytest.raises(UnsupportedFileError):
            router.parse(b"%PDF-1.4", "file.pdf")

    # v2 additions
    def test_parse_docx_returns_document(self, router):
        import io
        import docx as _docx
        doc_obj = _docx.Document()
        doc_obj.add_heading("Test", level=1)
        doc_obj.add_paragraph("Hello from docx.")
        buf = io.BytesIO()
        doc_obj.save(buf)
        doc = router.parse(buf.getvalue(), "test.docx")
        assert isinstance(doc, DoclingDocument)

    def test_parse_pptx_returns_document(self, router):
        import io
        from pptx import Presentation
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        slide.shapes.title.text = "Test Slide"
        slide.placeholders[1].text = "Body text."
        buf = io.BytesIO()
        prs.save(buf)
        doc = router.parse(buf.getvalue(), "test.pptx")
        assert isinstance(doc, DoclingDocument)


class TestParserRouterRegister:
    def test_register_custom_parser(self):
        """A dynamically registered parser should be discoverable."""
        from parsers.base import BaseParser

        class DummyParser(BaseParser):
            SUPPORTED_EXTENSIONS = frozenset({".dummy"})

            def can_handle(self, ext: str) -> bool:
                return ext == ".dummy"

            def parse(self, file_bytes: bytes, filename: str, **kwargs) -> DoclingDocument:
                raise NotImplementedError

        router = ParserRouter()
        router.register(DummyParser())
        parser = router.get_parser("test.dummy")
        assert isinstance(parser, DummyParser)
