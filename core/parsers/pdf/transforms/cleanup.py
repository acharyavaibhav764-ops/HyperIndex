from __future__ import annotations

import re
from collections import Counter

# Pattern for model generation tokens leaking into markdown
_VLM_TOKEN_RE = re.compile(r"<[a-z_0-9]{1,40}>|<[a-z_0-9]{0,40}\s*$")

# Inline markdown emphasis that can disrupt sentence boundary detection
_EMPHASIS_RE = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")


def strip_vlm_tokens(text: str) -> str:
    """Scrub raw completion tokens (e.g. <end_of_utteranc>, <unused0>) from text."""
    
    if not text:
        return text
    cleaned = _VLM_TOKEN_RE.sub("", text)
    return cleaned.strip()


def strip_running_lines(page_markdowns: list[str]) -> list[str]:
    """Detect and strip boilerplate headers and footers that repeat across consecutive pages."""
    
    if len(page_markdowns) < 2:
        return page_markdowns

    # Identify lines that appear at the very top or bottom of >= 50% of pages
    first_lines: list[str] = []
    last_lines: list[str] = []

    for md in page_markdowns:
        lines = [line.strip() for line in md.split("\n") if line.strip()]
        if lines:
            first_lines.append(lines[0])
            last_lines.append(lines[-1])

    threshold = max(2, len(page_markdowns) // 2)
    top_boilerplate = {line for line, count in Counter(first_lines).items() if count >= threshold}
    bottom_boilerplate = {line for line, count in Counter(last_lines).items() if count >= threshold}

    # Remove the detected boilerplate lines
    cleaned_pages: list[str] = []
    for md in page_markdowns:
        lines = md.split("\n")
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped in top_boilerplate or stripped in bottom_boilerplate:
                continue
            new_lines.append(line)
        cleaned_pages.append("\n".join(new_lines))

    return cleaned_pages


def clean_markdown_page(md: str) -> str:
    """
    Apply markdown text sanitization:
    - Strips leaked VLM tokens.
    - Normalizes double whitespace and empty code markers.
    """
    
    if not md:
        return md
    md = strip_vlm_tokens(md)
    
    # Collapse multiple consecutive blank lines to at most two
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md

