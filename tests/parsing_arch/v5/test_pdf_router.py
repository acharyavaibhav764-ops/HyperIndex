"""
tests/parsing_arch/v5/test_pdf_router.py

Unit tests for PdfPageRouter — triage logic and routing behaviour.

Mocking strategy:
  - fitz.open() is mocked so no real PDF I/O happens.
  - _docling_full / _docling_page / _smolvlm_page are mocked to return
    predictable values, isolating the triage and dispatch logic.
  - pymupdf4llm.to_markdown is mocked to avoid file system access.
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from docling_core.types.doc import DoclingDocument

from parsers.pdf_router import PdfPageRouter


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
        # Regression guard: old ratio-based logic required ~25,000+ chars on A4
        # to clear the 0.05 threshold; this case would have incorrectly routed
        # to SmolVLM under the old implementation.
        page = _make_page(tables=0, images=1, text="a" * 3_000)
        # 3,000 > default pdf_min_text_chars_for_text_route (800)
        assert self.router._triage_page(page) == ["text"]

    def test_triage_returns_text_when_no_image(self):
        page = _make_page(tables=0, images=0, text="some text here")
        assert self.router._triage_page(page) == ["text"]

    def test_triage_table_and_image_both_returned(self):
        # v5.1: a page with a table AND a low-text image returns BOTH routes
        # so neither is dropped.  Old behaviour returned only "table".
        page = _make_page(tables=1, images=3, text="")
        result = self.router._triage_page(page)
        assert "table" in result
        assert "image" in result
        assert "text" not in result


# ---------------------------------------------------------------------------
# parse() — fallback path (enable_pdf_page_router=False)
# ---------------------------------------------------------------------------

class TestParseFallback:
    @patch("parsers.pdf_router.settings")
    def test_parse_calls_docling_full_when_flag_off(self, mock_settings):
        mock_settings.enable_pdf_page_router = False
        router = PdfPageRouter()
        mock_doc = MagicMock(spec=DoclingDocument)
        router._docling_full = MagicMock(return_value=mock_doc)

        result = router.parse(b"dummy", "test.pdf")

        router._docling_full.assert_called_once_with(b"dummy", "test.pdf")
        assert result is mock_doc

    @patch("parsers.pdf_router.settings")
    def test_parse_does_not_open_fitz_when_flag_off(self, mock_settings):
        mock_settings.enable_pdf_page_router = False
        router = PdfPageRouter()
        router._docling_full = MagicMock(return_value=MagicMock(spec=DoclingDocument))

        with patch("parsers.pdf_router.fitz") as mock_fitz:
            router.parse(b"dummy", "test.pdf")
            mock_fitz.open.assert_not_called()


# ---------------------------------------------------------------------------
# parse() — triage path (enable_pdf_page_router=True)
# ---------------------------------------------------------------------------

class TestParseTriagePath:
    @patch("parsers.pdf_router.settings")
    @patch("parsers.pdf_router.fitz")
    def test_parse_calls_triage_for_each_page(self, mock_fitz, mock_settings):
        mock_settings.enable_pdf_page_router = True
        mock_settings.pdf_min_text_chars_for_text_route = 800

        # 3,000-char page → text route (well above 800-char threshold)
        page0 = _make_page(text="a" * 3_000)  # → "text"
        page1 = _make_page(tables=1)            # → "table"
        mock_pdf = MagicMock()
        mock_pdf.__iter__ = MagicMock(return_value=iter([page0, page1]))
        mock_fitz.open.return_value = mock_pdf

        router = PdfPageRouter()
        router._triage_page = MagicMock(side_effect=[["text"], ["table"]])
        router._docling_page = MagicMock(return_value="table md")
        router._merge_pages = MagicMock(return_value=MagicMock(spec=DoclingDocument))
        router._single_page_bytes = MagicMock(return_value=b"single")

        with patch("parsers.pdf_router.pymupdf4llm") as mock_pml:
            mock_pml.to_markdown.return_value = "text md"
            router.parse(b"dummy", "test.pdf")

        assert router._triage_page.call_count == 2

    @patch("parsers.pdf_router.settings")
    @patch("parsers.pdf_router.fitz")
    def test_parse_routes_text_to_pymupdf4llm(self, mock_fitz, mock_settings):
        mock_settings.enable_pdf_page_router = True
        mock_settings.pdf_min_text_chars_for_text_route = 800

        page = _make_page(text="a" * 50_000)
        mock_pdf = MagicMock()
        mock_pdf.__iter__ = MagicMock(return_value=iter([page]))
        mock_fitz.open.return_value = mock_pdf

        router = PdfPageRouter()
        router._triage_page = MagicMock(return_value=["text"])
        router._merge_pages = MagicMock(return_value=MagicMock(spec=DoclingDocument))

        with patch("parsers.pdf_router.pymupdf4llm") as mock_pml:
            mock_pml.to_markdown.return_value = "text md"
            router.parse(b"dummy", "test.pdf")
            mock_pml.to_markdown.assert_called_once()

    @patch("parsers.pdf_router.settings")
    @patch("parsers.pdf_router.fitz")
    def test_parse_routes_table_to_docling(self, mock_fitz, mock_settings):
        mock_settings.enable_pdf_page_router = True
        mock_settings.pdf_min_text_chars_for_text_route = 800

        page = _make_page(tables=1)
        mock_pdf = MagicMock()
        mock_pdf.__iter__ = MagicMock(return_value=iter([page]))
        mock_fitz.open.return_value = mock_pdf

        router = PdfPageRouter()
        router._triage_page = MagicMock(return_value=["table"])
        router._docling_page = MagicMock(return_value="table md")
        router._merge_pages = MagicMock(return_value=MagicMock(spec=DoclingDocument))
        # Mock single-page extraction so we know exactly what bytes _docling_page receives
        single = b"single-page-pdf-bytes"
        router._single_page_bytes = MagicMock(return_value=single)

        router.parse(b"dummy", "test.pdf")

        router._single_page_bytes.assert_called_once_with(mock_pdf, page.number)
        router._docling_page.assert_called_once_with(single, "test.pdf", page.number)

    @patch("parsers.pdf_router.settings")
    @patch("parsers.pdf_router.fitz")
    def test_parse_routes_image_to_smolvlm(self, mock_fitz, mock_settings):
        mock_settings.enable_pdf_page_router = True
        mock_settings.pdf_min_text_chars_for_text_route = 800

        page = _make_page(images=1, text="hi")
        mock_pdf = MagicMock()
        mock_pdf.__iter__ = MagicMock(return_value=iter([page]))
        mock_fitz.open.return_value = mock_pdf

        router = PdfPageRouter()
        router._triage_page = MagicMock(return_value=["image"])
        router._smolvlm_page = MagicMock(return_value="smolvlm md")
        router._merge_pages = MagicMock(return_value=MagicMock(spec=DoclingDocument))
        # Mock single-page extraction so we know exactly what bytes _smolvlm_page receives
        single = b"single-page-pdf-bytes"
        router._single_page_bytes = MagicMock(return_value=single)

        router.parse(b"dummy", "test.pdf")

        router._single_page_bytes.assert_called_once_with(mock_pdf, page.number)
        router._smolvlm_page.assert_called_once_with(single, "test.pdf", page.number)


# ---------------------------------------------------------------------------
# can_handle
# ---------------------------------------------------------------------------

class TestCanHandle:
    def setup_method(self):
        self.router = PdfPageRouter()

    def test_handles_pdf_lowercase(self):
        assert self.router.can_handle(".pdf") is True

    def test_handles_pdf_uppercase(self):
        assert self.router.can_handle(".PDF") is True

    def test_rejects_docx(self):
        assert self.router.can_handle(".docx") is False

    def test_rejects_txt(self):
        assert self.router.can_handle(".txt") is False
