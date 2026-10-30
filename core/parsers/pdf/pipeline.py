import logging
from typing import Any, Optional
import fitz
from docling_core.types.doc import DoclingDocument

from .config import PdfParserSettings, pdf_parser_settings
from .transforms.cellmarks import inject_marks
from .transforms.figures import process_pictures

logger = logging.getLogger(__name__)


def apply_page_transforms(
    doc: DoclingDocument,
    page_pdf_bytes: bytes,
    page_no: int,
    legend: Optional[dict[str, str]] = None,
    cfg: Optional[PdfParserSettings] = None,
    extract_figures: bool = True,
) -> list[dict[str, Any]]:
    """
    Apply fitz-dependent visual transformations to a single-page DoclingDocument.
    
    Orchestrates:
    1. Table cell availability marks injection (cellmarks).
    2. Visual figure diagram card extraction and OCR label association.
    
    Returns:
        List of generated figure cards (if figure_mode != 'off' and extract_figures=True).
    """
    settings = cfg or pdf_parser_settings
    cards: list[dict[str, Any]] = []

    should_process_figures = extract_figures and (settings.figure_mode != "off")
    if not (settings.enable_cellmarks or should_process_figures):
        return cards

    try:
        pdf_single = fitz.open(stream=page_pdf_bytes, filetype="pdf")
        page_fitz = pdf_single[0]
    except Exception as exc:
        logger.warning("apply_page_transforms: failed to open page %d in PyMuPDF: %s", page_no, exc)
        return cards

    try:
        # Step 1: Inject cellmarks into tables before export
        if settings.enable_cellmarks:
            try:
                inject_marks(doc, page_fitz, legend=legend, repeat_min=settings.cellmark_repeat_min)
            except Exception as exc:
                logger.warning("cellmarks: page %d failed: %s", page_no, exc)

        # Step 2: Extract picture cards & labels
        if should_process_figures:
            try:
                cards = process_pictures(
                    doc, page_fitz, heading_path=[], page_no=page_no, mode=settings.figure_mode
                )
            except Exception as exc:
                logger.warning("pdf_figures: page %d failed: %s", page_no, exc)
    finally:
        pdf_single.close()

    return cards

