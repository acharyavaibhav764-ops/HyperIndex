"""v6 phase 6: the A/B harness (scripts/figure_eval.py) against a fake Ollama and a real PDF."""
import importlib.util
import json
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pymupdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def ev():
    spec = importlib.util.spec_from_file_location("figure_eval", ROOT / "scripts" / "figure_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_scoring_helpers(ev):
    assert ev.score_edges([("SEM-IP ID1", "SBU ID1"), ("A", "B")], [("sbu id1", "sem-ip id1"), ("C", "D")]) == (0.5, 0.5)
    assert ev.score_edges([], []) == (0.0, 0.0)
    assert ev.label_recall(["SEM-IP ID1"], ["sem-ip id1", "DBUS 1"]) == 0.5
    assert ev.label_recall([], []) == 1.0


def test_gold_template_is_valid_json_with_the_fields_run_needs():
    gold = json.loads((ROOT / "scripts" / "gold_figures.template.json").read_text(encoding="utf-8"))
    assert len(gold) >= 3
    for g in gold:
        assert {"id", "page", "bbox", "section", "labels", "edges"} <= set(g) and len(g["bbox"]) == 4


def _fixture_pdf(tmp_path):
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=842)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20), False)
    pix.set_rect(pix.irect, (190, 190, 190))
    page.insert_image(pymupdf.Rect(100, 200, 400, 420), stream=pix.tobytes("png"))
    for y, t in [(230, "SEM-IP ID1"), (250, "DBUS 1"), (270, "SBU ID1")]:
        page.insert_text((120, y), t, fontsize=8)
    path = tmp_path / "m.pdf"
    pdf.save(str(path))
    return path


def test_list_reports_figure_boxes_and_label_counts(ev, tmp_path, capsys):
    ev.main(["list", "--pdf", str(_fixture_pdf(tmp_path))])
    out = capsys.readouterr().out
    assert "p  1 image  bbox=[100,200,400,420] labels=3 technical=True" in out


def test_run_scores_grounded_and_blind_with_validation(ev, tmp_path, capsys):
    bodies = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            bodies.append(body)
            grounded = "- SEM-IP ID1" in body["messages"][0]["content"]
            conns = ([{"from": "SEM-IP ID1", "to": "SBU ID1", "via": "DBUS 1"}] if grounded
                     else [{"from": "Server", "to": "Switch", "via": ""}])        # blind = hallucinated
            out = json.dumps({"message": {"content": json.dumps({"connections": conns})}}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    gold = tmp_path / "gold.json"
    gold.write_text(json.dumps([{"id": "fig1", "page": 1, "bbox": [100, 200, 400, 420], "section": "5.6",
                                 "labels": ["SEM-IP ID1", "DBUS 1", "SBU ID1", "SCU ID2"],
                                 "edges": [["SEM-IP ID1", "SBU ID1"], ["SBU ID1", "SCU ID2"]]}]))
    try:
        ev.main(["run", "--pdf", str(_fixture_pdf(tmp_path)), "--gold", str(gold),
                 "--models", "m1", "--ollama", f"http://127.0.0.1:{srv.server_port}", "--dpi", "100"])
    finally:
        srv.shutdown()
    rows = [l.split(",") for l in capsys.readouterr().out.strip().splitlines()[1:]]
    grounded, blind = rows
    assert grounded[:3] == ["fig1", "m1", "grounded"] and grounded[3] == "0.75"        # 3 of 4 gold labels on the page
    assert grounded[4:8] == ["1", "1", "1.00", "0.50"]                                  # 1 proposed, 1 kept, P=1, R=.5
    assert blind[2] == "blind" and blind[4:8] == ["1", "0", "0.00", "0.00"]             # hallucination rejected
    assert all(b["keep_alive"] == "2m" for b in bodies)
