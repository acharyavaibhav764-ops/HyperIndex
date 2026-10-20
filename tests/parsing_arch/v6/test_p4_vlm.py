"""v6 phase 4: local VLM connections (Ollama) + OCR fallback, with exact-match validation."""
import dataclasses
import json
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pymupdf
import pytest
from docling_core.types.doc import BoundingBox, CoordOrigin, DoclingDocument, ProvenanceItem, Size
from docling_core.types.doc.document import (
    PictureClassificationMetaField, PictureClassificationPrediction, PictureMeta,
)

from parsers.pdf_v6 import cards, labels, ocr, vlm

H = 842.0
LABELS = [(120, 230, "SEM-IP ID1"), (120, 250, "DBUS 1"), (120, 270, "SBU ID1"), (120, 290, "SCU ID2")]
RECT = (100, 200, 400, 420)


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


def _doc(cls=("engineering_drawing", 0.9)):
    doc = DoclingDocument(name="t")
    doc.add_page(page_no=1, size=Size(width=595, height=H))
    pic = doc.add_picture(prov=ProvenanceItem(page_no=1, bbox=BoundingBox(
        l=RECT[0], t=H - RECT[1], r=RECT[2], b=H - RECT[3], coord_origin=CoordOrigin.BOTTOMLEFT), charspan=(0, 0)))
    if cls:
        pic.meta = PictureMeta(classification=PictureClassificationMetaField(predictions=[
            PictureClassificationPrediction(class_name=cls[0], confidence=cls[1], created_by="t")]))
    return doc


def _settings(monkeypatch, **kw):
    import config
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, **kw))


def _vlm_reply(monkeypatch, payload):
    calls = []

    def fake(png, prompt, model, host, port, timeout, keep_alive="5m"):
        calls.append({"prompt": prompt, "model": model, "png": png[:4], "keep_alive": keep_alive})
        if isinstance(payload, Exception):
            raise payload
        return json.dumps(payload)

    monkeypatch.setattr(vlm, "chat", fake)
    return calls


# ----------------------------------------------------------------------------
# validation: exact tokens inside one label line
# ----------------------------------------------------------------------------
def test_validate_connections_is_exact_and_never_rewrites():
    lines = ["SEM-IP ID1", "SBU ID1", "DBUS 1", "SCU ID2", "SRT & SCB-RU", "4"]
    raw = [
        {"from": "SEM-IP ID1", "to": "SBU ID1", "via": "DBUS 1 / 4-wire"},
        {"from": "SEM-IP ID1", "to": "SBU ID3", "via": "DBUS 1"},        # ID3 not in figure
        {"from": "SEM-IP ID1", "to": "SBU ID2", "via": ""},              # 'SBU' and 'ID2' exist, never together
        {"from": "SEM-IP ID1", "to": "SEM-IP ID1", "via": ""},           # self loop
        {"from": "SRT & SCB-RU", "to": "SCU ID2", "via": "DBUS 2"},     # DBUS 2 not drawn -> via dropped
        {"from": "Server", "to": "SBU ID1", "via": ""},                  # invented label
        {"from": "sem-ip id1", "to": "SBU ID1", "via": "DBUS 1 / 4-wire"},  # duplicate (case)
    ]
    kept = vlm.validate_connections(raw, lines)
    assert [(k["from"], k["to"]) for k in kept] == [("SEM-IP ID1", "SBU ID1"), ("SRT & SCB-RU", "SCU ID2")]
    assert kept[0]["via"] == "DBUS 1 / 4-wire" and kept[1]["via"] == ""


def test_id_pairing_makes_split_labels_validatable():
    _, page = _page(texts=[(120, 230, "SBU"), (150, 222, "ID1"), (120, 330, "SRT"), (400, 330, "ID2")])
    got = labels.extract_labels(page, (100, 200, 520, 400))
    assert vlm.validate_connections(
        [{"from": "SBU ID1", "to": "SRT", "via": ""}, {"from": "SBU ID2", "to": "SRT", "via": ""}], got
    ) == [{"from": "SBU ID1", "to": "SRT", "via": ""}]


def test_parse_vlm_json_variants():
    good = '{"connections":[{"from":"A","to":"B","via":"x"}]}'
    assert vlm.parse_vlm_json("```json\n" + good + "\n```")[0]["from"] == "A"
    assert vlm.parse_vlm_json("noise " + good + " tail")[0]["to"] == "B"
    assert vlm.parse_vlm_json("not json at all") == []
    assert vlm.parse_vlm_json('{"connections": "oops"}') == []
    assert vlm.parse_vlm_json('{"edges":[{"source":"A","target":"B"}]}')[0]["target"] == "B"


def test_prompt_lists_only_figure_labels_and_context():
    p = vlm.build_prompt(["SEM-IP ID1", "DBUS 1"], "5.5 Overview", "Fig 3")
    assert "- SEM-IP ID1" in p and "- DBUS 1" in p and "5.5 Overview" in p and "Fig 3" in p
    assert "never invent a label" in p


# ----------------------------------------------------------------------------
# the Ollama request
# ----------------------------------------------------------------------------
def test_chat_request_shape_against_a_local_fake_server():
    import base64
    seen = {}

    class H_(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            out = json.dumps({"message": {"content": '{"connections": []}'}}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H_)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        reply = vlm.chat(b"\x89PNGdata", "prompt text", "qwen2.5vl:3b", "127.0.0.1", srv.server_port, 5, "2m")
    finally:
        srv.shutdown()
    body = seen["body"]
    assert reply == '{"connections": []}' and seen["path"] == "/api/chat"
    assert body["model"] == "qwen2.5vl:3b" and body["stream"] is False and body["format"] == "json"
    assert body["keep_alive"] == "2m"                       # unload after ingestion (compose uses KEEP_ALIVE=-1)
    assert body["options"]["temperature"] == 0 and body["options"]["num_ctx"] == 4096
    msg = body["messages"][0]
    assert msg["content"] == "prompt text" and base64.b64decode(msg["images"][0]) == b"\x89PNGdata"


# ----------------------------------------------------------------------------
# cards with the VLM (Ollama mocked)
# ----------------------------------------------------------------------------
def test_vlm_keeps_only_validated_edges(monkeypatch):
    _settings(monkeypatch, pdf_vlm_enabled=True, pdf_vlm_keep_alive="3m")
    calls = _vlm_reply(monkeypatch, {"connections": [
        {"from": "SEM-IP ID1", "to": "SBU ID1", "via": "DBUS 1"},
        {"from": "SEM-IP ID1", "to": "SBU ID9", "via": "DBUS 1"},
    ]})
    _, page = _page(texts=LABELS, images=[(*RECT, 180)])
    run = cards.FigureRun()
    [card] = cards.process_pictures(_doc(), page, ["Wiring"], 2, run=run)
    assert "Connections (machine-read, verify against the figure): SEM-IP ID1 -[DBUS 1]-> SBU ID1" in card["text"]
    assert "SBU ID9" not in card["text"] and card["edges"] == 1
    assert calls[0]["png"] == b"\x89PNG" and "- SEM-IP ID1" in calls[0]["prompt"] and calls[0]["keep_alive"] == "3m"
    assert calls[0]["model"] == "qwen2.5vl:3b"
    assert run.vlm_calls == 1 and run.stats["vlm_edges_dropped"] == 1


def test_vlm_is_off_by_default(monkeypatch):
    calls = _vlm_reply(monkeypatch, {"connections": []})
    _, page = _page(texts=LABELS, images=[(*RECT, 180)])
    [card] = cards.process_pictures(_doc(), page, [], 2)
    assert calls == [] and "Connections" not in card["text"]


def test_vlm_errors_and_budget_never_break_cards(monkeypatch):
    _settings(monkeypatch, pdf_vlm_enabled=True)
    _vlm_reply(monkeypatch, RuntimeError("ollama down"))
    _, page = _page(texts=LABELS, images=[(*RECT, 180)])
    run = cards.FigureRun()
    [card] = cards.process_pictures(_doc(), page, [], 2, run=run)
    assert "Labels:" in card["text"] and "Connections" not in card["text"] and run.stats["vlm_error"] == 1
    _settings(monkeypatch, pdf_vlm_enabled=True, pdf_vlm_max_per_doc=0)
    calls = _vlm_reply(monkeypatch, {"connections": []})
    cards.process_pictures(_doc(), page, [], 2, run=cards.FigureRun())
    assert calls == []


def test_vlm_needs_labels_to_validate_against(monkeypatch):
    _settings(monkeypatch, pdf_vlm_enabled=True)
    calls = _vlm_reply(monkeypatch, {"connections": [{"from": "A", "to": "B", "via": ""}]})
    monkeypatch.setattr(ocr, "ocr_labels", lambda png, px_per_pt=1.0: [])
    _, page = _page(images=[(*RECT, 180)])
    assert cards.process_pictures(_doc(), page, [], 2, run=cards.FigureRun()) == []
    assert calls == []


def test_vlm_skips_charts_and_photos(monkeypatch):
    _settings(monkeypatch, pdf_vlm_enabled=True)
    calls = _vlm_reply(monkeypatch, {"connections": []})
    _, page = _page(texts=[(120, 230, "Jan"), (120, 250, "Feb"), (120, 270, "Mar")], images=[(*RECT, 180)])
    [card] = cards.process_pictures(_doc(("bar_chart", 0.9)), page, [], 2, run=cards.FigureRun())
    assert calls == [] and "Labels: Jan, Feb, Mar" in card["text"]       # chart: labels only


def test_ocr_labels_without_vlm_when_figure_ocr_is_on(monkeypatch):
    _settings(monkeypatch, pdf_figure_ocr=True)
    calls = _vlm_reply(monkeypatch, {"connections": []})
    monkeypatch.setattr(ocr, "ocr_labels", lambda png, px_per_pt=1.0: ["120", "115", "46", "SEM+"])
    _, page = _page(images=[(*RECT, 180)])
    [card] = cards.process_pictures(_doc(), page, ["Dimensions"], 5)
    assert card["source"] == "ocr" and card["confidence"] == "medium"
    assert "Labels: 120, 115, 46, SEM+" in card["text"] and "Numbers: 120, 115, 46" in card["text"]
    assert calls == []


def test_ocr_is_off_by_default(monkeypatch):
    monkeypatch.setattr(ocr, "ocr_labels", lambda *a, **k: (_ for _ in ()).throw(AssertionError("OCR must not run")))
    _, page = _page(images=[(*RECT, 180)])
    assert cards.process_pictures(_doc(), page, [], 5) == []


def test_ocr_fallback_feeds_the_vlm(monkeypatch):
    _settings(monkeypatch, pdf_vlm_enabled=True)
    calls = _vlm_reply(monkeypatch, {"connections": [{"from": "SEM-IP ID1", "to": "SBU ID1", "via": ""}]})
    monkeypatch.setattr(ocr, "ocr_labels", lambda png, px_per_pt=1.0: ["SEM-IP ID1", "SBU ID1", "DBUS 1"])
    _, page = _page(images=[(*RECT, 180)])
    [card] = cards.process_pictures(_doc(), page, [], 2, run=cards.FigureRun())
    assert card["source"] == "ocr" and card["edges"] == 1 and len(calls) == 1


# ----------------------------------------------------------------------------
# ocr module
# ----------------------------------------------------------------------------
def test_effective_dpi_caps_the_long_side_and_render_crop_makes_a_png():
    assert ocr.effective_dpi((0, 0, 100, 100), 200) == 200
    assert ocr.effective_dpi((0, 0, 800, 500), 200) == 144           # 1600 px * 72 / 800 pt
    assert ocr.effective_dpi((0, 0, 5000, 100), 200) == ocr.MIN_DPI
    _, page = _page(texts=LABELS)
    png = ocr.render_crop(page, RECT, 100)
    assert png[:4] == b"\x89PNG"
    pix = pymupdf.Pixmap(png)
    assert (pix.width, pix.height) == (pytest.approx(300 * 100 / 72, abs=2), pytest.approx(220 * 100 / 72, abs=2))


def test_spaced_variants():
    assert ocr.spaced_variants(["DBUS2", "ID1", "STIP3", "24VDC", "SEM-IP", "R-ABUS"]) == ["DBUS 2", "STIP 3"]


def _fake_engine(monkeypatch, result):
    monkeypatch.setattr(ocr, "_OCR_ENGINE", lambda png: result)
    monkeypatch.setattr(ocr, "_OCR_FAILED", False)


def _box(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def test_ocr_labels_pair_ids_and_add_spaced_forms_onnxruntime_shape(monkeypatch):
    res = ([[_box(42, 65, 218, 108), "SEM-IP", 0.99], [_box(224, 66, 300, 107), "ID1", 0.99],
            [_box(44, 169, 178, 200), "DBUS2", 0.99], [_box(900, 900, 950, 940), "noise", 0.2]], 0.1)
    _fake_engine(monkeypatch, res)
    got = ocr.ocr_labels(b"png", px_per_pt=2.78)
    assert "SEM-IP ID1" in got and "DBUS 2" in got and "DBUS2" in got and "noise" not in got


def test_ocr_labels_rapidocr_v2_object_shape(monkeypatch):
    res = types.SimpleNamespace(txts=("SRT", "ID2"), scores=(0.9, 0.9), boxes=[_box(0, 0, 40, 20), _box(50, 0, 90, 20)])
    _fake_engine(monkeypatch, res)
    assert "SRT ID2" in ocr.ocr_labels(b"png", px_per_pt=1.0)


def test_ocr_failure_is_sticky_and_returns_empty(monkeypatch):
    def boom(png):
        raise RuntimeError("model missing")
    monkeypatch.setattr(ocr, "_OCR_ENGINE", boom)
    monkeypatch.setattr(ocr, "_OCR_FAILED", False)
    assert ocr.ocr_labels(b"x") == [] and ocr._OCR_FAILED is True
    assert ocr.ocr_labels(b"x") == []


@pytest.mark.slow
def test_real_rapidocr_reads_a_rendered_label():
    pytest.importorskip("rapidocr_onnxruntime")
    ocr._OCR_ENGINE, ocr._OCR_FAILED = None, False
    pdf = pymupdf.open()
    page = pdf.new_page(width=300, height=120)
    page.insert_text((20, 50), "SEM-IP ID1", fontsize=24)
    page.insert_text((20, 95), "DBUS 2   120", fontsize=18)
    got = ocr.ocr_labels(page.get_pixmap(dpi=150).tobytes("png"), px_per_pt=150 / 72)
    assert "SEM-IP ID1" in got and "120" in got and any(x.replace(" ", "") == "DBUS2" for x in got)
