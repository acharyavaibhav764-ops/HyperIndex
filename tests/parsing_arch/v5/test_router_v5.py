"""
tests/parsing_arch/v5/test_router_v5.py

Verify that ParserRouter dispatches .pdf to PdfPageRouter (not PdfStubParser).
"""
from parsers import ParserRouter
from parsers.pdf_router import PdfPageRouter


def test_get_parser_returns_pdf_page_router():
    router = ParserRouter()
    parser = router.get_parser("sample.pdf")
    assert isinstance(parser, PdfPageRouter), (
        f"Expected PdfPageRouter, got {type(parser).__name__}"
    )


def test_get_parser_returns_pdf_page_router_uppercase():
    router = ParserRouter()
    parser = router.get_parser("REPORT.PDF")
    assert isinstance(parser, PdfPageRouter)


def test_pdf_page_router_in_supported_extensions():
    router = ParserRouter()
    all_exts: list[str] = router._supported_extensions()
    assert ".pdf" in all_exts
