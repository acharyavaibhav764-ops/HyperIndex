#!/usr/bin/env python3
"""v6 step zero: install the Qwen vision model into Ollama and keep going in the background.

The pull of a ~3 GB model takes a while, so ``start`` spawns a detached worker and returns
immediately; ``status`` shows progress; ``verify`` proves the model can read a labelled image.

  python scripts/qwen_setup.py start    # begin the background pull (resumable, safe to re-run)
  python scripts/qwen_setup.py status   # installed? how far is the pull?
  python scripts/qwen_setup.py verify   # tiny image -> model -> checks the label comes back
  python scripts/qwen_setup.py pull     # same pull, but in the foreground (shows progress)

Ollama runs in Docker (service ``ollama``, port 11434 published), so the default URL is
http://localhost:11434.  Override with ``--ollama`` or the OLLAMA_URL env var; pick another
model with ``--model`` or PDF_VLM_MODEL.  Standard library only (``verify`` also needs PyMuPDF).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

DEFAULT_MODEL = os.getenv("PDF_VLM_MODEL", "qwen2.5vl:3b")
DEFAULT_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
DEFAULT_LOG = os.getenv("QWEN_PULL_LOG", "qwen_pull.log")
FRESH_SECONDS = 45  # a log touched within this window means a worker is still pulling


# ----------------------------------------------------------------------------
# Ollama helpers
# ----------------------------------------------------------------------------
def _norm_model(name: str) -> str:
    return name if ":" in name else f"{name}:latest"


def _get_json(url: str, timeout: float = 5.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - local service
        return json.loads(resp.read().decode("utf-8"))


def list_models(base: str) -> set[str]:
    """Names of the models Ollama has installed (empty set when it is unreachable)."""
    try:
        data = _get_json(base.rstrip("/") + "/api/tags")
    except (urllib.error.URLError, OSError, ValueError):
        return set()
    return {_norm_model(m.get("name", "")) for m in data.get("models", []) if m.get("name")}


def model_installed(base: str, model: str) -> bool:
    return _norm_model(model) in list_models(base)


def ollama_reachable(base: str) -> bool:
    try:
        _get_json(base.rstrip("/") + "/api/tags")
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


# ----------------------------------------------------------------------------
# background pull
# ----------------------------------------------------------------------------
def _log(path: str, **fields) -> None:
    fields["t"] = round(time.time(), 1)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")


def pull_worker(base: str, model: str, log_path: str, timeout: float = 3600.0) -> int:
    """Stream ``/api/pull`` into ``log_path`` (one JSON object per line).  0 = success."""
    body = json.dumps({"model": model, "name": model, "stream": True}).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/api/pull", data=body, headers={"Content-Type": "application/json"}
    )
    _log(log_path, status="starting", model=model)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - local service
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("error"):
                    _log(log_path, error=str(msg["error"]))
                    return 1
                _log(log_path, **{k: msg[k] for k in ("status", "digest", "total", "completed") if k in msg})
                if msg.get("status") == "success":
                    return 0
    except (urllib.error.URLError, OSError) as exc:
        _log(log_path, error=f"{type(exc).__name__}: {exc}")
        return 1
    _log(log_path, error="stream ended before 'success'")
    return 1


def read_progress(log_path: str) -> dict:
    """Summarise the log: state = none|running|stalled|done|error, percent of the current layer."""
    if not os.path.exists(log_path):
        return {"state": "none"}
    last, layer = {}, {}
    with open(log_path, encoding="utf-8") as fh:
        for line in fh:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            last = msg
            if msg.get("total"):
                layer = msg
    if last.get("error"):
        return {"state": "error", "detail": last["error"]}
    if last.get("status") == "success":
        return {"state": "done"}
    pct = None
    if layer.get("total"):
        pct = round(100.0 * layer.get("completed", 0) / layer["total"], 1)
    age = time.time() - os.path.getmtime(log_path)
    return {"state": "running" if age <= FRESH_SECONDS else "stalled",
            "status": last.get("status", ""), "percent": pct, "idle_seconds": round(age)}


def start_background(base: str, model: str, log_path: str) -> str:
    """Spawn a detached pull worker.  Returns 'installed' | 'running' | 'started'."""
    if model_installed(base, model):
        return "installed"
    if read_progress(log_path).get("state") == "running":
        return "running"
    cmd = [sys.executable, os.path.abspath(__file__), "worker",
           "--ollama", base, "--model", model, "--log", log_path]
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":  # survive the terminal being closed
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)  # noqa: S603
    return "started"


# ----------------------------------------------------------------------------
# verify
# ----------------------------------------------------------------------------
def label_image_png(text: str = "SEM-IP ID1") -> bytes:
    """A small PNG with ``text`` rendered on it (needs PyMuPDF)."""
    try:
        import pymupdf
    except ImportError:  # PyMuPDF < 1.24.3
        import fitz as pymupdf  # type: ignore
    pdf = pymupdf.open()
    page = pdf.new_page(width=260, height=90)
    page.insert_text((20, 55), text, fontsize=26)
    return page.get_pixmap(dpi=110).tobytes("png")


def verify(base: str, model: str, expect: str = "ID1", timeout: float = 600.0) -> tuple[bool, str, float]:
    """Ask the model to read a label from an image.  (ok, reply, seconds)."""
    body = {
        "model": model, "stream": False, "keep_alive": "5m",
        "options": {"temperature": 0, "num_predict": 40, "num_ctx": 2048},
        "messages": [{"role": "user",
                      "content": "Read the text in this image. Reply with the text only.",
                      "images": [base64.b64encode(label_image_png()).decode("ascii")]}],
    }
    req = urllib.request.Request(
        base.rstrip("/") + "/api/chat", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - local service
            reply = str(json.loads(resp.read().decode("utf-8")).get("message", {}).get("content", ""))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, f"{type(exc).__name__}: {exc}", time.time() - t0
    return expect.lower() in reply.lower(), reply.strip(), time.time() - t0


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["start", "status", "verify", "pull", "worker"])
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--ollama", default=DEFAULT_URL)
    ap.add_argument("--log", default=DEFAULT_LOG)
    a = ap.parse_args(argv)

    if a.cmd in ("start", "pull", "verify") and not ollama_reachable(a.ollama):
        print(f"Ollama is not reachable at {a.ollama}. Start it first: docker compose up -d ollama")
        return 2
    if a.cmd == "start":
        res = start_background(a.ollama, a.model, a.log)
        print({"installed": f"{a.model} is already installed.",
               "running": f"A pull of {a.model} is already running; see: status",
               "started": f"Pulling {a.model} in the background (log: {a.log}). Check with: status"}[res])
        return 0
    if a.cmd in ("pull", "worker"):
        rc = pull_worker(a.ollama, a.model, a.log)
        if a.cmd == "pull":
            print("pull finished" if rc == 0 else f"pull failed; see {a.log}")
        return rc
    if a.cmd == "status":
        prog = read_progress(a.log)
        print(f"ollama reachable : {ollama_reachable(a.ollama)}")
        print(f"{a.model} installed: {model_installed(a.ollama, a.model)}")
        print(f"pull             : {prog}")
        return 0
    ok, reply, secs = verify(a.ollama, a.model)
    print(f"{'OK' if ok else 'FAILED'}: {a.model} answered in {secs:.1f}s -> {reply!r}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
