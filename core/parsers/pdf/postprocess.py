from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from collections import Counter
from docling_core.types.doc import DoclingDocument

from .transforms.cellmarks import inject_marks
from .transforms.cleanup import clean_page_markdown, strip_running_lines
from .transforms.coverage import check_page, check_page_coverage
from .transforms.figures import inject_figure_cards
from .transforms.glyphs import normalize_glyphs
from .transforms.structure import (
    repair_pdf_headings,
    repair_pdf_structure,
    tag_toc_structures,
)

if TYPE_CHECKING:
    import fitz

logger = logging.getLogger(__name__)


class PdfPostProcessor:
    """
    Coordinates markdown-level and document-level transformations:
    - Markdown stage: glyph normalization, running footer/header stripping, token cleanup, table splitting.
    - Document stage: cross-page boilerplate demotion, heading freeze fixes, caption binding, releveling, ToC tagging.
    """

    def process_markdowns(
        self,
        markdowns: list[str],
        raw_texts: list[str] | None = None,
        vocab: Counter | None = None,
    ) -> list[str]:
        """Apply glyph normalization, coverage recovery, and markdown sanitation to extracted page markdowns."""
        
        # Normalize Wingdings & private use symbol fonts
        processed = [normalize_glyphs(md) for md in markdowns]

        # Strip repeating headers/footers across consecutive pages
        processed = strip_running_lines(processed)

        # Clean table structures, token debris, lost spaces, and excessive whitespace
        processed = [clean_page_markdown(md, vocab=vocab) for md in processed]

        # Coverage safety net: recover dropped raw text
        if raw_texts and len(raw_texts) == len(processed):
            running_lines: set[str] = set()
            repaired: list[str] = []
            for md, raw in zip(processed, raw_texts):
                try:
                    repaired.append(check_page(md, raw, running_lines))
                except Exception as exc:
                    logger.warning("Coverage check failed: %s", exc)
                    repaired.append(md)
            processed = repaired

        return processed

    def process_document(
        self,
        doc: DoclingDocument,
        pdf: fitz.Document | None = None,
        vocab: Counter | None = None,
    ) -> DoclingDocument:
        """Apply AST repairs, cellmarks detection, and heading hierarchy corrections to the merged DoclingDocument."""
        
        # Visual transforms: detect table availability checkmarks via bounding box collision
        if pdf is not None:
            for page in pdf:
                try:
                    inject_marks(doc, page)
                except Exception as exc:
                    logger.debug("Document-level inject_marks skipped: %s", exc)

        # Clean and deduplicate figure cards
        inject_figure_cards(doc)

        # Cross-page boilerplate demotion and heading level normalization
        repair_pdf_headings(doc, min_page_repeats=3)

        # Document-level AST repairs (captions, releveling, echoes, blacklist, vocab cleaning)
        repair_pdf_structure(doc, vocab=vocab)

        # Tag Table of Contents entries
        tag_toc_structures(doc)

        return doc
