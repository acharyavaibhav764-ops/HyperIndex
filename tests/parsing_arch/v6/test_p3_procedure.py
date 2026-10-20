"""v6 phase 3: step-by-step illustration pages -> one ordered Procedure chunk."""
import dataclasses

import pymupdf
import pytest
from docling_core.types.doc import BoundingBox, CoordOrigin, DoclingDocument, ProvenanceItem, Size
from docling_core.types.doc.document import (
    PictureClassificationMetaField, PictureClassificationPrediction, PictureMeta,
)

from parsers.pdf_v6 import cards, procedure

H = 842.0
STEPS = [
    "Reinsert the PCB and latch in place.",
    "Insert the connecting cables and mark them with the enclosed labels.",
    "Plug in the connection cable before attaching the front of the housing.",
    "Hook the front part of the housing into the marked openings at the top.",
    "Remove the protective film from the display.",
]
PANELS = [(60, 100, 260, 230), (320, 100, 520, 230), (60, 300, 260, 430), (320, 300, 520, 430), (60, 500, 260, 630)]


def _png(shade=200, size=20) -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, size, size), False)
    pix.set_rect(pix.irect, (shade, shade, shade))
    return pix.tobytes("png")


def _step_page(captions=STEPS, panels=PANELS):
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=H)
    for i, r in enumerate(panels):
        page.insert_image(pymupdf.Rect(*r), stream=_png(150 + i * 10))
    for r, c in zip(panels, captions):
        page.insert_textbox(pymupdf.Rect(r[0], r[3] + 6, r[2], r[3] + 60), c, fontsize=9)
    return pdf, page


def _doc(rects, cls=("engineering_drawing", 0.9)):
    doc = DoclingDocument(name="t")
    doc.add_page(page_no=1, size=Size(width=595, height=H))
    for r in rects:
        pic = doc.add_picture(prov=ProvenanceItem(page_no=1, bbox=BoundingBox(
            l=r[0], t=H - r[1], r=r[2], b=H - r[3], coord_origin=CoordOrigin.BOTTOMLEFT), charspan=(0, 0)))
        pic.meta = PictureMeta(classification=PictureClassificationMetaField(predictions=[
            PictureClassificationPrediction(class_name=cls[0], confidence=cls[1], created_by="t")]))
    return doc


# ----------------------------------------------------------------------------
# build_procedure
# ----------------------------------------------------------------------------
def test_steps_come_out_in_row_major_order_with_wrapped_captions_joined():
    _, page = _step_page()
    assert procedure.build_procedure(page, list(PANELS)) == STEPS        # step 3 wraps onto two lines


def test_panel_order_is_independent_of_the_input_order():
    _, page = _step_page()
    assert procedure.build_procedure(page, list(reversed(PANELS))) == STEPS


def test_figure_caption_grids_are_not_procedures():
    _, page = _step_page(captions=[f"Fig. {i} Dimension drawing of the module" for i in range(1, 6)])
    assert procedure.build_procedure(page, list(PANELS)) is None


def test_needs_three_panels_and_captions_for_most_of_them():
    _, page = _step_page()
    assert procedure.build_procedure(page, list(PANELS[:2])) is None
    _, page = _step_page(captions=STEPS[:2] + ["", "", ""])
    assert procedure.build_procedure(page, list(PANELS)) is None


def test_wildly_different_panel_sizes_or_no_text_are_rejected():
    _, page = _step_page()
    odd = [PANELS[0], PANELS[1], (60, 300, 70, 305)]                      # a 10x5 pt speck among panels
    assert procedure.build_procedure(page, odd) is None
    pdf = pymupdf.open()
    empty = pdf.new_page(width=595, height=H)
    assert procedure.build_procedure(empty, list(PANELS)) is None


def test_two_side_by_side_captions_stay_separate_steps():
    # PyMuPDF merges same-baseline captions into one *block*; line-level reading must not.
    _, page = _step_page()
    blocks = [b for b in page.get_text("blocks") if "Reinsert" in b[4]]
    assert "Insert the connecting" in blocks[0][4]                        # the trap this module avoids
    assert procedure.build_procedure(page, list(PANELS))[0] == STEPS[0]


# ----------------------------------------------------------------------------
# cards integration
# ----------------------------------------------------------------------------
def test_process_pictures_emits_one_procedure_card_not_five_captions():
    _, page = _step_page()
    cards_out = cards.process_pictures(_doc(PANELS), page, ["Systevo Room Terminal"], 3)
    assert len(cards_out) == 1
    c = cards_out[0]
    assert c["content_type"] == "procedure" and c["figure_id"] == "proc_p3"
    assert c["text"].startswith("Procedure (5 illustrated steps) | Section: Systevo Room Terminal")
    assert "Step 1: Reinsert the PCB and latch in place." in c["text"]
    assert "Step 5: Remove the protective film from the display." in c["text"]


def test_procedure_detection_can_be_switched_off(monkeypatch):
    import config
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, pdf_figure_procedures=False))
    _, page = _step_page()
    out = cards.process_pictures(_doc(PANELS), page, [], 3)
    assert all(c["content_type"] != "procedure" for c in out)             # panels have no labels -> no cards


def test_technical_diagrams_are_never_taken_for_step_panels():
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=H)
    for i, r in enumerate(PANELS[:3]):
        page.insert_image(pymupdf.Rect(*r), stream=_png(150 + i * 10))
        page.insert_text((r[0] + 10, r[1] + 30), "SEM-IP ID1", fontsize=8)
        page.insert_text((r[0] + 10, r[1] + 50), "DBUS 1", fontsize=8)
        page.insert_text((r[0] + 10, r[1] + 70), "SBU ID1", fontsize=8)
        page.insert_textbox(pymupdf.Rect(r[0], r[3] + 6, r[2], r[3] + 60), STEPS[i], fontsize=9)
    out = cards.process_pictures(_doc(PANELS[:3]), page, [], 1)
    assert [c["content_type"] for c in out] == ["figure"] * 3


def test_format_procedure_and_chunker_tag():
    assert cards.format_procedure(["a b c", "d e f"], "") == "Procedure (2 illustrated steps) | Step 1: a b c | Step 2: d e f"
    from core.chunker import _PROCEDURE_RE
    assert _PROCEDURE_RE.search("x\nProcedure (5 illustrated steps) | Step 1: y")
    assert not _PROCEDURE_RE.search("Procedure for cleaning")


def test_procedure_card_survives_the_router_markdown_glue(monkeypatch):
    from config import settings
    from parsers.pdf_router import PdfPageRouter
    monkeypatch.setattr("parsers.pdf_router.settings", dataclasses.replace(settings, pdf_figure_pipeline="v6"))
    pdf, _ = _step_page()
    out = PdfPageRouter()._v6_cards_md(_doc(PANELS), pdf.tobytes(), 3, "## Installation\n\ntext")
    assert out.startswith("Procedure (5 illustrated steps) | Section: Installation | Step 1: Reinsert")


@pytest.mark.parametrize("n", [3, 4, 6])
def test_other_panel_counts_work(n):
    panels = PANELS[:n] if n <= 5 else PANELS + [(320, 500, 520, 630)]
    caps = (STEPS + ["Fasten the cover with the two screws provided."])[:n]
    _, page = _step_page(captions=caps, panels=panels)
    assert procedure.build_procedure(page, list(panels)) == caps
