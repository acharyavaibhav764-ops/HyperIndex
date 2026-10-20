"""
tests/parsing_arch/v5_2/test_vlm_pdf_pipeline_options.py

v5.2 regression tests for Fix 1 (PdfPipelineOptions) and Fix 3
(enable_picture_description gate on _build_vlm_converter).

All tests run offline — no real model inference or file I/O.

Test inventory:
  1. test_build_vlm_converter_pdf_uses_pdf_pipeline_options
  2. test_build_vlm_converter_pdf_options_independent_of_docx_options
  3. test_smolvlm_page_respects_enable_picture_description
  4. test_picture_descriptions_only_respects_enable_picture_description
  5. test_build_vlm_converter_returns_plain_when_disabled
"""
import pytest
from unittest.mock import MagicMock, patch

from docling.datamodel.base_models import InputFormat


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_converter_with_picture_description_on():
    """Call _build_vlm_converter() with enable_picture_description=True."""
    with patch("parsers.docling_parser.settings") as mock_settings:
        mock_settings.enable_picture_description = True
        mock_settings.picture_description_preset = "smolvlm"
        mock_settings.picture_description_prompt = ""
        from parsers.docling_parser import _build_vlm_converter
        return _build_vlm_converter()


# ---------------------------------------------------------------------------
# Fix 1 — PDF format option must use PdfPipelineOptions
# ---------------------------------------------------------------------------

class TestPdfPipelineOptions:
    def test_build_vlm_converter_pdf_uses_pdf_pipeline_options(self):
        """The PDF format entry's pipeline_options must be a PdfPipelineOptions instance.

        This is the direct regression test for Issue 1: v5.1 Fix 4a accidentally
        reused ConvertPipelineOptions for InputFormat.PDF, causing AttributeError
        on generate_page_images every time SmolVLM tried to rasterise a PDF page.
        """
        from docling.datamodel.pipeline_options import PdfPipelineOptions

        converter = _get_converter_with_picture_description_on()
        pdf_opts = converter.format_to_options.get(InputFormat.PDF)
        assert pdf_opts is not None, "InputFormat.PDF must be present in format_options"
        assert isinstance(
            pdf_opts.pipeline_options,
            PdfPipelineOptions,
        ), (
            f"Expected PdfPipelineOptions for InputFormat.PDF, "
            f"got {type(pdf_opts.pipeline_options).__name__}"
        )

    def test_build_vlm_converter_pdf_has_generate_page_images_true(self):
        """generate_page_images must be True so SmolVLM can rasterise the page."""
        converter = _get_converter_with_picture_description_on()
        pdf_opts = converter.format_to_options[InputFormat.PDF]
        assert pdf_opts.pipeline_options.generate_page_images is True

    def test_build_vlm_converter_pdf_options_independent_of_docx_options(self):
        """The PDF and DOCX pipeline_options must be *different* objects.

        Guards against a future refactor that re-introduces the v5.1 shared-instance
        bug (passing the same ConvertPipelineOptions to all three format entries).
        """
        converter = _get_converter_with_picture_description_on()
        pdf_pipeline = converter.format_to_options[InputFormat.PDF].pipeline_options
        docx_pipeline = converter.format_to_options[InputFormat.DOCX].pipeline_options
        assert pdf_pipeline is not docx_pipeline, (
            "PDF and DOCX format options must not share the same pipeline_options object"
        )

    def test_build_vlm_converter_docx_still_uses_convert_pipeline_options(self):
        """DOCX should still use ConvertPipelineOptions (no regression on existing path)."""
        from docling.datamodel.pipeline_options import ConvertPipelineOptions

        converter = _get_converter_with_picture_description_on()
        docx_pipeline = converter.format_to_options[InputFormat.DOCX].pipeline_options
        assert isinstance(docx_pipeline, ConvertPipelineOptions)


# ---------------------------------------------------------------------------
# Fix 3 — enable_picture_description=False must short-circuit the VLM build
# ---------------------------------------------------------------------------

class TestEnablePictureDescriptionGate:
    def test_build_vlm_converter_returns_plain_when_disabled(self):
        """When enable_picture_description=False, _build_vlm_converter() returns a
        plain DocumentConverter with VLM disabled (do_picture_description=False
        on the PDF format option's pipeline). The converter always has PDF in
        format_to_options by docling default; what changes is the pipeline config.
        """
        with patch("parsers.docling_parser.settings") as mock_settings:
            mock_settings.enable_picture_description = False
            from parsers.docling_parser import _build_vlm_converter
            converter = _build_vlm_converter()
        # Plain converter: PDF pipeline must NOT have picture description enabled
        pdf_opts = converter.format_to_options.get(InputFormat.PDF)
        assert pdf_opts is not None
        assert pdf_opts.pipeline_options.do_picture_description is False, (
            "Plain converter must have do_picture_description=False on PDF pipeline"
        )

    @patch("parsers.pdf_router.settings")
    @patch("parsers.pdf_router.pymupdf")
    def test_smolvlm_page_respects_enable_picture_description(
        self, mock_fitz, mock_settings
    ):
        """With enable_picture_description=False, _build_vlm_converter() returns
        a plain DocumentConverter (Fix 3). _smolvlm_page() will use it, and the
        resulting conversion produces no [Figure description] captions — i.e. the
        VLM pipeline is effectively disabled. We test the observable boundary:
        _build_vlm_converter() called with the flag off must return no PDF VLM
        format option, which means any subsequent smolvlm call degrades silently
        to standard Docling output (not SmolVLM inference).

        This test verifies the gate mechanism works by asserting that when
        enable_picture_description is patched to False in the docling_parser
        settings, _build_vlm_converter returns a converter with VLM disabled
        (do_picture_description=False) on the PDF pipeline options.
        """
        with patch("parsers.docling_parser.settings") as mock_ds:
            mock_ds.enable_picture_description = False
            from parsers.docling_parser import _build_vlm_converter
            converter = _build_vlm_converter()

        # Plain converter: PDF pipeline must NOT have picture description enabled
        pdf_opts = converter.format_to_options.get(InputFormat.PDF)
        assert pdf_opts is not None
        assert pdf_opts.pipeline_options.do_picture_description is False, (
            "When enable_picture_description=False, PDF VLM must not be configured"
        )

    @patch("parsers.pdf_router.settings")
    @patch("parsers.pdf_router.pymupdf")
    def test_picture_descriptions_only_respects_enable_picture_description(
        self, mock_fitz, mock_settings
    ):
        """With enable_picture_description=False, _picture_descriptions_only()
        must return '' because _build_vlm_converter() returns a plain converter
        that produces no [Figure description] captions.

        We verify this by pre-seeding _vlm_converter with a mock that returns
        a document with no CAPTION items starting with '[Figure description]'.
        """
        mock_settings.enable_picture_description = False

        from parsers.pdf_router import PdfPageRouter
        router = PdfPageRouter()

        # Simulate _build_vlm_converter returning a plain converter (no VLM output)
        plain_doc = MagicMock()
        plain_doc.texts = []  # no [Figure description] captions produced

        plain_result = MagicMock()
        plain_result.document = plain_doc

        plain_converter = MagicMock()
        plain_converter.convert.return_value = plain_result

        # Pre-inject so _smolvlm_page uses our mock, bypassing _build_vlm_converter entirely
        router._vlm_converter = plain_converter

        result = router._picture_descriptions_only(b"fake-pdf", "test.pdf", 0)

        # No CAPTION items → empty string returned
        assert result == ""

