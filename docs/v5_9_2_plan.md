# v5.9.2 plan: why v5.9.1 did not fix ticks / ToC / "random characters", and the corrective patch

Scope: PDF parser only. Delivery: `v5_9_2.patch` (apply from the repo root: `patch -p1 < docs/v5_9_2.patch`) plus this doc.
Checked against: `diag_output2.txt` (STIP, 89470J4), `diag_output3.txt` (SEM, 89470K2), the real `89470J4.GB0.pdf`, and the v5.9.1 source.

## 1. What was actually wrong

| Symptom | Root cause | Evidence |
|---|---|---|
| Ticks show as `∩â╝` (STIP doc) | The ticks are **Wingdings font glyphs**, not images. PyMuPDF4LLM and Docling return them as private-use characters (tick = U+F0FC). v5.9 / v5.9.1 only detect tick *images*, and nothing maps private-use characters to text. | On the real PDF, p.16 has 35 x U+F0FC, p.27 has 30; PyMuPDF4LLM output contains `\|\uf0fc\|\uf0fc\|**…**\|\uf0fc\|`. 0 images on p.5 and p.27. |
| "Random characters" (`∩â¿`, `néü`, `néà`...) | Same cause: arrows U+F0E8 and circled call-out numbers U+F081..F088 (Wingdings) pass through untouched, in tables and in running text, on both the text route and the Docling route. | p.13: F085 F086 F0E8; p.14: F087 F088 F0E8. F081..F08A are the circled numbers 1..10, and numbering continues across pages (p.14 uses 7 and 8). |
| Blank tick cells (SEM doc) | Image ticks **are** detected by v5.9.1's hash fix, but the cell matching fails on real Docling output. v5.9.1 needs the image to lie fully inside one cell box (2 pt tolerance) and writes `cell.text` on grid cells. TableFormer boxes are approximate, and docling-core rebuilds `grid` on every access, with blank placeholders for cells that have no content, so a write to a placeholder is lost. | The v5.9.1 test fabricated its cells from PyMuPDF `find_tables()` rectangles (pixel exact) in a static list, so it could not fail this way. With a Docling-like fake (rebuilt grid, placeholders, shifted boxes) the v5.9.1 code loses the ticks even with exact boxes (negative control in `test_v5_9_2.py`). |
| ToC still leaks | Only the first ToC page is tagged (it has a "Contents" heading). The continuation page (p.3) is reflowed text with no dot leaders left (v5.9 WP1 collapses them first), so `_TOC_ROW_RE` never matches and 4 fragments stay retrievable as `text` / `recovered_text`. | diag_output2 chunks 8, 9, 10 (dense "2.4 Title 10 2.5 Title 12 ..." entries, type `text`) and 11 (`recovered_text`). |
| `ΓÇö`, `├ñ`, `-¬`, `-¦` | **Display artefacts** of the PowerShell redirect (console code page), not chunk defects: `-¬` is `©`, `├ñ` is `ä`, `-¦` is `°`/`²`. Only the private-use glyphs above are real. | v5.9.1 plan already notes this; confirm on `chunks_<doc>.json`. |

## 2. Changes

1. `parsers/pdf_glyphs.py` (new): `normalize_glyphs()` turns a table cell that is only a tick into `Yes` (cross into `No`); other private-use glyphs map to `✓ ✗ → • ①..⑩`; unknown ones are dropped. `strip_glyphs()` removes them from raw page text for the coverage check.
2. `parsers/pdf_router.py`: both applied at the start of `_merge_pages()`, the one place every route (text, Docling, SmolVLM) passes through.
3. `parsers/pdf_cellmarks.py`: image ticks are located by the image **centre** (cell box +3 pt), snapping to the nearest row/column when no box contains it; the mark is written into `table_cells` so it survives export (a cell is added when none covers the position); if no image digest repeats, ticks are judged by colour. A WARNING line is logged when small images were seen in a table but none became a mark.
4. `core/chunk_cleanup.py`: ToC detection also counts "number title page" entries (>=4 entries covering >=55% of the chunk, or >=2 right after a ToC chunk), tags the "Table of Contents" residue after a ToC chunk, and drops running-header lines from the merged ToC chunk.
5. `tests/parsing_arch/v5_9/test_v5_9_2.py`: 12 tests, including a real-PDF glyph test (`V592_STIP_PDF=<path to 89470J4.GB0.pdf>`).

## 3. Verified here / not verified

Verified (sandbox, no Docling): all 12 new tests pass and the 10 existing v5.9.1 tests still pass; the patch applies cleanly to the repo; the real STIP page 16 has no private-use character left and 30+ `Yes`; the real STIP chunks 3-14 collapse so the ToC is one chunk (`page_numbers` 2,3) and chunks 8-11 no longer exist as separate chunks; the cellmarks and ToC tests fail on the v5.9.1 code (negative control).

**Not verified:** a full run through Docling, and the SEM image-tick path on the real 89470K2 PDF (neither is available in the sandbox). The cellmarks change fixes both failure modes above, but whether either was the one that hit your run is inferred.

## 4. Re-run and what to look for

```
python -X utf8 test_parse.py <89470K2 pdf>   (with PDF_DEBUG_HEADING_DUMP=1 as before)
python -X utf8 test_parse.py <89470J4 pdf>
```
Save with `Out-File -Encoding utf8` (or read `chunks_<doc>.json`); do not hand-edit with `Get-Content`/`Set-Content` on Windows PowerShell 5.1, which writes ANSI.

- STIP: no `∩â╝`, `∩â¿` or `néü` left; the feature table (p.16) and profile table (p.27) show `Yes`/`No`; one `toc` chunk covers pp. 2-3.
- SEM: the Door / Bathroom-WC / PoC tables show `Yes` where the ticks are. If a tick cell is still blank, look for the line `cellmarks: ... small imgs in table, ... 0 cells marked` in the console and send it along with the page number.

## 5. Known leftovers (not in this patch)

- The merged ToC chunk keeps one running-header line with the document number (`Systevo Touch IP (STIP) 89470J4.GB0 / 10.2021`).
- The running page header `Systevo Touch IP (STIP)` and the copyright line become part of `heading_path` on pp. 2-3.
- The earlier hand-repaired `diag_output2/3.txt` are superseded: those fills were guesses from table layout, not parser output.
