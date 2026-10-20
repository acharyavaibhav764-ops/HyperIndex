from __future__ import annotations

from typing import TYPE_CHECKING
from docling_core.types.doc import DoclingDocument

from .transforms.cellmarks import inject_marks
from .transforms.cleanup import clean_markdown_page, strip_running_lines
from .transforms.coverage import check_page_coverage
from .transforms.figures import inject_figure_cards
from .transforms.glyphs import normalize_glyphs
from .transforms.structure import repair_headings, tag_toc_structures

if TYPE_CHECKING:
    import fitz


class PdfPostProcessor:
    """
    Coordinates markdown-level and document-level transformations:
    - Markdown stage: glyph normalization, running footer/header stripping, token cleanup.
    - Document stage: heading freeze fixes, heading depth normalization, ToC tagging.
    """

    def process_markdowns(
        self,
        markdowns: list[str],
        raw_texts: list[str] | None = None,
    ) -> list[str]:
        """Apply glyph normalization, coverage recovery, and markdown sanitation to extracted page markdowns."""
        
        # Normalize Wingdings & private use symbol fonts
        processed = [normalize_glyphs(md) for md in markdowns]

        # Strip repeating headers/footers across consecutive pages
        processed = strip_running_lines(processed)

        # Clean token debris and excessive whitespace
        processed = [clean_markdown_page(md) for md in processed]

        # Coverage safety net: recover dropped raw text
        if raw_texts and len(raw_texts) == len(processed):
            processed = [
                check_page_coverage(md, raw)
                for md, raw in zip(processed, raw_texts)
            ]

        return processed

    def process_document(
        self,
        doc: DoclingDocument,
        pdf: fitz.Document | None = None,
    ) -> DoclingDocument:
        """Apply AST repairs, cellmarks detection, and heading hierarchy corrections to the merged DoclingDocument."""
        
        # Visual transforms: detect table availability checkmarks via bounding box collision
        if pdf is not None:
            for page_idx, page in enumerate(pdf):
                inject_marks(doc, page, page_idx + 1)

        # Clean and deduplicate figure cards
        inject_figure_cards(doc)

        # Fix heading freeze and normalize section levels
        repair_headings(doc)

        # Tag Table of Contents entries
        tag_toc_structures(doc)

        return doc
