"""
tests/parsing_arch/v5_4/test_flatten_reverted.py

v5.4 regression tests ensuring _flatten_document() is NOT called from
_merge_pages() and that tables survive the merge pass.

These are the direct regression tests that would have caught v5.3's
table-loss bug before it ever reached a real PDF smoke test.

Test inventory:
  1. test_merge_pages_does_not_call_flatten
     Spy on _flatten_document; assert it is never called and that the
     returned document's doc.tables is non-empty when a table page is present.
  2. test_debug_heading_dump_default_off
     Assert settings.pdf_debug_heading_dump defaults to False and that no
     HEADING / ORPHAN-CHECK log lines appear from _merge_pages() when unset.
"""
import logging
import pytest
from io import BytesIO
from unittest.mock import patch, MagicMock

from docling_core.types.doc import DoclingDocument, DocItemLabel

from config import Settings
from parsers.pdf_router import PdfPageRouter, _flatten_document


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TABLE_MARKDOWN = "| Animal | Protein |\n|--------|----------|\n| Chicken | 31g |\n| Beef    | 26g |\n"
# Use ## (SECTION_HEADER) not # (TITLE) — docling's markdown parser maps:
#   #   → DocItemLabel.TITLE
#   ##+ → DocItemLabel.SECTION_HEADER
# The diagnostic block only logs SECTION_HEADER items, so a # heading produces
# zero log lines and the diagnostic test would always fail.
_TEXT_MARKDOWN  = "## Section Heading\n\nSome body text on this page."


# ---------------------------------------------------------------------------
# Test 1 — _flatten_document is never called by _merge_pages()
# ---------------------------------------------------------------------------

class TestFlattenReverted:
    def test_merge_pages_does_not_call_flatten(self):
        """_merge_pages() must NOT call _flatten_document() in v5.4+.

        The v5.3 regression: _flatten_document() only copied doc.texts, silently
        dropping every doc.tables entry.  This test would have caught it before
        the first real-PDF run.

        Approach: spy on _flatten_document; run _merge_pages with a page that
        produces a table; assert the spy was never called AND the result has
        non-empty doc.tables.
        """
        router = PdfPageRouter()
        flatten_spy = MagicMock(wraps=_flatten_document)

        page_markdowns = [
            _TEXT_MARKDOWN,      # page 1 — text
            _TABLE_MARKDOWN,     # page 2 — table (the item type that v5.3 dropped)
            _TEXT_MARKDOWN,      # page 3 — text
        ]

        with patch("parsers.pdf_router._flatten_document", flatten_spy):
            result = router._merge_pages(page_markdowns, "test.pdf")

        assert flatten_spy.call_count == 0, (
            "_flatten_document must NOT be called from _merge_pages() in v5.4 — "
            f"it was called {flatten_spy.call_count} time(s). Revert is incomplete."
        )

        assert len(result.tables) > 0, (
            "Tables must survive _merge_pages(). Got 0 tables — this is the v5.3 "
            "regression where _flatten_document() silently dropped doc.tables."
        )

    def test_merge_pages_preserves_table_content(self):
        """Table cell text must be reachable from the merged document's .tables."""
        router = PdfPageRouter()
        result = router._merge_pages([_TABLE_MARKDOWN, _TEXT_MARKDOWN], "test.pdf")

        assert len(result.tables) > 0, "At least one TableItem must be present after merge"

        # Verify at least one table has a non-empty grid
        has_content = any(
            t.data and t.data.num_rows > 0
            for t in result.tables
            if t.data is not None
        )
        assert has_content, (
            "At least one TableItem must have grid rows — table content was dropped"
        )

    def test_merge_pages_returns_combined_not_flat_copy(self):
        """_merge_pages() must return the original merged DoclingDocument,
        not a new flat copy that discards non-text items.

        In v5.3, _flatten_document() created a brand-new DoclingDocument and
        only copied doc.texts — this test would have caught that the returned
        object had fewer item types than the input.
        """
        router = PdfPageRouter()

        # Single page with both a table and text
        md = _TABLE_MARKDOWN + "\n\n" + _TEXT_MARKDOWN
        result = router._merge_pages([md], "test.pdf")

        text_count = len(result.texts)
        table_count = len(result.tables)

        assert text_count > 0, "Texts must survive merge"
        assert table_count > 0, (
            f"Tables must survive merge — got {table_count} tables, {text_count} texts. "
            "If this fails, _flatten_document (which only copies texts) is still active."
        )


# ---------------------------------------------------------------------------
# Test 2 — pdf_debug_heading_dump defaults off, no leakage into logs
# ---------------------------------------------------------------------------

class TestDebugHeadingDumpDefaultOff:
    def test_debug_heading_dump_default_false(self):
        """settings.pdf_debug_heading_dump must default to False/0.

        The diagnostic is only useful when explicitly enabled. If it defaulted
        to True it would emit verbose log lines in every production parse run.
        """
        settings = Settings()
        assert not settings.pdf_debug_heading_dump, (
            "pdf_debug_heading_dump must default to False. "
            "Set PDF_DEBUG_HEADING_DUMP=1 only for local diagnostic runs."
        )

    def test_no_heading_log_lines_emitted_by_default(self, caplog):
        """No HEADING/ORPHAN-CHECK log lines must appear from _merge_pages()
        unless PDF_DEBUG_HEADING_DUMP=1 is explicitly set.

        This ensures the diagnostic can never accidentally leak into production
        logs when the environment variable is absent (the common case).
        """
        router = PdfPageRouter()

        with caplog.at_level(logging.INFO, logger="parsers.pdf_router"):
            router._merge_pages([_TEXT_MARKDOWN, _TABLE_MARKDOWN], "test.pdf")

        diagnostic_lines = [
            line for line in caplog.messages
            if line.startswith("HEADING ") or line.startswith("ORPHAN-CHECK ")
        ]
        assert diagnostic_lines == [], (
            f"Diagnostic log lines must NOT appear when PDF_DEBUG_HEADING_DUMP is unset. "
            f"Got: {diagnostic_lines}"
        )

    def test_heading_log_lines_emitted_when_enabled(self, caplog):
        """When PDF_DEBUG_HEADING_DUMP is patched to True, at least one HEADING
        log line must be emitted for a page that contains a heading.

        This validates the diagnostic code path is actually reachable.
        """
        router = PdfPageRouter()

        # Temporarily override settings.pdf_debug_heading_dump to True
        from config import settings as real_settings
        patched_settings = Settings(
            **{
                k: True if k == "pdf_debug_heading_dump" else getattr(real_settings, k)
                for k in real_settings.__dataclass_fields__
            }
        )

        with patch("parsers.pdf_router.settings", patched_settings), \
             caplog.at_level(logging.INFO, logger="parsers.pdf_router"):
            router._merge_pages([_TEXT_MARKDOWN], "test.pdf")

        heading_lines = [l for l in caplog.messages if l.startswith("HEADING ")]
        assert len(heading_lines) >= 1, (
            "At least one HEADING log line must appear when pdf_debug_heading_dump=True "
            "and the input contains a SECTION_HEADER item."
        )
