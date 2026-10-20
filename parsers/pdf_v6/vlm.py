"""Local VLM (Ollama) reads connections; every connection must be provable from the figure's labels.

The VLM never writes prose for the index.  It returns JSON connections, and a connection is kept
only if both endpoints (and the bus name) are contiguous token runs inside ONE label line of the
figure.  Exact match, no fuzzy matching: SBU ID1 / ID2 / ID3 and DBUS 1 / 2 differ by one
character, and 'SBU' + 'ID2' taken from two different labels must not combine into a device
that is not drawn.  Endpoints are kept as written, never rewritten to a neighbour.
"""
from __future__ import annotations

import base64
import json
import re
import urllib.request

from .labels import MAX_LABEL_LINES
from .text import norm, tokens


def build_prompt(labels: list[str], heading: str, caption: str) -> str:
    lines = "\n".join(f"- {label}" for label in labels[:MAX_LABEL_LINES])
    return (
        "You are reading one technical figure (wiring / system diagram) from a product manual.\n"
        f"Section: {heading or 'unknown'}\n"
        f"Caption: {caption or 'none'}\n"
        "These are the ONLY text labels that exist in the figure:\n"
        f"{lines}\n\n"
        "List the drawn connections between labelled items. Reply with JSON only:\n"
        '{"connections":[{"from":"<label>","to":"<label>","via":"<bus name or wire count>"}]}\n'
        "Rules: copy labels exactly as written above; one entry per drawn line or arrow between two "
        "labelled items; never invent a label; if a link is unclear leave it out; "
        'if nothing is readable reply {"connections":[]}.'
    )


def chat(png: bytes, prompt: str, model: str, host: str, port, timeout: int, keep_alive: str = "5m") -> str:
    """One image + prompt to Ollama ``/api/chat`` (JSON mode, temperature 0).

    ``keep_alive`` matters: the Ollama service runs with OLLAMA_KEEP_ALIVE=-1 (models stay loaded
    forever), so without a per-request value the vision model would stay resident next to the
    answer model after ingestion.
    """
    base = host if "://" in host else f"http://{host}:{port}"
    body = {
        "model": model,
        "stream": False,
        "format": "json",
        "keep_alive": keep_alive,
        "options": {"temperature": 0, "num_predict": 700, "num_ctx": 4096},
        "messages": [{"role": "user", "content": prompt,
                      "images": [base64.b64encode(png).decode("ascii")]}],
    }
    req = urllib.request.Request(
        base.rstrip("/") + "/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - local service
        data = json.loads(resp.read().decode("utf-8"))
    return str(data.get("message", {}).get("content", ""))


def parse_vlm_json(text: str) -> list[dict]:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I).strip()
    obj = None
    try:
        obj = json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                obj = json.loads(m.group(0))
            except Exception:
                obj = None
    if isinstance(obj, dict):
        conns = obj.get("connections", obj.get("edges", []))
    elif isinstance(obj, list):
        conns = obj
    else:
        conns = []
    return [c for c in conns if isinstance(c, dict)] if isinstance(conns, list) else []


def line_tokens(lines: list[str]) -> list[list[str]]:
    """Token lists, one per label line (the unit endpoints are validated against)."""
    return [t for t in (tokens(line) for line in lines) if t]


def _contains(seq: list[str], sub: list[str]) -> bool:
    n = len(sub)
    return n > 0 and any(seq[i:i + n] == sub for i in range(len(seq) - n + 1))


def _covered(text: str, ltoks: list[list[str]]) -> bool:
    toks = tokens(text)
    return bool(toks) and any(_contains(lt, toks) for lt in ltoks)


def _clean_via(via: str, ltoks: list[list[str]]) -> str:
    keep = []
    for part in re.split(r"\s*[/,;]\s*", via or ""):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*-?\s*(?:wire|wires|core|cores)", part, re.I)
        if m:
            if any(m.group(1) in lt for lt in ltoks):
                keep.append(f"{m.group(1)}-wire")
            continue
        if _covered(part, ltoks):
            keep.append(part)
    return " / ".join(keep)


def validate_connections(raw: list[dict], lines: list[str]) -> list[dict]:
    """Keep only connections whose endpoints really exist in the figure (see module docstring)."""
    ltoks = line_tokens(lines)
    out: list[dict] = []
    seen: set[tuple] = set()
    for e in raw or []:
        a = str(e.get("from") or e.get("source") or "").strip()
        b = str(e.get("to") or e.get("target") or "").strip()
        via = str(e.get("via") or e.get("connection") or "").strip()
        if not a or not b or norm(a) == norm(b):
            continue
        if not (_covered(a, ltoks) and _covered(b, ltoks)):
            continue
        via = _clean_via(via, ltoks)
        key = (norm(a), norm(b), norm(via))
        if key in seen:
            continue
        seen.add(key)
        out.append({"from": a, "to": b, "via": via})
    return out
