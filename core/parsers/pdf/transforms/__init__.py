from .cellmarks import inject_marks, scan_legend
from .cleanup import clean_markdown_page, strip_running_lines, strip_vlm_tokens
from .coverage import check_page_coverage
from .figures import inject_figure_cards
from .glyphs import normalize_glyphs, strip_glyphs
from .structure import repair_headings, tag_toc_structures

__all__ = [
    "clean_markdown_page",
    "check_page_coverage",
    "inject_figure_cards",
    "inject_marks",
    "normalize_glyphs",
    "repair_headings",
    "scan_legend",
    "strip_glyphs",
    "strip_running_lines",
    "strip_vlm_tokens",
    "tag_toc_structures",
]
