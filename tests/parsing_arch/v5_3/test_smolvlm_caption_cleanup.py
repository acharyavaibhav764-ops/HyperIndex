"""
tests/parsing_arch/v5_3/test_smolvlm_caption_cleanup.py

v5.3 regression tests for Fix 1: _smolvlm_page() now calls
_inject_picture_descriptions() before export_to_markdown(), applying the same
token-cleanup and [Figure description] tagging used on the table+image path.

Test inventory:
  1. test_smolvlm_page_strips_dangling_token
  2. test_smolvlm_page_adds_figure_description_prefix
  3. test_smolvlm_page_and_picture_descriptions_only_produce_consistent_tagging
"""
import pytest
from unittest.mock import MagicMock, patch

from docling_core.types.doc import DoclingDocument, DocItemLabel


# ---------------------------------------------------------------------------
# Helper: build a mock VLM converter that returns a document with one picture
# whose description ends in a dangling completion token.
# ---------------------------------------------------------------------------

def _make_mock_vlm_converter(description_text: str):
    """Return a MagicMock VLM converter whose convert() produces a
    DoclingDocument with one PICTURE item carrying the given description."""
    from docling_core.types.doc import PictureItem, BoundingBox, ProvenanceItem

    doc = DoclingDocument(name="page.pdf")

    # Add a picture with the raw VLM description text
    pic = doc.add_picture()
    # Set the picture's annotations so _inject_picture_descriptions can find the description
    pic.annotations = []  # will be populated by adding a description annotation

    # Inject raw description text directly via PictureItem attributes
    # _inject_picture_descriptions reads pic.captions or annotations depending on version;
    # we mock at the export level to test the integration contract.

    mock_result = MagicMock()
    mock_doc = MagicMock()
    mock_doc.export_to_markdown.return_value = (
        f"[Figure description] {description_text.split('<')[0].strip()}"
        if "<" not in description_text
        else f"[Figure description] {description_text.split('<')[0].strip()}"
    )
    mock_result.document = mock_doc
    mock_converter = MagicMock()
    mock_converter.convert.return_value = mock_result
    return mock_converter


# ---------------------------------------------------------------------------
# Test 1 — dangling token is stripped
# ---------------------------------------------------------------------------

class TestSmolVLMPageCleanup:
    def test_smolvlm_page_calls_inject_picture_descriptions(self):
        """_smolvlm_page() must call _inject_picture_descriptions(doc) before
        exporting to markdown — i.e. the cleanup function is invoked on the
        image-only path.
        """
        from parsers.pdf_router import PdfPageRouter

        router = PdfPageRouter()

        mock_doc = MagicMock()
        mock_doc.export_to_markdown.return_value = "[Figure description] Two men standing."

        mock_result = MagicMock()
        mock_result.document = mock_doc

        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_result
        router._vlm_converter = mock_converter

        inject_spy = MagicMock()

        with patch("parsers.pdf_router._inject_picture_descriptions", inject_spy):
            router._smolvlm_page(b"fake-pdf", "test.pdf", 0)

        inject_spy.assert_called_once_with(mock_doc), (
            "_inject_picture_descriptions must be called on the document before export"
        )

    def test_smolvlm_page_strips_dangling_token(self):
        """End-to-end: verify that after _smolvlm_page(), the returned markdown
        does not contain any '<' token fragment (the class of garbage that leaked
        into chunk #1 in the real run: '...smiling.<end_of_utteranc').

        Mocks _inject_picture_descriptions to apply the same regex cleanup that
        the real function applies, simulating what happens after Fix 1.
        """
        from parsers.pdf_router import PdfPageRouter

        router = PdfPageRouter()

        # Simulate a raw VLM doc whose picture description has a dangling token
        raw_md = "In this image there are two men standing and smiling.<end_of_utteranc"

        mock_doc = MagicMock()

        def _fake_inject(doc):
            # Simulate what _inject_picture_descriptions does: strip the dangling token
            import re
            cleaned = re.sub(r"<[a-z_]{0,40}\s*$", "", raw_md).strip()
            doc.export_to_markdown.return_value = f"[Figure description] {cleaned}"

        mock_doc.export_to_markdown.return_value = raw_md  # before cleanup
        mock_result = MagicMock()
        mock_result.document = mock_doc
        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_result
        router._vlm_converter = mock_converter

        with patch("parsers.pdf_router._inject_picture_descriptions", side_effect=_fake_inject):
            result = router._smolvlm_page(b"fake-pdf", "test.pdf", 0)

        assert "<" not in result, (
            f"Dangling token fragment must be stripped; got: {result!r}"
        )
        assert "[Figure description]" in result, (
            f"[Figure description] prefix must be present; got: {result!r}"
        )

    def test_smolvlm_page_and_picture_descriptions_only_both_call_inject(self):
        """Both _smolvlm_page() and _picture_descriptions_only() must call
        _inject_picture_descriptions() — closing the pre-v5.3 asymmetry where
        only the table+image path ran cleanup.
        """
        from parsers.pdf_router import PdfPageRouter

        router = PdfPageRouter()

        mock_doc = MagicMock()
        mock_doc.export_to_markdown.return_value = "[Figure description] Test."
        mock_doc.texts = []  # _picture_descriptions_only iterates doc.texts for CAPTION items

        mock_result = MagicMock()
        mock_result.document = mock_doc

        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_result
        router._vlm_converter = mock_converter

        smolvlm_inject_calls = []
        pdo_inject_calls = []

        def _spy_inject_smolvlm(doc):
            smolvlm_inject_calls.append(doc)

        def _spy_inject_pdo(doc):
            pdo_inject_calls.append(doc)

        # Test _smolvlm_page
        with patch("parsers.pdf_router._inject_picture_descriptions", _spy_inject_smolvlm):
            router._smolvlm_page(b"fake-pdf", "test.pdf", 0)

        # Test _picture_descriptions_only (needs fresh mock)
        mock_result2 = MagicMock()
        mock_result2.document = mock_doc
        mock_converter.convert.return_value = mock_result2

        with patch("parsers.pdf_router._inject_picture_descriptions", _spy_inject_pdo):
            router._picture_descriptions_only(b"fake-pdf", "test.pdf", 0)

        assert len(smolvlm_inject_calls) == 1, "_smolvlm_page must call _inject_picture_descriptions once"
        assert len(pdo_inject_calls) == 1, "_picture_descriptions_only must call _inject_picture_descriptions once"
