#!/usr/bin/env python3
"""Run the real PDF through router + chunker; PASS/FAIL the v5.8 checklist; dump v5_8_chunks.txt.
Usage (project root, PowerShell: $env:PYTHONUTF8=1):  python tests/parsing_arch/v5_8/verify_v5_8.py <pdf>"""
import pathlib, re, sys

from core.chunker import Chunker
from parsers.pdf_router import PdfPageRouter

pdf = pathlib.Path(sys.argv[1])
doc = PdfPageRouter().parse(pdf.read_bytes(), pdf.name)
chunks, metas, _ = Chunker().split(doc, "verify", pdf.name)
allt = "\n".join(chunks)
checks = {
    "no leaked ### / ** / *italic*": not re.search(r"###|\*\*|(?<!\w)\*\w", allt),
    "no chunk ends with the next chunk's heading": not any(
        re.search(r"\n\d+(\.\d+)* [^\n]{3,80}$", c) and c.split("\n")[-1] in chunks[i + 1].split("\n")[:3]
        for i, c in enumerate(chunks[:-1])),
    "no heading-only / micro chunks": all(len(c.split("\n")) > 1 or len(c) >= 40 for c in chunks),
    "contents table numbered": bool(re.search(r"\|\s*12\.\s*\|\s*Words of Encouragement\s*\|\s*36\s*\|", allt))
        and bool(re.search(r"\|\s*1\.\s*\|\s*Introduction\s*\|\s*4\s*\|", allt)),
    "6.5.1 Chest / 6.5.2 Core headings": "6.5.1 Chest Circuit" in allt and "6.5.2 Core Circuit" in allt
        and "6.2.2" not in allt and "1Chest" not in allt,
    "Day 1 / Day 2 nutrition captions": bool(re.search(r"9\.8[^\n]*\nDay 1\b", allt)) and "Day 7" not in allt,
    "no button debris": "r ^ Start Now" not in allt,
    "chunk_index == position": all(m["chunk_index"] == i for i, m in enumerate(metas)),
}
for name, ok in checks.items():
    print(("PASS  " if ok else "FAIL  ") + name)
pathlib.Path("v5_8_chunks.txt").write_text(
    "\n".join(f"===== #{i} p{m.get('page_numbers')}\n{c}" for i, (c, m) in enumerate(zip(chunks, metas), 1)),
    encoding="utf-8")
print(f"{len(chunks)} chunks written to v5_8_chunks.txt")
sys.exit(0 if all(checks.values()) else 1)
