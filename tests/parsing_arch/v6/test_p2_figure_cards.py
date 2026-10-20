"""v6 phase 2: figure foundation (geometry, exact labels, skip gate, Figure cards, router glue).

Real PyMuPDF pages + docling-core documents; no Docling models, no VLM.
"""
import dataclasses

import pymupdf
import pytest
from docling_core.types.doc import BoundingBox, CoordOrigin, DoclingDocument, ProvenanceItem, Size, TableData
from docling_core.types.doc.document import (
    PictureClassificationMetaField, PictureClassificationPrediction, PictureMeta,
)

from parsers.pdf_v6 import cards, gate, geometry, labels, text

H = 842.0
LABELS = [(120, 230, "SEM-IP ID1"), (120, 250, "DBUS 1"), (120, 270, "SBU ID1"), (120, 290, "SCU ID2")]
RECT = (100, 200, 400, 420)


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def _png(shade=200, size=20) -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, size, size), False)
    pix.set_rect(pix.irect, (shade, shade, shade))
    return pix.tobytes("png")


def _page(texts=(), images=()):
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=H)
    for x, y, s in texts:
        page.insert_text((x, y), s, fontsize=8)
    for im in images:
        page.insert_image(pymupdf.Rect(*im[:4]), stream=_png(im[4] if len(im) > 4 else 200))
    return pdf, page


def _bl(rect):
    x0, y0, x1, y1 = rect
    return ProvenanceItem(
        page_no=1,
        bbox=BoundingBox(l=x0, t=H - y0, r=x1, b=H - y1, coord_origin=CoordOrigin.BOTTOMLEFT),
        charspan=(0, 0),
    )


def _doc(rects, classes=None):
    doc = DoclingDocument(name="t")
    doc.add_page(page_no=1, size=Size(width=595, height=H))
    pics = []
    for i, r in enumerate(rects):
        pic = doc.add_picture(prov=_bl(r))
        cls = (classes or {}).get(i)
        if cls:
            pic.meta = PictureMeta(classification=PictureClassificationMetaField(predictions=[
                PictureClassificationPrediction(class_name=cls[0], confidence=cls[1], created_by="t")]))
        pics.append(pic)
    return doc, pics


def _settings(monkeypatch, **kw):
    import config
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, **kw))


# ----------------------------------------------------------------------------
# geometry
# ----------------------------------------------------------------------------
def test_item_bbox_converts_bottom_left_to_top_left():
    _, page = _page()
    doc, [pic] = _doc([(100, 200, 300, 400)])
    assert geometry.item_bbox(pic, doc, page) == pytest.approx((100, 200, 300, 400))


def test_item_bbox_none_without_prov_and_class_info_reads_meta():
    _, page = _page()
    doc, [pic] = _doc([RECT], classes={0: ("flow_chart", 0.8)})
    assert geometry.class_info(pic) == ("flow_chart", 0.8)
    pic.prov = []
    assert geometry.item_bbox(pic, doc, page) is None
    doc2, [pic2] = _doc([RECT])
    assert geometry.class_info(pic2) == ("", 0.0)


def test_inside_and_iou():
    assert geometry.inside((10, 10, 20, 20), (0, 0, 30, 30))
    assert not geometry.inside((10, 10, 40, 20), (0, 0, 30, 30))
    assert geometry.iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert geometry.iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0


# ----------------------------------------------------------------------------
# gate
# ----------------------------------------------------------------------------
def test_gate_geometry_and_class_rules():
    assert gate.geometry_skip((0, 0, 30, 30)) == "skip_tiny"
    assert gate.geometry_skip((0, 0, 500, 50)) == "skip_sliver"
    assert gate.geometry_skip((0, 0, 300, 200)) == ""
    assert gate.effective_class("logo", 0.3) == "" and gate.effective_class("logo", 0.9) == "logo"
    assert gate.class_skip("photograph", False, 0) == "skip_class_photograph"
    assert gate.class_skip("photograph", True, 0) == ""            # technical text rescues it
    assert gate.class_skip("photograph", False, 5) == ""           # annotated photo kept
    for cls in ("", "other", "screenshot_from_manual", "table", "line_chart", "engineering_drawing"):
        assert gate.class_skip(cls, False, 0) == "", cls           # unlisted classes are read


# ----------------------------------------------------------------------------
# labels
# ----------------------------------------------------------------------------
def test_extract_labels_keeps_lines_whole_and_ignores_outside_text():
    _, page = _page(texts=LABELS + [(120, 310, "DBUS 1"), (400, 230, "outside text"), (120, 600, "below")])
    got = labels.extract_labels(page, RECT)
    assert "SEM-IP ID1" in got and "DBUS 1" in got
    assert got.count("DBUS 1") == 1                                 # de-duplicated
    assert not any("outside" in x or "below" in x for x in got)


def test_id_labels_are_paired_with_the_nearest_device_label():
    _, page = _page(texts=[(120, 230, "SBU"), (150, 222, "ID1"), (120, 330, "SRT"), (400, 330, "ID2")])
    got = labels.extract_labels(page, (100, 200, 520, 400))
    assert "SBU ID1" in got and "SRT ID2" not in got                # ID2 is 280 pt from SRT


def test_is_technical_tokens():
    assert labels.is_technical(["SEM-IP ID1"]) and labels.is_technical(["[7]"])
    assert not labels.is_technical(["CH-102", "4:19 PM", "Thursday January 24, 2021", "Honeywell"])
    assert labels.is_technical(["XYZ-9"], r"XYZ-\d")                # custom regex


# ----------------------------------------------------------------------------
# text helpers
# ----------------------------------------------------------------------------
def test_clean_caption_drops_generic_and_looping_text():
    assert text.clean_caption("In this image there is a diagram.") == ""
    loop = "there is a cable on the top of the cable cover, " * 5
    assert text.clean_caption(loop) == ""
    assert text.clean_caption("  Fig. 2   Room wiring  ") == "Fig. 2 Room wiring"


def test_last_heading_and_classifier_label_strip():
    assert text.last_heading("intro\n\n## 5.5 System overview\n\ntext\n### 5.5.1 Sub\n") == "5.5.1 Sub"
    assert text.last_heading("no headings") == "" and text.last_heading(None) == ""
    out = text.strip_classifier_labels("text\n\nScreenshot from manual\n\nTable\n\nOther\n\nmore")
    assert "Screenshot from manual" not in out and "\nTable\n" not in out and "Other" in out


# ----------------------------------------------------------------------------
# cards
# ----------------------------------------------------------------------------
def test_diagram_card_uses_text_layer_labels():
    _, page = _page(texts=LABELS, images=[(*RECT, 180)])
    doc, _ = _doc([RECT], classes={0: ("engineering_drawing", 0.93)})
    [card] = cards.process_pictures(doc, page, ["5.6 Room wiring"], 4)
    assert card["content_type"] == "figure" and card["confidence"] == "high" and card["source"] == "text_layer"
    assert card["figure_id"] == "fig_p4_0"
    assert card["text"].startswith("Figure: (untitled) | Type: engineering drawing | Section: 5.6 Room wiring | Labels: ")
    assert "SEM-IP ID1" in card["text"] and "SCU ID2" in card["text"] and card["text"].endswith("| Numbers: 1")


def test_product_photo_without_text_gets_no_card_and_is_counted():
    _, page = _page(images=[(*RECT, 180)])
    doc, _ = _doc([RECT], classes={0: ("photograph", 0.95)})
    run = cards.FigureRun()
    assert cards.process_pictures(doc, page, [], 5, run=run) == []
    assert run.stats == {"skip_class_photograph": 1}


def test_photo_class_is_rescued_when_technical_text_present():
    _, page = _page(texts=LABELS, images=[(*RECT, 180)])
    doc, _ = _doc([RECT], classes={0: ("photograph", 0.9)})
    assert len(cards.process_pictures(doc, page, [], 5)) == 1


def test_low_confidence_unknown_and_unlisted_classes_are_read_not_dropped():
    _, page = _page(texts=LABELS, images=[(*RECT, 180)])
    for cls in [("logo", 0.30), None, ("other", 0.9), ("screenshot_from_manual", 0.9),
                ("table", 0.9), ("line_chart", 0.9)]:
        doc, _ = _doc([RECT], classes={0: cls} if cls else None)
        assert len(cards.process_pictures(doc, page, [], 5)) == 1, cls


def test_tiny_sliver_and_raster_without_text_are_skipped():
    rects = [(100, 100, 130, 130), (50, 300, 550, 350), (100, 400, 400, 600)]   # tiny, sliver, plain raster
    _, page = _page(images=rects)
    doc, _ = _doc(rects)
    run = cards.FigureRun()
    assert cards.process_pictures(doc, page, [], 1, run=run) == []
    assert run.stats == {"skip_tiny": 1, "skip_sliver": 1, "skip_no_text": 1}


def test_picture_inside_table_is_skipped():
    _, page = _page(texts=LABELS, images=[(*RECT, 180)])
    doc, _ = _doc([RECT])
    doc.add_table(data=TableData(num_rows=0, num_cols=0), prov=_bl((80, 180, 420, 440)))
    assert cards.process_pictures(doc, page, [], 5) == []


def test_repeated_image_across_pages_is_skipped():
    pdf = pymupdf.open()
    png = _png(77)
    for _ in range(3):
        p = pdf.new_page(width=595, height=H)
        p.insert_image(pymupdf.Rect(*RECT), stream=png)
        for x, y, s in LABELS[:3]:
            p.insert_text((x, y), s, fontsize=8)
    run = cards.FigureRun.from_pdf(pdf, min_pages=3)
    assert len(run.repeated) == 1
    doc, _ = _doc([RECT], classes={0: ("engineering_drawing", 0.9)})
    assert cards.process_pictures(doc, pdf[0], [], 0, run=run) == []
    assert run.stats == {"skip_repeated": 1}
    assert cards.FigureRun.from_pdf(pdf, min_pages=4).repeated == set()


def test_custom_tech_regex_setting_is_honoured(monkeypatch):
    _settings(monkeypatch, pdf_figure_tech_regex=r"ZZTOP\d")
    _, page = _page(texts=[(120, 230, "ZZTOP1"), (120, 250, "ZZTOP2"), (120, 270, "ZZTOP3")], images=[(*RECT, 180)])
    doc, _ = _doc([RECT], classes={0: ("photograph", 0.9)})
    assert len(cards.process_pictures(doc, page, [], 5)) == 1       # rescued by the custom regex


def test_format_card_with_and_without_connections():
    base = cards.format_card("", "flow_chart", "5.5 Overview", ["Server", "Switch", "4"])
    assert base == "Figure: (untitled) | Type: flow chart | Section: 5.5 Overview | Labels: Server, Switch, 4 | Numbers: 4"
    full = cards.format_card("Fig 3", "", "", ["A", "B"], [{"from": "A", "to": "B", "via": "DBUS 1"},
                                                          {"from": "B", "to": "A", "via": ""}])
    assert full == ("Figure: Fig 3 | Labels: A, B | Connections (machine-read, verify against the figure): "
                    "A -[DBUS 1]-> B; B -> A")


# ----------------------------------------------------------------------------
# router glue (PDF_FIGURE_PIPELINE)
# ----------------------------------------------------------------------------
def _router_settings(monkeypatch, **kw):
    from config import settings
    monkeypatch.setattr("parsers.pdf_router.settings", dataclasses.replace(settings, **kw))


def test_default_pipeline_is_v5_so_nothing_changes_until_you_opt_in():
    from config import settings
    assert settings.pdf_figure_pipeline == "v5"


def test_v6_figure_page_and_docling_page_append_cards_end_to_end(monkeypatch):
    from unittest.mock import MagicMock
    from parsers.pdf_router import PdfPageRouter

    _router_settings(monkeypatch, pdf_figure_pipeline="v6")
    pdf, page = _page(texts=LABELS, images=[(*RECT, 180)])
    doc, _ = _doc([RECT], classes={0: ("screenshot_from_manual", 0.9)})
    doc.add_heading("5.6 Room wiring", level=1)
    data = pdf.tobytes()

    router = PdfPageRouter()
    conv = MagicMock()
    conv.convert.return_value.document = doc
    router._fig_for = MagicMock(return_value=conv)
    router._vlm_for = MagicMock(side_effect=AssertionError("SmolVLM must not run on v6"))
    md = router._smolvlm_page(data, "m.pdf", 4, False)               # image route delegates to v6
    assert "Screenshot from manual" not in md                        # classifier label no longer leaks
    assert "Figure: (untitled) | Type: screenshot from manual | Section: 5.6 Room wiring | Labels: " in md
    assert "[Figure description]" not in md

    router._docling_full = MagicMock(return_value=doc)
    md2 = router._docling_page(data, "m.pdf", 4, False)              # table route builds cards too
    assert "Figure: (untitled)" in md2 and "Labels: " in md2
    assert router._picture_descriptions_only(data, "m.pdf", 4, False) == ""


def test_v6_cards_use_the_running_heading_hint_and_respect_off(monkeypatch):
    from parsers.pdf_router import PdfPageRouter

    _router_settings(monkeypatch, pdf_figure_pipeline="v6")
    pdf, _ = _page(texts=LABELS, images=[(*RECT, 180)])
    doc, _ = _doc([RECT], classes={0: ("engineering_drawing", 0.9)})
    router = PdfPageRouter()
    router._heading_hint = "5.5 System overview"
    out = router._v6_cards_md(doc, pdf.tobytes(), 2, "page text without any heading")
    assert "Section: 5.5 System overview" in out
    _router_settings(monkeypatch, pdf_figure_pipeline="v6", pdf_figure_mode="off")
    assert router._v6_cards_md(doc, pdf.tobytes(), 2, "x") == ""


def test_v6_figure_page_falls_back_to_text_when_docling_fails(monkeypatch):
    from unittest.mock import MagicMock
    from parsers.pdf_router import PdfPageRouter

    _router_settings(monkeypatch, pdf_figure_pipeline="v6")
    pdf = pymupdf.open()
    pdf.new_page(width=595, height=842).insert_textbox(
        pymupdf.Rect(72, 300, 520, 600), "Plain text survives. " + "This is a body paragraph. " * 8, fontsize=11)
    router = PdfPageRouter()
    router._fig_for = MagicMock(side_effect=RuntimeError("boom"))
    assert "Plain text survives" in router._v6_figure_page(pdf.tobytes(), "m.pdf", 0, False)


def test_v5_pipeline_still_uses_the_smolvlm_path(monkeypatch):
    from unittest.mock import MagicMock
    from parsers.pdf_router import PdfPageRouter

    _router_settings(monkeypatch, pdf_figure_pipeline="v5")
    router = PdfPageRouter()
    router._v6_figure_page = MagicMock(side_effect=AssertionError("v6 must not run on v5"))
    router._vlm_for = MagicMock(side_effect=RuntimeError("legacy path reached"))
    pdf, _ = _page(texts=LABELS)
    router._smolvlm_page(pdf.tobytes(), "a.pdf", 0, True)            # legacy path swallows into its fallback
    router._vlm_for.assert_called_once()


def test_v6_markdown_has_no_classifier_label():
    from parsers.pdf_router import PdfPageRouter
    doc, _ = _doc([RECT], classes={0: ("screenshot_from_manual", 0.9)})
    assert "Screenshot from manual" not in PdfPageRouter._v6_markdown(doc)


def test_chunker_tags_figure_cards():
    from core.chunker import _FIGURE_CARD_RE
    assert _FIGURE_CARD_RE.search("pre\nFigure: (untitled) | Type: engineering drawing | Labels: a")
    assert not _FIGURE_CARD_RE.search("Figure 3 shows the unit")
