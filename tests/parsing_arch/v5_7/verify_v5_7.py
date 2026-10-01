#!/usr/bin/env python3
"""Run the real PDF through the router + chunker and assert the v5.7 checklist.

Usage (from the project root, in the project's Python environment):
    set PYTHONUTF8=1            (PowerShell:  $env:PYTHONUTF8=1)
    python verify_v5_7.py path\\to\\Calisthenics-Training-Guide-Calisthenics-Family.pdf
Prints one PASS/FAIL line per check and a chunk dump to v5_7_chunks.txt.
"""
import pathlib, re, sys

from core.chunker import Chunker
from parsers.pdf_router import PdfPageRouter

pdf = pathlib.Path(sys.argv[1])
doc = PdfPageRouter().parse(pdf.read_bytes(), pdf.name)
chunks, metas, _ = Chunker().split(doc, "verify", pdf.name)
allt = "\n".join(chunks)
pages = {p for m in metas for p in m.get("page_numbers", [])}


def heads(c):          # heading path lines = everything before the first blank line / table
    return c.split("\n\n")[0].split("\n")


def under(text_start, heading_sub):
    hits = [c for c in chunks if text_start in c]
    return bool(hits) and all(heading_sub in heads(c)[0] or heading_sub in c[:200] for c in hits)


checks = {
    "all 36 pages covered": pages >= set(range(1, 37)),
    "no leaked '###' / '**' markup": not re.search(r"###|\*\*", allt),
    "no page footers": "Calisthenics Family | Calisthenics Training Guide" not in allt,
    "URLs rejoined": "https://calisthenics-family.com" in allt and "https:/ /" not in allt and "bmr-calculator" in allt,
    "promo codes exact": all(c in allt for c in ("BEGINNER25", "FULLJOURNEY25", "BURNFAT25")) and "FULUOURIMEY" not in allt,
    "per 100g / Squat fixed": "perlOOg" not in allt and "Sguat" not in allt,
    "no lost-space samples": not re.search(r"basedon|combinedwith|shouldyouconsume|consumehealthy", allt),
    "no OCR word-soup (p23/p28/p29)": not re.search(r"Yes\s+t s S|In fo on ot|nut t t nts", allt),
    "no doubled hydration paragraph": allt.count("liter of extra fluid") == 1,
    "7.x sections not under Beginners Circuit": not any("Beginners Circuit" in c[:120] and re.match(r"7\.\d", c.split("\n")[1] if "\n" in c else "") for c in chunks),
    "CTA lines not headings": not any(h in allt.split("\n\n")[0] for h in ()) and not any(
        c.strip().startswith(("Start Your Journey Now!\n", "> Beginner")) for c in chunks),
    "'Day 1' and 'Day 2' tables present": sum("| 12:00 Breakfast" in c for c in chunks) >= 2,
    "protein tables are separate groups": "Beef, Fish" not in allt and "| Fish | Protein (per 100g) |" in allt,
    "core circuit keeps both round headers": "Round 1 (Dynamic)" in allt and "Round 2 (Static)" in allt,
    "contents table complete": "| 12. | Words of Encouragement | 36 |" in allt,
}
for name, ok in checks.items():
    print(("PASS  " if ok else "FAIL  ") + name)
pathlib.Path("v5_7_chunks.txt").write_text(
    "\n".join(f"===== #{i} p{m.get('page_numbers')}\n{c}" for i, (c, m) in enumerate(zip(chunks, metas), 1)),
    encoding="utf-8")
print(f"{len(chunks)} chunks written to v5_7_chunks.txt")
sys.exit(0 if all(checks.values()) else 1)
