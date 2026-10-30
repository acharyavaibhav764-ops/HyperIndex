import os
import pytest
from core.parsers.pdf.config import PdfParserSettings, _get_bool, _get_int, _get_float


def test_pdf_parser_settings_defaults():
    """Verify clean default values for PdfParserSettings."""
    cfg = PdfParserSettings()
    assert cfg.enable_page_router is True
    assert cfg.min_text_chars_for_text_route == 800
    assert cfg.text_layer_min_chars == 40
    assert cfg.allow_ocr_on_text_pages is False
    assert cfg.enable_text_cleanup is True
    assert cfg.boilerplate_min_page_repeats == 3
    assert cfg.debug_heading_dump is False
    assert cfg.enable_cellmarks is True
    assert cfg.cellmark_repeat_min == 3
    assert cfg.figure_mode == "labels_only"
    assert cfg.smolvlm_max_new_tokens == 200
    assert cfg.enable_coverage_check is True
    assert cfg.coverage_recall_min == 0.9
    assert cfg.coverage_near_match == 0.75
    assert cfg.enable_table_crosscheck is True


def test_pdf_parser_settings_legacy_fallbacks(monkeypatch):
    """Verify that legacy env vars (e.g. PDF_V59_CELLMARKS) are honored when canonical vars are unset."""
    monkeypatch.setenv("PDF_V59_CELLMARKS", "false")
    monkeypatch.setenv("PDF_MARK_REPEAT_MIN", "5")
    monkeypatch.setenv("PDF_V59_COVERAGE", "false")
    monkeypatch.setenv("PDF_COVERAGE_RECALL_MIN", "0.85")
    monkeypatch.delenv("PDF_ENABLE_CELLMARKS", raising=False)
    monkeypatch.delenv("PDF_CELLMARK_REPEAT_MIN", raising=False)
    monkeypatch.delenv("PDF_ENABLE_COVERAGE_CHECK", raising=False)

    cfg = PdfParserSettings()
    assert cfg.enable_cellmarks is False
    assert cfg.cellmark_repeat_min == 5
    assert cfg.enable_coverage_check is False
    assert cfg.coverage_recall_min == 0.85


def test_pdf_parser_settings_canonical_overrides(monkeypatch):
    """Verify that canonical semantic env vars take precedence over legacy aliases."""
    monkeypatch.setenv("PDF_ENABLE_CELLMARKS", "true")
    monkeypatch.setenv("PDF_V59_CELLMARKS", "false")
    monkeypatch.setenv("PDF_ENABLE_COVERAGE_CHECK", "true")
    monkeypatch.setenv("PDF_V59_COVERAGE", "false")

    cfg = PdfParserSettings()
    assert cfg.enable_cellmarks is True
    assert cfg.enable_coverage_check is True

