"""v6 phase 5: typed chunks with page / bbox / MinIO image link in metadata."""
import sys
import types
from unittest.mock import MagicMock

import pymupdf
import pytest
from docling_core.types.doc import BoundingBox, CoordOrigin, DoclingDocument, ProvenanceItem, Size
from docling_core.types.doc.document import (
    PictureClassificationMetaField, PictureClassificationPrediction, PictureMeta,
)

from core.chunker import _split_figure_tail
from parsers.pdf_v6 import cards
from parsers.pdf_v6.store import FigureStore

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


def _doc(rects=(RECT,)):
    doc = DoclingDocument(name="t")
    doc.add_page(page_no=1, size=Size(width=595, height=H))
    for r in rects:
        pic = doc.add_picture(prov=ProvenanceItem(page_no=1, bbox=BoundingBox(
            l=r[0], t=H - r[1], r=r[2], b=H - r[3], coord_origin=CoordOrigin.BOTTOMLEFT), charspan=(0, 0)))
        pic.meta = PictureMeta(classification=PictureClassificationMetaField(predictions=[
            PictureClassificationPrediction(class_name="engineering_drawing", confidence=0.9, created_by="t")]))
    return doc


class FakeS3:
    def __init__(self, fail=False):
        self.objects, self.fail = {}, fail

    def put_object(self, Bucket, Key, Body, ContentType):
        if self.fail:
            raise RuntimeError("minio down")
        self.objects[(Bucket, Key)] = (Body, ContentType)


# ----------------------------------------------------------------------------
# store
# ----------------------------------------------------------------------------
def test_store_keys_are_content_derived_and_idempotent():
    s3 = FakeS3()
    store = FigureStore(s3, "honeywell-files", "/figures/")
    url = store.put("abc123", "fig_p4_0", b"PNG1")
    assert url == "s3://honeywell-files/figures/abc123/fig_p4_0.png"
    assert store.put("abc123", "fig_p4_0", b"PNG2") == url             # same key -> overwrite, not duplicate
    assert s3.objects == {("honeywell-files", "figures/abc123/fig_p4_0.png"): (b"PNG2", "image/png")}


def test_store_from_settings_uses_the_uploaders_minio_config(monkeypatch):
    fake_boto = types.SimpleNamespace(client=MagicMock(return_value="client"))
    monkeypatch.setitem(sys.modules, "boto3", fake_boto)
    from config import settings
    store = FigureStore.from_settings(settings)
    kw = fake_boto.client.call_args.kwargs
    assert fake_boto.client.call_args.args == ("s3",)
    assert kw["endpoint_url"] == f"http://{settings.minio_endpoint}" and kw["region_name"] == "us-east-1"
    assert kw["aws_access_key_id"] == settings.minio_access_key
    assert store.client == "client" and store.bucket == settings.minio_bucket and store.prefix == "figures"


# ----------------------------------------------------------------------------
# cards
# ----------------------------------------------------------------------------
def test_figure_card_carries_page_and_bbox_without_a_store():
    _, page = _page(texts=LABELS, images=[(*RECT, 180)])
    [card] = cards.process_pictures(_doc(), page, ["Wiring"], 4)           # page_no is 0-based
    assert card["text"].endswith(" | Page: 5 | BBox: 100,200,400,420")
    assert card["bbox"] == pytest.approx(RECT) and card["image"] == ""


def test_crop_is_uploaded_and_linked_when_a_store_is_configured():
    s3 = FakeS3()
    run = cards.FigureRun()
    run.doc_key, run.store = "deadbeef", FigureStore(s3, "honeywell-files")
    _, page = _page(texts=LABELS, images=[(*RECT, 180)])
    [card] = cards.process_pictures(_doc(), page, [], 4, run=run)
    key = ("honeywell-files", "figures/deadbeef/fig_p4_0.png")
    assert card["image"] == "s3://honeywell-files/figures/deadbeef/fig_p4_0.png"
    assert card["text"].endswith(f" | Page: 5 | BBox: 100,200,400,420 | Image: {card['image']}")
    body, ctype = s3.objects[key]
    assert body[:4] == b"\x89PNG" and ctype == "image/png" and run.stats["figure_stored"] == 1


def test_upload_failure_keeps_the_card_without_an_image_link():
    run = cards.FigureRun()
    run.doc_key, run.store = "deadbeef", FigureStore(FakeS3(fail=True), "b")
    _, page = _page(texts=LABELS, images=[(*RECT, 180)])
    [card] = cards.process_pictures(_doc(), page, [], 4, run=run)
    assert card["image"] == "" and "Image:" not in card["text"] and run.stats["figure_store_failed"] == 1
    assert "Labels: SEM-IP ID1" in card["text"]


def test_procedure_card_gets_a_page_tail():
    panels = [(60, 100, 260, 230), (320, 100, 520, 230), (60, 300, 260, 430)]
    steps = ["Reinsert the PCB and latch in place.", "Insert the connecting cables and mark them.",
             "Plug in the connection cable before attaching the housing."]
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=H)
    for i, r in enumerate(panels):
        page.insert_image(pymupdf.Rect(*r), stream=_png(150 + i * 10))
        page.insert_textbox(pymupdf.Rect(r[0], r[3] + 6, r[2], r[3] + 60), steps[i], fontsize=9)
    [card] = cards.process_pictures(_doc(panels), page, ["Installation"], 6)
    assert card["content_type"] == "procedure"
    assert card["text"].endswith("Step 3: Plug in the connection cable before attaching the housing. | Page: 7")


# ----------------------------------------------------------------------------
# chunker: tail -> metadata
# ----------------------------------------------------------------------------
def test_split_figure_tail_moves_page_bbox_image_into_metadata():
    line = "Figure: (untitled) | Type: engineering drawing | Labels: a, b, c | Page: 5 | BBox: 100,200,400,420 | Image: s3://b/figures/k/fig_p4_0.png"
    text, meta = _split_figure_tail("5.6 Room wiring\n" + line + "\nother text")
    assert text == "5.6 Room wiring\nFigure: (untitled) | Type: engineering drawing | Labels: a, b, c\nother text"
    assert meta == {"figure_page": 5, "figure_bbox": "100,200,400,420", "figure_image": "s3://b/figures/k/fig_p4_0.png"}


def test_split_figure_tail_handles_page_only_and_non_cards():
    text, meta = _split_figure_tail("Procedure (3 illustrated steps) | Step 1: a b c | Page: 2")
    assert text == "Procedure (3 illustrated steps) | Step 1: a b c" and meta == {"figure_page": 2}
    plain = "Normal paragraph | Page: 7"
    assert _split_figure_tail(plain) == (plain, {})                         # only cards are touched


def test_metadata_values_are_chroma_safe_scalars():
    _, meta = _split_figure_tail("Figure: x | Labels: a | Page: 3 | BBox: 1,2,3,4 | Image: s3://b/k.png")
    assert all(isinstance(v, (str, int, float, bool)) for v in meta.values())


# ----------------------------------------------------------------------------
# router wiring
# ----------------------------------------------------------------------------
def test_parse_wires_the_store_and_a_content_key_into_the_run(monkeypatch):
    import hashlib
    import dataclasses as dc
    from config import settings
    import parsers.pdf_router as pr

    monkeypatch.setattr(pr, "settings", dc.replace(
        settings, enable_pdf_page_router=True, pdf_figure_pipeline="v6", pdf_figure_store=True))
    fake = FakeS3()
    monkeypatch.setattr(FigureStore, "from_settings", classmethod(lambda cls, st: cls(fake, "b")))
    pdf = pymupdf.open()
    pdf.new_page(width=595, height=842).insert_textbox(
        pymupdf.Rect(72, 300, 520, 600), "Body paragraph with several sentences. " * 8, fontsize=11)
    data = pdf.tobytes()
    router = pr.PdfPageRouter()
    router._merge_pages = MagicMock(return_value="merged")
    assert router.parse(data, "m.pdf") == "merged"
    assert router._fig_run.doc_key == hashlib.sha1(data).hexdigest()[:16]
    assert router._fig_run.store.bucket == "b"


def test_parse_leaves_the_run_without_a_store_by_default(monkeypatch):
    import dataclasses as dc
    from config import settings
    import parsers.pdf_router as pr

    monkeypatch.setattr(pr, "settings", dc.replace(settings, enable_pdf_page_router=True, pdf_figure_pipeline="v6"))
    pdf = pymupdf.open()
    pdf.new_page(width=595, height=842).insert_textbox(
        pymupdf.Rect(72, 300, 520, 600), "Body paragraph with several sentences. " * 8, fontsize=11)
    router = pr.PdfPageRouter()
    router._merge_pages = MagicMock(return_value="merged")
    router.parse(pdf.tobytes(), "m.pdf")
    assert router._fig_run.store is None and router._fig_run.doc_key == ""
