from __future__ import annotations

from docling_core.types.doc import DoclingDocument

from .transforms.cleanup import clean_markdown_page, strip_running_lines
from .transforms.glyphs import normalize_glyphs
from .transforms.structure import repair_headings, tag_toc_structures


class PdfPostProcessor:
    """
    Coordinates markdown-level and document-level transformations:
    - Markdown stage: glyph normalization, running footer/header stripping, token cleanup.
    - Document stage: heading freeze fixes, heading depth normalization, ToC tagging.
    """

    def process_markdowns(self, markdowns: list[str]) -> list[str]:
        """Apply glyph normalization and markdown sanitation to extracted page markdowns."""
        
        # Normalize Wingdings & private use symbol fonts
        processed = [normalize_glyphs(md) for md in markdowns]

        # Strip repeating headers/footers across consecutive pages
        processed = strip_running_lines(processed)

        # Clean token debris and excessive whitespace
        processed = [clean_markdown_page(md) for md in processed]

        return processed

    def process_document(self, doc: DoclingDocument) -> DoclingDocument:
        """Apply AST repairs and heading hierarchy corrections to the merged DoclingDocument."""
        
        # Fix heading freeze and normalize section levels
        repair_headings(doc)

        # Tag Table of Contents entries
        tag_toc_structures(doc)

        return doc

