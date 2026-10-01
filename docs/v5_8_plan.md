# v5.8 Implementation Plan

Scope: the v5.7 items that are still failing in the post-v5.7 chunk dump (`v5_7_chunks.txt`, 119 chunks).
Inputs: `HoneyWell_V2.zip` (repo), `v5_7_chunks.txt`, `.pytest_cache/.../lastfailed`, `docs/v5_7_plan.md`.
Note: the zip contains no separate Antigravity report file, so the failure list below is derived from the chunk dump and the code.

## 1. What failed in v5.7 and why

| # | Symptom in the dump | Root cause | v5.8 fix |
|---|---|---|---|
| 1 | `### **3.2 Basics**` glued to the END of the previous chunk (#14, 24, 25, 57, 71, 77, 78) | A bare trailing `###` token never matched `_ATX_RE` (it required a following non-space), and the bold heading text survived as its own item, so it was serialised into the previous chunk | `_ATX_RE` now strips a trailing `###`; chunk post-pass drops a last line that equals the next chunk's heading |
| 2 | `**bold**` and `*italic*` in ~20 chunks (#6, 56, 85, 86, 103-117) | The v5.7 text cleanup already removes `**` from `item.text`, so the `**` is re-added by the HybridChunker markdown serialiser from each item's `formatting` flag | `clean_text_items` clears `formatting` on every text item; the chunk post-pass strips any leftover `**`, `*x*` and heading `#` |
| 3 | Chunk #71 is heading-only (`CALISTHENICS MYTHS... / ### 8.1 ...`); #119 is a lone `Calisthenics Family` | Consequence of 1; running logo on the last page | Post-pass drops a chunk whose only lines are the next chunk's headings; for PDFs it drops single-line chunks under 40 chars, 3 words or fewer, no digits |
| 4 | Contents table (#5): `I. Introduction`, `I I. Equipment`, `7. 10 Crucial...` | The table has 2 columns; the v5.7 repair only ran on 3-column tables | `_try_toc()` detects a 2-column contents table (page column ascending) and rewrites it to `No. / Section / Page` with `1.`...`12.` |
| 5 | `6.5. 1Chest Circuit` and `6.2.2 Core Circuit` (#50-56) | Heading number lost its dot; the `.` split made it level 2, so Core Circuit nested under Chest Circuit and the core intro was filed wrongly. The source itself says 6.2.2 | `fix_heading_number()` then `repair_heading_sequence()` (3-level number whose 2nd part is lower than the open 2-level heading takes that heading's prefix). Both now read `6.5.1` / `6.5.2` and are siblings |
| 6 | `Day 7` instead of `Day 1` (#99) | `_renumber_sequence_captions` ran once per table group, so a lone `Day 7` never saw `Day 2` | Captions are collected and renumbered per page via `renumber_sequence()` (fixes only when at most 1/3 of numbers are wrong) |
| 7 | `r ^ Start Now L J` (#104) | Button debris passed the 60% word-character test | `is_noise_paragraph` also flags short lines where 40%+ of tokens are lone letters or `^ ~ \| _` |
| 8 | `THEFULLJOURNEYTIMELINE` (#108-110) | All-caps glued heading; vocabulary splitter skips it | One `KNOWN_FIXES` entry |

## 2. Files changed

Edited: `config.py` (new flag `CHUNK_POSTPROCESS`, default true), `core/chunker.py` (calls the post-pass before the heading-only injection, so intentional heading chunks survive), `parsers/pdf_cleanup.py`, `parsers/pdf_structure.py`.
Added: `core/chunk_cleanup.py` (pure Python, no Docling), `tests/parsing_arch/v5_8/test_v58_repairs.py` (10 tests), `tests/parsing_arch/v5_8/verify_v5_8.py`.
Kill switches: `CHUNK_POSTPROCESS=false` (chunk pass), `PDF_V57_CLEANUP=false` (all parser-level passes, unchanged).

## 3. Applying

From the project root: `patch -p1 < docs/v5_8.patch` (or `git apply docs/v5_8.patch`, or hand `v5_8.patch` to Antigravity as-is). Verified: it applies cleanly with `patch -p1` against the v5.7 files in the zip. Edited files keep their CRLF endings.
Then, with `$env:PYTHONUTF8=1`:
1. `python -m pytest tests/parsing_arch/v5_8 tests/parsing_arch/v5_7 tests/parsing_arch/v5_6 tests/parsing_arch/v5_5 -q`
2. `python tests/parsing_arch/v5_8/verify_v5_8.py <path-to-Calisthenics-pdf>` and send back the console output plus `v5_8_chunks.txt`.

## 4. What was and was not verified here

- Ran: the 10 new tests (pass), and the chunk post-pass on the real 119-chunk dump: 0 leaked `###`/`**`/`*x*` remain, chunks #71 and #119 are dropped, the tails of #14 and #24 are clean (119 -> 117 chunks).
- Not run (no Docling in my sandbox): the `formatting` clearing, the per-page caption renumbering and the heading-number pass inside `pdf_structure.py`. The string logic behind them is unit-tested; the Docling wiring is read-verified only. `verify_v5_8.py` is the end-to-end check. The `formatting` cause in fix 2 is inferred from the output pattern; the chunk post-pass removes the markup either way.

## 5. Not fixed / known issues

1. `[Figure description] In this image there are two men standing and smiling. Photograph` (#1) and the `BEGINNER CALISTHENICS PROGRAM VUlt THE FULL JDURNEY` banner line (#104) are image-captioning and image-OCR quality problems. They belong to the image-handling redesign for the real Honeywell documents, not a text-cleanup patch.
2. p.32 timeline grid still needs a hand-built JSON or a VLM table description (same as v5.7).
3. The `6.2.2` -> `6.5.2` change rewrites heading text in the index on purpose, because the source numbering is wrong. Set `PDF_V57_CLEANUP=false` to compare.
4. The 2-column contents rewrite only fires when the page column is ascending and every first cell parses as a number plus title.
5. `verify_v5_7.py` check "contents table complete" could never pass: the chunk serialiser pads table cells (`|   4 |`). `verify_v5_8.py` matches with whitespace-tolerant regexes.
6. `.pytest_cache` lists 6 older failures (`test_router.py` x3, `test_config_v5.py` x2, `test_libreoffice_converter.py` x1). They are outside this patch; they test the pre-v5 router and an environment-dependent LibreOffice lookup.
