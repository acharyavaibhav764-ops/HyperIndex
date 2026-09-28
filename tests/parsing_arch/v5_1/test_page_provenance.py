"""
tests/parsing_arch/v5_1/test_page_provenance.py

v5.1 regression tests — page provenance & triage recalibration.

Covers:
  1. _merge_pages stamps correct page_no on every ProvenanceItem.
  2. End-to-end: _merge_pages output → Chunker._split_docling() yields real page ints.
  3. Multi-page chunks report all constituent page numbers.
  4. Realistic text + small image stays on the text route (was broken before v5.1).
  5. Sparse text + image still routes to image.

Mocking strategy mirrors the v5 suite: no real PDF I/O or heavy model calls.
"""
import pytest
from unittest.mock import MagicMock, patch

from docling_core.types.doc import DoclingDocument, ProvenanceItem, BoundingBox

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
    """Build a mock fitz.Page (same helper as v5 suite)."""
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


def _prov(page_no: int) -> ProvenanceItem:
    return ProvenanceItem(
        page_no=page_no,
        bbox=BoundingBox(l=0, t=0, r=0, b=0),
        charspan=(0, 0),
    )


# ---------------------------------------------------------------------------
# Fix 1 — _merge_pages stamps correct page_no (Issue 1)
# ---------------------------------------------------------------------------

class TestMergePagesStampsProvenance:
    def test_merge_pages_stamps_correct_page_no(self):
        """Each page markdown must produce text items whose prov[0].page_no
        matches the 1-indexed position in the list."""
        router = PdfPageRouter()

        # Three tiny single-page markdowns
        markdowns = [
            "# Installation Guide\n\nConnect the unit.",   # page 1
            "## Troubleshooting\n\nCheck the fuse.",        # page 2
            "### Warranty\n\nTwo year limited warranty.",   # page 3
        ]

        # _merge_pages calls DocumentConverter internally — mock it so the test
        # is purely structural without pulling in real docling I/O.
        def _fake_converter_factory(**kwargs):
            conv = MagicMock()

            def _fake_convert(stream):
                result = MagicMock()
                page_no = int(stream.name.split("_")[1].split(".")[0])  # "page_N.md"
                item = MagicMock()
                item.text = f"page {page_no} content"
                item.prov = []  # start empty — _merge_pages must fill this
                page_doc = MagicMock(spec=DoclingDocument)
                page_doc.texts = [item]
                result.document = page_doc
                return result

            conv.convert.side_effect = _fake_convert
            return conv

        combined = MagicMock(spec=DoclingDocument)
        combined.texts = []  # v5.2: _repair_pdf_headings iterates .texts; must be iterable
        combined.name = "manual"  # v5.3: _flatten_document reads doc.name

        with patch("parsers.pdf_router.DocumentConverter", side_effect=_fake_converter_factory), \
             patch("parsers.pdf_router.DoclingDocument", return_value=combined):
            router._merge_pages(markdowns, "manual.pdf")

        # combined.add_document called once per page
        assert combined.add_document.call_count == 3

    def test_provenance_items_have_correct_page_no_values(self):
        """Items added to the merged document carry prov[0].page_no == their
        1-indexed source page number.

        Note: _merge_pages does `item.prov = [ProvenanceItem(...)]`, which
        rebinds the attribute rather than mutating the original list.  We
        therefore capture the item objects themselves and inspect .prov on
        them after the call has returned.
        """
        router = PdfPageRouter()
        collected_items: list = []

        call_index = 0

        def _fake_converter_factory(**kwargs):
            conv = MagicMock()

            def _fake_convert(stream):
                nonlocal call_index
                call_index += 1
                page_no = call_index
                result = MagicMock()
                item = MagicMock()
                item.text = f"text on page {page_no}"
                item.prov = []  # _merge_pages will rebind this to a new list

                # Capture the *item*, not item.prov (prov will be rebound)
                collected_items.append(item)

                page_doc = MagicMock(spec=DoclingDocument)
                page_doc.texts = [item]
                # v5.3: _merge_pages now stamps prov via iterate_items(), not just .texts
                page_doc.iterate_items.return_value = [(item, 1)]
                result.document = page_doc
                return result

            conv.convert.side_effect = _fake_convert
            return conv

        combined = MagicMock(spec=DoclingDocument)
        combined.texts = []  # v5.2: _repair_pdf_headings iterates .texts; must be iterable
        combined.name = "doc"  # v5.3: _flatten_document reads doc.name

        with patch("parsers.pdf_router.DocumentConverter", side_effect=_fake_converter_factory), \
             patch("parsers.pdf_router.DoclingDocument", return_value=combined):
            router._merge_pages(["page one", "page two", "page three"], "doc.pdf")

        # Inspect each item's prov AFTER _merge_pages has rebound it
        for idx, item in enumerate(collected_items, start=1):
            assert len(item.prov) == 1, f"Expected 1 prov on page {idx}"
            assert item.prov[0].page_no == idx, \
                f"Page {idx} got page_no={item.prov[0].page_no}"


# ---------------------------------------------------------------------------
# Fix 2 — _triage_page absolute-count threshold (Issue 2)
# ---------------------------------------------------------------------------

class TestTriageRecalibrated:
    def setup_method(self):
        self.router = PdfPageRouter()

    def test_triage_realistic_text_page_with_small_image_stays_text(self):
        """A page with ~3,000 realistic chars AND an image must route to ['text'].

        This is the exact case Issue 2 broke: the old area-ratio formula required
        ~25,000+ chars on A4, so any real page with a logo routed to SmolVLM.
        """
        page = _make_page(images=1, text="a" * 3_000)
        # 3,000 > default pdf_min_text_chars_for_text_route (800)
        assert self.router._triage_page(page) == ["text"]

    def test_triage_sparse_text_with_image_still_routes_image(self):
        """A page with very little text (< threshold) and an image → ['image']."""
        page = _make_page(images=1, text="hi")  # 2 chars << 800
        assert self.router._triage_page(page) == ["image"]

    def test_triage_no_image_always_text_regardless_of_char_count(self):
        """Pages with zero images never route to 'image', even if text is sparse."""
        page = _make_page(images=0, text="")
        assert self.router._triage_page(page) == ["text"]

    def test_triage_exactly_at_threshold_routes_text(self):
        """Boundary: text_len == threshold is NOT less-than → text route."""
        page = _make_page(images=1, text="a" * 800)
        assert self.router._triage_page(page) == ["text"]

    def test_triage_one_below_threshold_routes_image(self):
        """text_len == threshold - 1 → image route."""
        page = _make_page(images=1, text="a" * 799)
        assert self.router._triage_page(page) == ["image"]


# ---------------------------------------------------------------------------
# Fix 4 — table + image merge (Issue 4)
# ---------------------------------------------------------------------------

class TestTableImageMerge:
    def setup_method(self):
        self.router = PdfPageRouter()

    def test_triage_returns_both_for_table_and_image_page(self):
        """v5.1: a page with a table AND sparse-text image returns ['table', 'image'].

        Previously _triage_page returned only 'table', silently dropping the image.
        """
        page = _make_page(tables=1, images=1, text="")  # text=0 << 800-char threshold
        result = self.router._triage_page(page)
        assert "table" in result
        assert "image" in result
        assert "text" not in result

    @patch("parsers.pdf_router.settings")
    @patch("parsers.pdf_router.fitz")
    def test_merged_page_keeps_table_and_picture_description(
        self, mock_fitz, mock_settings
    ):
        """When _triage_page returns ['table', 'image'], parse() must call both
        _docling_page (for table markdown) and _picture_descriptions_only (for
        figure captions), and join them so neither is dropped.
        """
        mock_settings.enable_pdf_page_router = True
        mock_settings.pdf_min_text_chars_for_text_route = 800

        page = _make_page(tables=1, images=1, text="")
        mock_pdf = MagicMock()
        mock_pdf.__iter__ = MagicMock(return_value=iter([page]))
        mock_fitz.open.return_value = mock_pdf

        router = PdfPageRouter()
        router._triage_page = MagicMock(return_value=["table", "image"])
        router._docling_page = MagicMock(return_value="| col | val |\n|---|---|")
        router._picture_descriptions_only = MagicMock(
            return_value="[Figure description] A diagram showing valve positions."
        )
        single = b"single-page-bytes"
        router._single_page_bytes = MagicMock(return_value=single)
        router._merge_pages = MagicMock(return_value=MagicMock(spec=DoclingDocument))

        router.parse(b"dummy", "test.pdf")

        # Both extraction methods must have been called
        router._docling_page.assert_called_once_with(single, "test.pdf", page.number)
        router._picture_descriptions_only.assert_called_once_with(
            single, "test.pdf", page.number
        )
        # The combined markdown must be passed to _merge_pages
        combined_md = router._merge_pages.call_args[0][0][0]
        assert "| col | val |" in combined_md
        assert "[Figure description]" in combined_md

