"""v5.9 WP0: Automated golden-question harness and chunk-quality checks.

Usage (no Chroma or MinIO required -- uses in-memory cosine similarity):
    PYTHONUTF8=1 python -m pytest tests/parsing_arch/v5_9/verify_v5_9.py -v \
        --chunks-json chunks_89470K2.json

Or load a JSON produced by test_parse.py and run directly:
    python tests/parsing_arch/v5_9/verify_v5_9.py chunks_89470K2.json
"""
from __future__ import annotations

import json
import re
import sys
import math
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# In-memory retriever (cosine similarity with MiniLM)
# ---------------------------------------------------------------------------

def _embed(texts: list[str]):
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return model.encode(texts, normalize_embeddings=True)


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot  # already normalised


def retrieve_top5(query: str, chunks: list[str], embeddings) -> list[str]:
    q_emb = _embed([query])[0]
    scores = [_cosine(q_emb, e) for e in embeddings]
    top = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:5]
    return [chunks[i] for i in top]


# ---------------------------------------------------------------------------
# Automated chunk checks
# ---------------------------------------------------------------------------

def check_no_junk_chunks(chunks: list[str]) -> list[str]:
    """No chunk should be separator-only or pure dots."""
    junk_re = re.compile(r"^[\s|:.-]*$")
    dots_re = re.compile(r"\.{5,}")
    fails = []
    for i, c in enumerate(chunks):
        stripped = c.strip()
        if junk_re.match(stripped):
            fails.append(f"chunk #{i}: separator-only junk")
        if dots_re.search(stripped):
            fails.append(f"chunk #{i}: contains dot-leader run: {stripped[:60]!r}")
    return fails


def check_toc_not_indexed(chunks: list[str], metas: list[dict]) -> list[str]:
    """content_type=toc chunks must be 0 (retriever filter gates them out)."""
    fails = []
    for i, m in enumerate(metas):
        if m.get("content_type") == "toc":
            fails.append(f"chunk #{i}: content_type=toc present in index (filter missing)")
    return fails


def check_table_headers(chunks: list[str]) -> list[str]:
    """Every chunk with a pipe-table body should have a separator row -> header."""
    fails = []
    for i, c in enumerate(chunks):
        lines = c.splitlines()
        has_body = any(l.strip().startswith("|") and "---" not in l for l in lines[2:])
        has_sep = any(re.match(r"^\|[-:| ]+\|\s*$", l) for l in lines)
        if has_body and not has_sep:
            fails.append(f"chunk #{i}: table body without header/separator")
    return fails


def check_metadata_completeness(metas: list[dict]) -> list[str]:
    """heading_path, content_type, page_numbers, section_id must be present and str."""
    required_str = ("heading_path", "content_type", "page_numbers", "section_id")
    fails = []
    for i, m in enumerate(metas):
        for key in required_str:
            val = m.get(key)
            if val is None:
                fails.append(f"chunk #{i}: missing metadata key {key!r}")
            elif not isinstance(val, str):
                fails.append(f"chunk #{i}: {key!r} is {type(val).__name__}, expected str")
    return fails


def check_encoding(chunks: list[str]) -> list[str]:
    """No mojibake characters."""
    mojibake_re = re.compile("[\u251C\u252C\u0393\u2229\u00C3\u00C2]")
    fails = []
    for i, c in enumerate(chunks):
        if mojibake_re.search(c):
            fails.append(f"chunk #{i}: contains mojibake: {c[:80]!r}")
    return fails


def check_no_classifier_labels(chunks: list[str]) -> list[str]:
    """class_hint labels (Bar chart, Screenshot, etc.) must not appear in chunk text."""
    hint_re = re.compile(r"\b(?:Bar chart|Pie chart|Screenshot from manual|Photograph|"
                          r"Wiring diagram|Table)\b", re.I)
    fails = []
    for i, c in enumerate(chunks):
        if hint_re.search(c):
            fails.append(f"chunk #{i}: classifier label in text: {c[:80]!r}")
    return fails


# ---------------------------------------------------------------------------
# Golden questions
# ---------------------------------------------------------------------------

GOLDEN_QUESTIONS = [
    ("Does Profile 1 have presence 2?",           r"(?i)\bno\b.*presence\s*2|presence\s*2.*\bno\b"),
    ("How to mount the nameplate on the SEM?",    r"(?i)ribbon cable|blue marking|nameplate"),
    ("How to release the standalone nameplate?",  r"(?i)press.*lock|do not pull|unlock"),
    ("SEM dimensions / hole spacing?",            r"120.*115.*46|85\s*mm"),
    ("Does V05 support firmware update for SEM?", r"(?i)V05.*[Nn]o|[Nn]o.*V05|firmware.*V05"),
    ("Which door variants work with SEM+?",       r"D1.*D2.*D3|D[123]"),
    ("Which PoC variants support discrete speech?", r"(?i)P4|discrete speech"),
    ("Is R-ABUS available on SEM?",               r"(?i)R-ABUS.*[Nn]o|SEM\+.*only"),
    ("SCL position for 6-wire direct connection?",r"(?i)ID2|WRGY"),
    ("Mode switch position for duty room?",       r"(?i)II.*SCVIP|SCVIP"),
    ("Fire protection class?",                    r"V-0"),
    (r"SEM\+ idle / max current?",                r"60\s*mA|140\s*mA"),
    ("Room type with 3 x P4 and D3?",             r"(?i)R5"),
    ("Wire diameter accepted by terminals?",      r"0\.6.*0\.8\s*mm|0\.8.*0\.6\s*mm"),
    ("Max DBUS cable length?",                    r"400\s*m"),
]


def run_golden_questions(chunks, embeddings) -> tuple[int, int, list[str]]:
    fails = []
    passed = 0
    for question, pattern in GOLDEN_QUESTIONS:
        top5 = retrieve_top5(question, chunks, embeddings)
        found = any(re.search(pattern, c) for c in top5)
        if found:
            passed += 1
        else:
            fails.append(f"FAIL: {question!r}  (pattern: {pattern!r})")
    return passed, len(GOLDEN_QUESTIONS), fails


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python verify_v5_9.py chunks_<doc>.json")
        sys.exit(1)

    json_path = Path(sys.argv[1])
    data = json.loads(json_path.read_text(encoding="utf-8"))
    chunks = [d["text"] for d in data]
    metas  = [d["metadata"] for d in data]

    print(f"\nLoaded {len(chunks)} chunks from {json_path.name}")
    print("=" * 60)

    all_fails = []

    # Automated checks
    checks = [
        ("No junk chunks",            check_no_junk_chunks(chunks)),
        ("ToC not in index",          check_toc_not_indexed(chunks, metas)),
        ("Table headers present",     check_table_headers(chunks)),
        ("Metadata completeness",     check_metadata_completeness(metas)),
        ("No encoding issues",        check_encoding(chunks)),
        ("No classifier labels",      check_no_classifier_labels(chunks)),
    ]
    for name, fails in checks:
        status = "PASS" if not fails else f"FAIL ({len(fails)} issues)"
        print(f"  [{status}] {name}")
        all_fails.extend(fails)

    # Golden questions
    print("\nRunning golden questions (requires sentence-transformers)...")
    try:
        embeddings = _embed(chunks)
        passed, total, gq_fails = run_golden_questions(chunks, embeddings)
        print(f"  Golden questions: {passed}/{total} passed")
        all_fails.extend(gq_fails)
    except ImportError:
        print("  [SKIP] sentence-transformers not installed — skipping golden questions")

    print("\n" + "=" * 60)
    if all_fails:
        print(f"TOTAL FAILURES: {len(all_fails)}")
        for f in all_fails[:20]:
            print(f"  - {f}")
    else:
        print("ALL CHECKS PASSED")

    sys.exit(1 if all_fails else 0)


if __name__ == "__main__":
    main()
