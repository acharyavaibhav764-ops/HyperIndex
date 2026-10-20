"""v6 phase 0: Qwen install helper (scripts/qwen_setup.py) against a fake Ollama server."""
import importlib.util
import json
import pathlib
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "qwen_setup.py"


@pytest.fixture(scope="module")
def qs():
    spec = importlib.util.spec_from_file_location("qwen_setup", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeOllama:
    """Tiny Ollama stand-in: /api/tags, streaming /api/pull, /api/chat."""

    def __init__(self, models=(), pull_lines=None, chat_reply="SEM-IP ID1"):
        self.models, self.chat_reply, self.chat_bodies, self.pull_bodies = list(models), chat_reply, [], []
        self.pull_lines = pull_lines if pull_lines is not None else [
            {"status": "pulling manifest"},
            {"status": "pulling abc", "digest": "sha256:abc", "total": 1000, "completed": 250},
            {"status": "pulling abc", "digest": "sha256:abc", "total": 1000, "completed": 1000},
            {"status": "success"},
        ]
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, payload: bytes):
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                self._send(json.dumps({"models": [{"name": m} for m in outer.models]}).encode())

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/api/pull":
                    outer.pull_bodies.append(body)
                    self._send(("\n".join(json.dumps(l) for l in outer.pull_lines) + "\n").encode())
                else:
                    outer.chat_bodies.append(body)
                    self._send(json.dumps({"message": {"content": outer.chat_reply}}).encode())

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}"

    def close(self):
        self.srv.shutdown()


@pytest.fixture
def fake():
    made = []

    def make(**kw):
        f = FakeOllama(**kw)
        made.append(f)
        return f

    yield make
    for f in made:
        f.close()


def test_model_installed_matches_latest_tag(qs, fake):
    f = fake(models=["qwen2.5vl:3b", "llama3.2:latest"])
    assert qs.model_installed(f.url, "qwen2.5vl:3b")
    assert qs.model_installed(f.url, "llama3.2")          # bare name == :latest
    assert not qs.model_installed(f.url, "qwen3-vl:4b")


def test_unreachable_ollama_is_reported_not_raised(qs):
    assert qs.list_models("http://127.0.0.1:9") == set()
    assert qs.ollama_reachable("http://127.0.0.1:9") is False


def test_pull_worker_logs_progress_and_finishes(qs, fake, tmp_path):
    f = fake()
    log = str(tmp_path / "pull.log")
    assert qs.pull_worker(f.url, "qwen2.5vl:3b", log) == 0
    assert f.pull_bodies[0]["model"] == "qwen2.5vl:3b" and f.pull_bodies[0]["stream"] is True
    prog = qs.read_progress(log)
    assert prog == {"state": "done"}
    lines = [json.loads(l) for l in open(log, encoding="utf-8")]
    assert lines[0]["status"] == "starting" and any(l.get("completed") == 250 for l in lines)


def test_read_progress_running_percent_and_stalled(qs, tmp_path):
    log = tmp_path / "p.log"
    log.write_text(json.dumps({"status": "pulling abc", "total": 2000, "completed": 500}) + "\n")
    p = qs.read_progress(str(log))
    assert p["state"] == "running" and p["percent"] == 25.0
    old = time.time() - 600
    import os
    os.utime(log, (old, old))
    assert qs.read_progress(str(log))["state"] == "stalled"
    assert qs.read_progress(str(tmp_path / "missing.log")) == {"state": "none"}


def test_pull_worker_reports_ollama_errors(qs, fake, tmp_path):
    f = fake(pull_lines=[{"status": "pulling manifest"}, {"error": "pull model manifest: file does not exist"}])
    log = str(tmp_path / "pull.log")
    assert qs.pull_worker(f.url, "nope:1b", log) == 1
    assert qs.read_progress(log) == {"state": "error", "detail": "pull model manifest: file does not exist"}


def test_pull_worker_connection_failure_is_logged(qs, tmp_path):
    log = str(tmp_path / "pull.log")
    assert qs.pull_worker("http://127.0.0.1:9", "m", log, timeout=2) == 1
    assert qs.read_progress(log)["state"] == "error"


def test_start_background_spawns_detached_worker_once(qs, fake, tmp_path, monkeypatch):
    f = fake()
    spawned = []
    monkeypatch.setattr(qs.subprocess, "Popen", lambda cmd, **kw: spawned.append((cmd, kw)))
    log = str(tmp_path / "pull.log")
    assert qs.start_background(f.url, "qwen2.5vl:3b", log) == "started"
    cmd, kw = spawned[0]
    assert cmd[1].endswith("qwen_setup.py") and cmd[2] == "worker" and "--model" in cmd and "qwen2.5vl:3b" in cmd
    assert kw.get("start_new_session") or kw.get("creationflags")       # detached on posix / windows
    # a fresh, unfinished log means a worker is alive -> no second spawn
    pathlib.Path(log).write_text(json.dumps({"status": "pulling abc", "total": 10, "completed": 1}) + "\n")
    assert qs.start_background(f.url, "qwen2.5vl:3b", log) == "running"
    assert len(spawned) == 1


def test_start_background_skips_when_already_installed(qs, fake, tmp_path, monkeypatch):
    f = fake(models=["qwen2.5vl:3b"])
    monkeypatch.setattr(qs.subprocess, "Popen", lambda *a, **k: pytest.fail("must not spawn"))
    assert qs.start_background(f.url, "qwen2.5vl:3b", str(tmp_path / "l.log")) == "installed"


def test_verify_checks_the_label_comes_back(qs, fake):
    f = fake(chat_reply="The text reads SEM-IP ID1.")
    ok, reply, secs = qs.verify(f.url, "qwen2.5vl:3b")
    assert ok and "ID1" in reply and secs >= 0
    body = f.chat_bodies[0]
    assert body["model"] == "qwen2.5vl:3b" and body["keep_alive"] == "5m" and body["options"]["temperature"] == 0
    assert body["messages"][0]["images"][0]                         # a real PNG was sent
    bad = fake(chat_reply="HOME THEATRE SYSTEM")
    assert qs.verify(bad.url, "qwen2.5vl:3b")[0] is False


def test_cli_status_and_unreachable(qs, fake, tmp_path, capsys):
    f = fake(models=["qwen2.5vl:3b"])
    assert qs.main(["status", "--ollama", f.url, "--log", str(tmp_path / "x.log")]) == 0
    out = capsys.readouterr().out
    assert "installed: True" in out and "reachable : True" in out
    assert qs.main(["start", "--ollama", "http://127.0.0.1:9"]) == 2
    assert "docker compose up -d ollama" in capsys.readouterr().out
