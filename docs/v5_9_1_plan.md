# v5.9.1 plan: verification of v5.9 output + corrective patch

Scope: PDF parser only. Delivery: `v5_9_1.patch` (apply with `patch -p1 < v5_9_1.patch` from the repo root) plus this doc.
Input checked: `diag_output2.txt` (test_parse.py on `89470K2.GB0_V2.pdf`, 110 chunks) against `v5_9_plan.md` and the implemented source.

> Note: `diag_output2.txt` is a PowerShell redirect (UTF-16, console code page). `ΓëÑ` for `≥` and `├ñ` for `ä` in it are
> display artefacts, not chunk defects. Confirm on `chunks_<doc>.json` (run with `PYTHONUTF8=1`).

---

## 1. Verdict on v5.9

Not finished. Of the 15 golden questions (presence of the expected fact in some chunk, which is more lenient than top-5 retrieval):
**8 pass, 2 partial, 5 fail.**

| # | Question | Result | Evidence |
|---|---|---|---|
| 1 | Profile 1 has presence 2? | FAIL | chunk 70 reads `- presence 2` (the `No` is lost) and its heading is a bare `Features:` |
| 2 | Mount nameplate (5 steps) | pass | chunk 53 (recovered text) |
| 3 | Release standalone nameplate | pass | chunk 55 (recovered text) |
| 4 | SEM dimensions / 85 mm | FAIL | chunk 42 says "home theater", "120-inch screen"; `85 mm` absent |
| 5 | V05 firmware update SEM | pass | `No` in V05 column |
| 6 | Door variants with SEM+ | FAIL | every green tick is an empty cell |
| 7 | PoC with discrete speech | FAIL | same, ticks empty |
| 8 | R-ABUS on SEM | partial | SEM shows `No`, SEM+ is blank |
| 9 | SCL 6-wire position | pass | chunk 61 (text) |
| 10 | Duty-room switch position | pass | chunk 57 (text) |
| 11 | Fire protection class | FAIL | row reads `+ ABS-FR3010 (x% antimicrobial)`; `V-O` missing |
| 12 | SEM+ idle / max current | partial | `24V DC +/- 10% 60mA` fused into one cell |
| 13 | Room type with 3 x P4 + D3 | pass | R5 row in chunk 88 |
| 14, 15 | wire diameter, DBUS length | pass | regression guards hold |

Other plan "done when" criteria: chunk count 110 (plan ~80); ToC leak (1 chunk tagged `toc`, ~23 more ToC fragments
tagged `table` / `recovered_text` and therefore retrievable); 4 separator-only chunks (9, 10, 11, 107) plus a header-only
chunk (106); 4 `Chunks prefix is too long` warnings (796/314/312/267 tokens); 11 pages with coverage recall < 0.9;
`doc_number` / `doc_version` / `doc_date` on 0 of 110 chunks; `section_id` is `p<page>` only; 14 chunks still contain
`[Figure description]` SmolVLM text. Metadata is all scalar and complete otherwise (no list values).

## 2. Root causes (each confirmed in code or on the real PDF)

1. **Ticks never detected (WP3).** The green ticks are *inline* images, `xref == 0` (15/15 on p.5, 34 of 35 small images on p.17).
   `_image_hash()` calls `extract_image(xref)`, which fails for xref 0, so no hash ever repeats and `mark_hashes` stays empty.
   Negative control on the real p.5 and p.21 with the v5.9 module: 0 ticks marked. (The `No` cells appear only because the
   legend scan on p.17 converts `...`.)
2. **Dropped words (WP4).** Two bugs. (a) `check_page` compares each raw line with the *whole page* via `SequenceMatcher`;
   the ratio is ~0, so the near-match repair can never fire. (b) The lost words are all bold runs (`No`, `SF12`, `be set.`);
   Docling's markdown backend splits or drops inline strong runs in the page round trip, and coverage is measured before
   that round trip so it cannot see the loss. The fragmented `without presence 2` / `, for` / `1 bed` lines in chunk 69 are the
   same bug. (b) is inferred from the pattern and must be confirmed on a re-run (section 5).
3. **ToC leak (WP2/WP4).** Only the first ToC chunk is tagged; the rest keep `content_type=table`. `check_page` never gets
   `toc_page=True`, so dot-leader lines are re-added as `[Recovered text]` (chunks 8, 30).
4. **Junk chunks (WP1).** The junk regex is applied to text that still carries the breadcrumb heading, so it never matches.
   p.30 splits into header-only (106), separator-only (107) and header-less body chunks.
5. **Doc metadata (WP6).** `extract_doc_metadata()` has no caller. Its regexes would also fail on the raw first page:
   `\bV(\d+)` does not match `GB0_V2` and the number regex swallows `_V2`.
6. **Figures (WP5).** `process_pictures()` returns cards, but `_docling_page` discards the return value, `_smolvlm_page` never
   calls it, and the SmolVLM caption still runs. `heading_path` is hard-coded `[]` and Docling pictures have no `.bbox`
   (it is `prov[0].bbox`), so labels could not be extracted anyway.
7. **p.30 (WP7).** Not implemented. Only the config flag `PDF_V59_TABLE_CROSSCHECK` exists.

## 3. What v5.9.1 changes

| Fix | File | Change |
|---|---|---|
| F1 | `parsers/pdf_cellmarks.py` | hash marks by PyMuPDF `digest` (works for xref 0); log `cellmarks: N cells, M candidate imgs, K mark hashes, J cells marked` |
| F2 | `parsers/pdf_router.py` | `_strip_inline_emphasis()` removes `**` / `*` before the markdown to Docling round trip |
| F3 | `parsers/pdf_coverage.py` | line-level near-match; auto-skip ToC pages; never re-add dot-leader lines; repairs keep the list/heading prefix and never rewrite table rows |
| F4 | `core/chunk_cleanup.py` | junk test ignores the breadcrumb; header-only table fragment carried into the header-less chunks after it; all ToC chunks tagged `toc` and merged into one |
| F5 | `core/chunker.py`, `core/chunk_cleanup.py`, `parsers/pdf_structure.py` | `section_id` = `p28:1.2`; `doc_number` / `doc_version` / `doc_date` on every chunk; fixed regexes |
| T | `tests/parsing_arch/v5_9/test_v5_9_1.py` | 12 offline tests (pure Python + PyMuPDF) |

Verified offline here: 12/12 tests pass; real-PDF tick check gives **15** `Yes` cells on p.5 and **11** on p.21 (v5.9: 0 and 0);
replaying the 110 chunks from `diag_output2.txt` through the new `postprocess_chunks` gives **81 chunks**, 1 ToC chunk,
0 separator-only chunks, and the p.30 body chunks carry the `Systevo Bed Unit M | SEM+ | SEM | SCL` header.
Not verifiable without Docling: Docling's cell geometry for F1 (the new log line shows it), and F2.

## 4. Not fixed here (needs a Docling run)

- **WP5:** wire `process_pictures()` output into the document, skip SmolVLM when `PDF_FIGURE_MODE=labels_only`, read the bbox from `prov[0].bbox`, apply the guards to whatever caption remains. Fixes Q4 and the 14 `[Figure description]` chunks.
- **WP7:** `find_tables()` cross-check for p.30 (Q11, Q12).
- **WP6 nesting:** `Features:` under `Profile 1/2/3` (Q1 still lacks a profile label in its heading).
- **WP1 cap:** the 4 `prefix is too long` warnings; re-check after the ToC merge.
- **p.16:** its single tick has a unique digest, so the repeat >= 3 rule skips it (answer still in text, Q9).
- `self._tick_legend` is instance state on a shared router (Rev2 correction 3); pass it as an argument in v5.10.

## 5. Re-run checklist

1. `patch -p1 < v5_9_1.patch`, then `python -m pytest tests/parsing_arch/v5_9/test_v5_9_1.py -q` (set `V59_TEST_PDF` to the PDF).
2. `PYTHONUTF8=1 python test_parse.py ...` and keep `chunks_<doc>.json`.
3. In the log expect `cellmarks: ... marked` with J = 15 on p.5. If K > 0 but J = 0, Docling cell coordinates do not match PyMuPDF; send that line.
4. In the chunks expect: `No presence 2`, `SF12`, `| Yes |` rows on p.5/17/20/21, one `toc` chunk, no `...` leaders, ~81 chunks, `doc_number=89470K2.GB0`, `section_id` like `p28:1.2`.
5. If `No presence 2` / `SF12` are still missing, the round-trip theory (F2) is wrong; dump Docling text items around those words (WP0 item 6).
