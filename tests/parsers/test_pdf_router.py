"""
tests/parsers/test_pdf_router.py

Unit tests for PdfPageRouter — Phase 1: triage logic, single-page extraction, and routing behaviour.
"""
from unittest.mock import MagicMock, patch

import pytest
from docling_core.types.doc import DoclingDocument
import fitz

from core.parsers.pdf_router import PdfPageRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_page(
    tables: int = 0,
    images: int = 0,
    text: str = "",
    width: float = 595.0,
    height: float = 842.0,
) -> MagicMock:
    """Build a mock fitz.Page with controllable properties."""
    page = MagicMock()
    page.number = 0
    page.rect.width = width
    page.rect.height = height
    page.get_text.return_value = text
    page.get_images.return_value = [MagicMock()] * images
    table_mock = MagicMock()
    table_mock.tables = [MagicMock()] * tables
    page.find_tables.return_value = table_mock
    return page


# ---------------------------------------------------------------------------
# can_handle & basic interface
# ---------------------------------------------------------------------------

class TestPdfPageRouterInterface:
    def setup_method(self):
        self.router = PdfPageRouter()

    def test_can_handle_pdf(self):
        assert self.router.can_handle(".pdf") is True
        assert self.router.can_handle(".PDF") is True

    def test_cannot_handle_other_extensions(self):
        assert self.router.can_handle(".docx") is False
        assert self.router.can_handle(".txt") is False
        assert self.router.can_handle(".doc") is False


# ---------------------------------------------------------------------------
# _triage_page
# ---------------------------------------------------------------------------

class TestTriagePage:
    def setup_method(self):
        self.router = PdfPageRouter()

    def test_triage_returns_table_when_tables_found_no_image(self):
        # Table only, no image — returns ["table"]
        page = _make_page(tables=2, images=0, text="some text")
        assert self.router._triage_page(page) == ["table"]

    def test_triage_returns_image_when_image_and_low_text(self):
        # Very little text and an image → ["image"]
        page = _make_page(tables=0, images=1, text="hi", width=595.0, height=842.0)
        # 2 chars << default 800-char threshold
        assert self.router._triage_page(page) == ["image"]

    def test_triage_returns_text_when_text_dense(self):
        # Realistic dense text (3,000 chars) despite having an image → text route.
        page = _make_page(tables=0, images=1, text="a" * 3_000)
        # 3,000 > default pdf_min_text_chars_for_text_route (800)
        assert self.router._triage_page(page) == ["text"]

    def test_triage_returns_text_when_no_image(self):
        page = _make_page(tables=0, images=0, text="some text here")
        assert self.router._triage_page(page) == ["text"]

    def test_triage_table_and_image_both_returned(self):
        # A page with a table AND a low-text image returns BOTH routes
        page = _make_page(tables=1, images=3, text="")
        result = self.router._triage_page(page)
        assert "table" in result
        assert "image" in result
        assert "text" not in result





# ---------------------------------------------------------------------------
# parse() — fallback path (enable_pdf_page_router=False)
# ---------------------------------------------------------------------------

class TestParseFallback:
    @patch("core.parsers.pdf_router.settings")
    def test_parse_calls_docling_full_when_flag_off(self, mock_settings):
        mock_settings.enable_pdf_page_router = False
        router = PdfPageRouter()
        mock_doc = MagicMock(spec=DoclingDocument)
        router._docling_full = MagicMock(return_value=mock_doc)

        result = router.parse(b"dummy", "test.pdf")

        router._docling_full.assert_called_once_with(b"dummy", "test.pdf")
        assert result is mock_doc

    @patch("core.parsers.pdf_router.settings")
    def test_parse_does_not_open_fitz_when_flag_off(self, mock_settings):
        mock_settings.enable_pdf_page_router = False
        router = PdfPageRouter()
        router._docling_full = MagicMock(return_value=MagicMock())

        with patch("core.parsers.pdf_router.fitz.open") as mock_fitz_open:
            router.parse(b"dummy", "test.pdf")
            mock_fitz_open.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 2: _page_markdown & _merge_pages (Page Provenance Stamping)
# ---------------------------------------------------------------------------

class TestPageMarkdown:
    @patch("core.parsers.pdf_router.pymupdf4llm.to_markdown")
    def test_page_markdown_calls_pymupdf4llm(self, mock_to_md):
        mock_to_md.return_value = "# Header\n\nContent"
        mock_pdf = MagicMock(spec=fitz.Document)

        md = PdfPageRouter._page_markdown(mock_pdf, 0)

        assert md == "# Header\n\nContent"
        mock_to_md.assert_called_once()
        args, kwargs = mock_to_md.call_args
        assert args[0] is mock_pdf
        assert kwargs.get("pages") == [0]


class TestMergePagesProvenance:
    def test_merge_pages_stamps_correct_page_numbers(self):
        router = PdfPageRouter()
        markdowns = [
            "# Installation Guide\n\nConnect the power cable.",
            "# Troubleshooting\n\nCheck the LED indicator.",
        ]

        doc = router._merge_pages(markdowns, "manual.pdf")

        assert isinstance(doc, DoclingDocument)
        # Check that items from page 1 have page_no == 1, and page 2 items have page_no == 2
        page_1_items = [
            item for item, _ in doc.iterate_items()
            if hasattr(item, "prov") and item.prov and item.prov[0].page_no == 1
        ]
        page_2_items = [
            item for item, _ in doc.iterate_items()
            if hasattr(item, "prov") and item.prov and item.prov[0].page_no == 2
        ]

        assert len(page_1_items) > 0
        assert len(page_2_items) > 0
        # Verify text in respective pages
        page_1_texts = " ".join(getattr(item, "text", "") for item in page_1_items)
        page_2_texts = " ".join(getattr(item, "text", "") for item in page_2_items)
        assert "Installation Guide" in page_1_texts
        assert "Troubleshooting" in page_2_texts


