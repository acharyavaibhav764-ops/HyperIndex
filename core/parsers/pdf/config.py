import os
from dataclasses import dataclass, field


def _get_bool(primary: str, fallback: str, default: str = "true") -> bool:
    """Read a boolean setting, checking the new semantic key first, then falling back to legacy."""
    val = os.getenv(primary)
    if val is None:
        val = os.getenv(fallback, default)
    return val.strip().lower() in ("true", "1", "yes")


def _get_int(primary: str, fallback: str, default: str) -> int:
    val = os.getenv(primary)
    if val is None:
        val = os.getenv(fallback, default)
    return int(val.strip())


def _get_float(primary: str, fallback: str, default: str) -> float:
    val = os.getenv(primary)
    if val is None:
        val = os.getenv(fallback, default)
    return float(val.strip())


@dataclass
class PdfParserSettings:
    """PDF-specific parsing, triage, OCR, and transform settings."""

    # Page Routing & Triage
    enable_page_router: bool = field(default_factory=lambda: _get_bool("PDF_ENABLE_PAGE_ROUTER", "ENABLE_PDF_PAGE_ROUTER", "true"))
    min_text_chars_for_text_route: int = field(default_factory=lambda: _get_int("PDF_MIN_TEXT_CHARS_FOR_TEXT_ROUTE", "PDF_MIN_TEXT_CHARS_FOR_TEXT_ROUTE", "800"))
    text_layer_min_chars: int = field(default_factory=lambda: _get_int("PDF_TEXT_LAYER_MIN_CHARS", "PDF_TEXT_LAYER_MIN_CHARS", "40"))
    allow_ocr_on_text_pages: bool = field(default_factory=lambda: _get_bool("PDF_ALLOW_OCR_ON_TEXT_PAGES", "PDF_ALLOW_OCR_ON_TEXT_PAGES", "false"))
    enable_text_cleanup: bool = field(default_factory=lambda: _get_bool("PDF_ENABLE_TEXT_CLEANUP", "PDF_V57_CLEANUP", "true"))
    boilerplate_min_page_repeats: int = field(default_factory=lambda: _get_int("PDF_BOILERPLATE_MIN_PAGE_REPEATS", "PDF_BOILERPLATE_MIN_PAGE_REPEATS", "3"))
    debug_heading_dump: bool = field(default_factory=lambda: _get_bool("PDF_DEBUG_HEADING_DUMP", "PDF_DEBUG_HEADING_DUMP", "false"))

    # Visual Domain & Cellmarks
    enable_cellmarks: bool = field(default_factory=lambda: _get_bool("PDF_ENABLE_CELLMARKS", "PDF_V59_CELLMARKS", "true"))
    cellmark_repeat_min: int = field(default_factory=lambda: _get_int("PDF_CELLMARK_REPEAT_MIN", "PDF_MARK_REPEAT_MIN", "3"))

    # Figures & VLM
    figure_mode: str = field(default_factory=lambda: os.getenv("PDF_FIGURE_MODE", "labels_only"))  # off / labels_only / vlm_fallback
    smolvlm_max_new_tokens: int = field(default_factory=lambda: int(os.getenv("PDF_SMOLVLM_MAX_NEW_TOKENS", "200")))

    # Text Coverage & Table Crosscheck
    enable_coverage_check: bool = field(default_factory=lambda: _get_bool("PDF_ENABLE_COVERAGE_CHECK", "PDF_V59_COVERAGE", "true"))
    coverage_recall_min: float = field(default_factory=lambda: _get_float("PDF_COVERAGE_RECALL_MIN", "PDF_COVERAGE_RECALL_MIN", "0.9"))
    coverage_near_match: float = field(default_factory=lambda: _get_float("PDF_COVERAGE_NEAR_MATCH", "PDF_COVERAGE_NEAR_MATCH", "0.75"))
    enable_table_crosscheck: bool = field(default_factory=lambda: _get_bool("PDF_ENABLE_TABLE_CROSSCHECK", "PDF_V59_TABLE_CROSSCHECK", "true"))


pdf_parser_settings = PdfParserSettings()
