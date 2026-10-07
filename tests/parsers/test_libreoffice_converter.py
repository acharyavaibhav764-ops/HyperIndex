"""
Unit tests for LibreOfficeConverter (Parsing Architecture v3).

All tests use mocks — no real LibreOffice installation or Office files required.
"""
from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from core.parsers.libreoffice_converter import (
    LibreOfficeConversionError,
    LibreOfficeConverter,
    LibreOfficeNotFoundError,
    find_libreoffice_binary,
)
from core.parsers.router import ParserRouter


FAKE_DOC_BYTES = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504  # OLE2 header
FAKE_PPT_BYTES = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x01" * 504
FAKE_BINARY = "/usr/bin/soffice"


# ---------------------------------------------------------------------------
# Phase 1: find_libreoffice_binary — resolution order
# ---------------------------------------------------------------------------

class TestFindLibreOfficeBinary:
    def test_uses_configured_path_if_file_exists(self, tmp_path):
        fake_bin = tmp_path / "soffice"
        fake_bin.touch()
        with patch("core.parsers.libreoffice_converter.settings") as mock_settings:
            mock_settings.libreoffice_binary = str(fake_bin)
            result = find_libreoffice_binary()
        assert result == str(fake_bin)

    def test_falls_back_to_which(self):
        with patch("core.parsers.libreoffice_converter.settings") as mock_settings, \
             patch("shutil.which", return_value=FAKE_BINARY) as mock_which:
            mock_settings.libreoffice_binary = ""
            result = find_libreoffice_binary()
        assert result == FAKE_BINARY

    def test_raises_when_not_found(self):
        with patch("core.parsers.libreoffice_converter.settings") as mock_settings, \
             patch("shutil.which", return_value=None), \
             patch("pathlib.Path.is_file", return_value=False):
            mock_settings.libreoffice_binary = ""
            with pytest.raises(LibreOfficeNotFoundError):
                find_libreoffice_binary()


# ---------------------------------------------------------------------------
# Phase 1: convert_to_openxml — command construction & error cases
# ---------------------------------------------------------------------------

class TestConvertToOpenxml:
    def _make_converter(self) -> LibreOfficeConverter:
        return LibreOfficeConverter(timeout=30)

    @patch("core.parsers.libreoffice_converter.find_libreoffice_binary", return_value=FAKE_BINARY)
    def test_doc_conversion_uses_correct_format_flag(self, _mock_bin):
        converter = self._make_converter()
        captured_cmd = []

        def fake_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            outdir_idx = cmd.index("--outdir")
            outdir = Path(cmd[outdir_idx + 1])
            (outdir / "input.docx").write_bytes(b"docx bytes")
            r = MagicMock(); r.returncode = 0; r.stderr = ""; r.stdout = ""; return r

        with patch("subprocess.run", side_effect=fake_run):
            converted, out_name = converter.convert_to_openxml(FAKE_DOC_BYTES, "report.doc")

        assert "--convert-to" in captured_cmd
        assert captured_cmd[captured_cmd.index("--convert-to") + 1] == "docx"
        assert "--headless" in captured_cmd
        assert any("-env:UserInstallation=" in arg for arg in captured_cmd)
        assert out_name == "report.docx"
        assert converted == b"docx bytes"

    @patch("core.parsers.libreoffice_converter.find_libreoffice_binary", return_value=FAKE_BINARY)
    def test_ppt_conversion_uses_pptx_format(self, _mock_bin):
        converter = self._make_converter()
        captured_cmd = []

        def fake_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            outdir_idx = cmd.index("--outdir")
            outdir = Path(cmd[outdir_idx + 1])
            (outdir / "input.pptx").write_bytes(b"pptx bytes")
            r = MagicMock(); r.returncode = 0; r.stderr = ""; r.stdout = ""; return r

        with patch("subprocess.run", side_effect=fake_run):
            converted, out_name = converter.convert_to_openxml(FAKE_PPT_BYTES, "slides.ppt")

        assert captured_cmd[captured_cmd.index("--convert-to") + 1] == "pptx"
        assert out_name == "slides.pptx"

    @patch("core.parsers.libreoffice_converter.find_libreoffice_binary", return_value=FAKE_BINARY)
    def test_timeout_raises_conversion_error(self, _mock_bin):
        converter = self._make_converter()
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=[], timeout=30)):
            with pytest.raises(LibreOfficeConversionError, match="timed out"):
                converter.convert_to_openxml(FAKE_DOC_BYTES, "report.doc")

    @patch("core.parsers.libreoffice_converter.find_libreoffice_binary", return_value=FAKE_BINARY)
    def test_nonzero_exit_raises_conversion_error(self, _mock_bin):
        converter = self._make_converter()
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = "permission denied"
        mock_proc.stdout = ""
        with patch("subprocess.run", return_value=mock_proc):
            with pytest.raises(LibreOfficeConversionError, match="permission denied"):
                converter.convert_to_openxml(FAKE_DOC_BYTES, "report.doc")

    @patch("core.parsers.libreoffice_converter.find_libreoffice_binary", return_value=FAKE_BINARY)
    def test_missing_output_file_raises_conversion_error(self, _mock_bin):
        converter = self._make_converter()
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = ""
        mock_proc.stdout = ""
        # Don't write the expected output file — conversion "succeeded" but produced nothing
        with patch("subprocess.run", return_value=mock_proc):
            with pytest.raises(LibreOfficeConversionError, match="failed to produce output"):
                converter.convert_to_openxml(FAKE_DOC_BYTES, "report.doc")

    def test_unsupported_format_raises_value_error(self):
        converter = self._make_converter()
        with pytest.raises(ValueError, match="Unsupported legacy format"):
            converter.convert_to_openxml(b"bytes", "file.odt")


# ---------------------------------------------------------------------------
# Phase 2: LibreOfficeConverter.parse — delegation to DoclingParser
# ---------------------------------------------------------------------------

class TestLibreOfficeConverterParse:
    def test_can_handle_doc_and_ppt(self):
        c = LibreOfficeConverter()
        assert c.can_handle(".doc") is True
        assert c.can_handle(".DOC") is True
        assert c.can_handle(".ppt") is True
        assert c.can_handle(".docx") is False
        assert c.can_handle(".txt") is False

    def test_parse_delegates_to_docling_parser(self):
        mock_docling = MagicMock()
        mock_doc = MagicMock()
        mock_docling.parse.return_value = mock_doc

        converter = LibreOfficeConverter(docling_parser=mock_docling)

        with patch.object(converter, "convert_to_openxml", return_value=(b"converted", "report.docx")):
            result = converter.parse(FAKE_DOC_BYTES, "report.doc")

        mock_docling.parse.assert_called_once_with(b"converted", "report.docx")
        assert result is mock_doc

    def test_parse_ppt_delegates_with_pptx_filename(self):
        mock_docling = MagicMock()
        converter = LibreOfficeConverter(docling_parser=mock_docling)

        with patch.object(converter, "convert_to_openxml", return_value=(b"pptx bytes", "slides.pptx")):
            converter.parse(FAKE_PPT_BYTES, "slides.ppt")

        mock_docling.parse.assert_called_once_with(b"pptx bytes", "slides.pptx")


# ---------------------------------------------------------------------------
# Phase 3: Router dispatch
# ---------------------------------------------------------------------------

class TestRouterDispatch:
    def test_doc_dispatches_to_libreoffice_converter(self):
        router = ParserRouter()
        parser = router.get_parser("document.doc")
        assert isinstance(parser, LibreOfficeConverter)

    def test_ppt_dispatches_to_libreoffice_converter(self):
        router = ParserRouter()
        parser = router.get_parser("slides.ppt")
        assert isinstance(parser, LibreOfficeConverter)

    def test_supported_extensions_includes_doc_and_ppt(self):
        router = ParserRouter()
        exts = router._supported_extensions()
        assert ".doc" in exts
        assert ".ppt" in exts

    def test_supported_extensions_full_list(self):
        router = ParserRouter()
        exts = router._supported_extensions()
        for ext in (".doc", ".docx", ".md", ".ppt", ".pptx", ".txt"):
            assert ext in exts, f"Expected '{ext}' in supported extensions"
