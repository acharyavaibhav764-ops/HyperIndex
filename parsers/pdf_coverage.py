"""v5.9 WP4: Page text-coverage safety net.

Compares raw PyMuPDF text vs cleaned markdown per page.
Repairs near-matches in-place and appends uncovered lines as [Recovered text].

v5.9.1 fixes
  * Near-match is scored against the best single markdown LINE. v5.9 scored it against the whole
    page, so the ratio was ~0 and no in-place repair could ever fire.
  * Table-of-contents pages (>= 60 % dot-leader lines) are skipped, and dot-leader lines are never
    re-added as recovered text.
  * In-place repair keeps the list / heading prefix and never rewrites markdown table rows.
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

_NORM_RE = re.compile(r"[\s\W]+")
_FIGURE_LABEL_RE = re.compile(r"^(?:[A-Z]{1,6}\s*\d*|Fig\.?\s*\d+|Figure\s*\d+)$", re.I)
_TOC_LINE_RE = re.compile(r"\.{3,}\s*\d+\s*$")
_MD_PREFIX_RE = re.compile(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s+)")
_TOC_PAGE_RATIO = 0.6


def _norm(text: str) -> str:
    return _NORM_RE.sub(" ", text.lower()).strip()


def _is_figure_label(line: str) -> bool:
    return bool(_FIGURE_LABEL_RE.match(line.strip())) and len(line.strip()) < 40


def _is_toc_page(raw_lines: list[str]) -> bool:
    dotted = sum(1 for ln in raw_lines if _TOC_LINE_RE.search(ln))
    return dotted >= 5 and dotted / len(raw_lines) >= _TOC_PAGE_RATIO


def _best_line(n_raw: str, md_lines: list[str], md_norms: list[str]) -> tuple[int, float]:
    """Index and difflib ratio of the most similar non-table markdown line."""
    best_i, best_r = -1, 0.0
    lr = len(n_raw)
    for i, n in enumerate(md_norms):
        if not n or md_lines[i].lstrip().startswith("|"):
            continue
        if len(n) > lr * 2 or len(n) * 2 < lr:
            continue
        sm = SequenceMatcher(None, n_raw, n, autojunk=False)
        if sm.real_quick_ratio() <= best_r or sm.quick_ratio() <= best_r:
            continue
        r = sm.ratio()
        if r > best_r:
            best_i, best_r = i, r
    return best_i, best_r


def _with_prefix(md_line: str, raw_line: str) -> str:
    m = _MD_PREFIX_RE.match(md_line)
    prefix = m.group(0) if m else ""
    return prefix + raw_line.lstrip("-*+\u2022 ").strip()


def check_page(
    page_md: str,
    raw_text: str,
    running_lines: set[str],
    *,
    toc_page: bool = False,
    recall_min: float = 0.9,
    near_match_ratio: float = 0.75,
) -> str:
    """Check coverage and repair/append uncovered text for one page.

    Args:
        page_md:          Cleaned markdown for this page.
        raw_text:         Raw PyMuPDF text (page.get_text()).
        running_lines:    Boilerplate strings from strip_running_lines.
        toc_page:         If True, skip this page entirely (auto-detected when False).
        recall_min:       Warn when recall drops below this.
        near_match_ratio: difflib ratio threshold for in-place repair.

    Returns:
        Modified page_md with near-match repairs and optional recovered-text block.
    """
    if toc_page or not raw_text.strip():
        return page_md

    raw_lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    if not raw_lines or _is_toc_page(raw_lines):
        return page_md

    try:
        from parsers.pdf_cleanup import is_noise_paragraph
    except Exception:  # pdf_cleanup pulls in heavy deps; the noise test is optional
        is_noise_paragraph = None

    md_lines = page_md.split("\n")
    md_norms = [_norm(ln) for ln in md_lines]
    md_all = " ".join(n for n in md_norms if n)
    norm_running = {_norm(r) for r in running_lines}
    covered: list[bool] = []
    uncovered: list[str] = []

    for raw_line in raw_lines:
        n_raw = _norm(raw_line)
        if (
            not n_raw
            or n_raw in norm_running
            or _is_figure_label(raw_line)
            or _TOC_LINE_RE.search(raw_line)
            or (is_noise_paragraph is not None and is_noise_paragraph(raw_line))
        ):
            covered.append(True)
            continue

        if n_raw in md_all:
            covered.append(True)
            continue

        idx, ratio = _best_line(n_raw, md_lines, md_norms)
        if idx >= 0 and ratio >= near_match_ratio:
            if len(n_raw) > len(md_norms[idx]):  # md line lost words -> restore from text layer
                md_lines[idx] = _with_prefix(md_lines[idx], raw_line)
                md_norms[idx] = n_raw
                md_all = " ".join(n for n in md_norms if n)
            covered.append(True)
            continue

        covered.append(False)
        uncovered.append(raw_line)

    total = len(covered)
    n_cov = sum(covered)
    recall = n_cov / total if total else 1.0
    if recall < recall_min:
        logger.warning(
            "coverage: recall=%.2f < %.2f -- %d/%d lines uncovered",
            recall, recall_min, total - n_cov, total,
        )

    repaired = "\n".join(md_lines)
    if uncovered:
        repaired = repaired.rstrip() + "\n\n[Recovered text]\n" + "\n".join(uncovered)
    return repaired
