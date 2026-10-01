# v5.7 Implementation Plan

Scope: everything still open from the v5.4 review list after v5.5 and v5.6, plus the "later stage" items v5.6 deferred.
Inputs used: `HoneyWell_V2.zip` (repo), the post-v5.6 chunk dump `diag_output2.txt` (128 chunks), and the source PDF.

## 0. Correction to my previous message

I said the garbled text (#76, #95, #97) and the lost spaces came from `pymupdf4llm.to_markdown()` running OCR by default. **That was wrong.** Testing against the real PDF shows:

- Every one of the 36 pages is a single full-page bitmap (1500x2122) with an embedded text layer. The text layer itself is clean on p.23, p.28 and p.29; `use_ocr=False` gives byte-identical output to the default there, so pymupdf4llm was not the cause.
- Every page that showed corruption (15, 16, 23, 27, 28, 29) is routed to a **Docling tier** by `_triage_page`: pages 15, 16, 27, 28, 29 as table pages, and p.23 (579 characters, under the 800 threshold) as an image page. Both tiers build their converter with Docling's default `do_ocr=True`. Because the whole page is a bitmap, Docling OCRs all of it and replaces the good text layer with OCR output.
- This also explains the headers lost in the tables. White text on a green header row is what OCR fails on, and it is why "Day 1" and "Meal / Consumption" went missing.

So the primary fix is to turn Docling's OCR off for pages that have a text layer. I could not run Docling in my environment (the sandbox has no room to install it), so this fix is **verified by reading the code path and by testing the page-level cleanup on the real PDF, but not by an end-to-end run**. `verify_v5_7.py` is the end-to-end check.

## 1. Status of v5.5 and v5.6 (verified against the repo)

Both patches are applied in the working tree, and the 40 tests in `v5_5`, `v5_6` and `v5_2/test_heading_integrity.py` pass. In the post-v5.6 dump:

| Item | Result |
|---|---|
| Heading numbers relocated and levelled (`5.7`, `6.4`, `6.5.1`, `9.6`) | Fixed |
| Freeze on `TitleItem` level 0, tail-orphan chunks, empty L1 heading | Fixed |
| §7.1–7.4 filed under "Beginners Circuit" | Fixed (nested under `10 CRUCIAL TRAINING PRINCIPLES`) |
| Literal `### **7.1 …**` glued to body text | Mostly fixed. It only matches when `###` follows a newline or 2+ spaces. v5.7 handles the single-space case. |
| Chunks #10, #55, #71 (heading-only), CTA and bullet headings (#105–107, #113–114), text corruption, table semantics, footers, photo noise | Still open. This patch. |

## 2. What v5.7 changes

Four existing files are edited and two modules are added. Nothing is removed. `PDF_V57_CLEANUP=false` turns the cleanup and structure passes off, and `PDF_ALLOW_OCR_ON_TEXT_PAGES=true` restores the old OCR behaviour.

### 2.1 OCR and extraction (`pdf_router.py`, `docling_parser.py`, `config.py`)
- New `_build_text_layer_converter()`: a Docling PDF converter with `do_ocr=False` and table structure kept on.
- The router computes each page's text-layer length once. Pages with at least `PDF_TEXT_LAYER_MIN_CHARS` (40) characters use the OCR-free converters in the table tier and in both VLM calls (`_build_vlm_converter(do_ocr=False)`). Pages without a text layer keep OCR.
- The pymupdf4llm text path passes `header=False, footer=False, use_ocr=False`, with a fallback for older versions that reject those arguments. On the real PDF this alone removes the footer from 27 of 34 pages.

### 2.2 Text and markdown cleanup (new `parsers/pdf_cleanup.py`)
Pure functions with no Docling imports. They run on each page's markdown before Docling's markdown reader sees it, and again per item after the merge.
- **Lost spaces:** the vocabulary is built from the PDF's own text layer. `basedon` becomes `based on`, and `RingDips` becomes `Ring Dips`. A token is only split when every piece is a word the document itself uses. Words the text layer already contains are never touched, so `Brinta`, `Shrimpflip` and `hetCOI` are safe.
- **Markup leaks:** `###`, `**`, `<br>`, `<sup>` and `mind**<sup>**-**</sup> **set**` (now `7.5 Bodybuilding mind-set`).
- **URLs:** `https:/ /site.com / meal-plan` becomes `https://site.com/meal-plan`. `bmr -calculator /` is fixed the same way.
- **Corpus typos:** `perlOOg` becomes `per 100g`, `Sguat` becomes `Squat`, and the promo codes are snapped to the known list (`BEGINNER25`, `FULLJOURNEY25`, `BURNFAT25`) when at least 70% similar. Edit `PROMO_CODES` and `KNOWN_FIXES` for other documents.
- **Soft breaks:** `15\n-\n30` becomes `15-30`, and single newlines become spaces.
- **Photo-OCR debris:** picture-text blocks and short paragraphs that are mostly non-words are dropped. Logo text that reads as words ("BY CALISTHENICS FAMILY") is kept.
- **Running footers:** a line that repeats on at least 4 pages, or 10% of them, is removed. This includes footers typed as `# **…**`, and digits are normalised so `Guide 4` equals `Guide 2 6`.
- **Doubled paragraphs:** the #96 case keeps the copy with proper spacing.

### 2.3 Tables (in `pdf_cleanup.py` plus `core/chunker.py`)
- Side-by-side protein tables are split into one table per column group, so "Beef, Fish = Tuna" can no longer be produced.
- Back-to-back tables get a blank line between them. Without it a markdown reader merges the second header into the first table's data.
- A body row that repeats the header's tail (the `Round 2 (Static)` row on p.17) starts a new table with its own header.
- Contents table: numerals repaired (`I.` → `1.`, `II` → `11.`, `10` + `. Workout Programs` → `10.` + `Workout Programs`) and given a real header.
- `…` filler rows and cells are dropped, and cell spacing is fixed (`Exc.1` → `Exc. 1`, `Nuts(Avg.)` → `Nuts (Avg.)`).
- `HybridChunker` now uses a markdown table serializer with `repeat_table_header=True`. Each row stays whole, the header repeats in every chunk of a long table, and the `row, col = value` triplets are gone.

### 2.4 Structure repair (new `parsers/pdf_structure.py`, called after `_repair_pdf_headings`)
- **Pseudo-headings demoted to text:** call-to-action lines ending in `!`, `> ` bullets, button labels (`Get The Program`, `Transform Now`), sign-offs (`Best,`), `Use Code …` lines, and CTA lines that sit directly before a promo code. This fixes §10.2 and §10.3 being filed under CTA headings.
- **Unnumbered labels bound to their table:** `Day 1`, `Day 2`, `Animal Protein` and similar become the table's caption. They leave the heading path and travel with the table chunk. Sequences like `Day 7`/`Day 2` are renumbered.
- **Relative levels for unnumbered headings:** one level below the last numbered heading, so `Animal Protein` and `Beginners Circuit` no longer stay at L1 and no longer close numbered sections.
- Echo removal (a paragraph that only repeats a neighbouring heading) and stripping of a heading repeated at the end of a paragraph.

## 3. Coverage against the review list

| Review item | v5.7 |
|---|---|
| Heading bleed 56–61 | Already fixed in v5.6; kept |
| Core circuit intro, duplicates, orphan "Advanced Circuit" (#52–55) | Round header rows and the "Advanced/Beginners Circuit" levels fixed. **The intro still sits under 6.5.1 (see 5).** |
| §10.2, §10.3 filing | Fixed by 2.4 (unit-tested with a synthetic document) |
| Trailing-number headings | Fixed in v5.6 |
| Leaked markup (#56, 71, 73, 77, 78) | Fixed (2.2) |
| `mind-set` split, stray `**-**` (#62) | Fixed (2.2) |
| Text corruption (#76, 95, 97), lost spaces | OCR off + vocabulary repair (2.1, 2.2) |
| #96 duplicate | Fixed (2.2) |
| Broken URLs, `perlOOg`, `Sguat`, promo codes | Fixed (2.2) |
| Animal/veg protein pairing, fats header, weekly table, contents, carbs scramble | 2.3 plus the OCR fix (the header rows should now exist in the text layer) |
| Mid-row chunk cuts, "Day 2" label at the wrong end | Fixed by 2.3 and 2.4 |
| Footers (~18 chunks), photo junk, newline fragments | Fixed (2.2) |
| Logo "BY CALISTHENICS FAMILY" (#1) | Recovered from the text layer now that OCR no longer overwrites it |

## 4. Tests and verification

- `tests/parsing_arch/v5_7/test_v57_cleanup_and_structure.py`: 19 tests. They cover text repairs, table normalisation, heading and caption behaviour on a synthetic document, row-atomic table chunking with header repeat, and a real-PDF test that runs the sample through pymupdf4llm and the cleanup, then asserts.
- Results in my environment: **59 passed** (19 new plus the 40 from v5.5, v5.6 and v5.2). Docling was replaced by stubs, and its markdown reader, table model, OCR and VLM never ran. The 4 tests in `v5_4/test_flatten_reverted.py` fail identically on the untouched repo because they need the real converter.
- Measured on the real PDF at page-markdown level (before → after): footer lines 34 → 0, picture-text blocks 54 → 0, `<sup>` tags 24 → 0, `perlOOg` 6 → 0, `**-**` 3 → 0, `https:/ /` 1 → 0.
- `verify_v5_7.py` runs the real router and chunker and prints PASS/FAIL for 15 checks, then writes `v5_7_chunks.txt` for review. Please run it before trusting any Docling-dependent claim above.

## 5. Not fixed, and known risks

1. **Core circuit intro under "Chest Circuit 6.5.1".** This is a reading-order or numbering problem in the source: the PDF numbers the core circuit `6.2.2` where it should be `6.5.2`. I can't fix it without either renumbering by rule or seeing the raw page markdown. Please send `pymupdf4llm` output for p.16–17 if you want it done.
2. **p.32 timeline.** It is a bitmap grid. The text layer has the words but not the grid structure, and "One Arm Pushups" and "Adv. Tucked Backlever" are already split there. I recommend a hand-built JSON, or a VLM description. I did not attempt it.
3. **`Apply The 8 80/20 Rule 66`** (§9.9). The "9.9" is missing upstream, so a rule cannot recover it safely.
4. **Duplicate Advanced/Beginner tables (#53/#54).** The two tables are identical in the PDF. v5.7 keeps them, which is correct, but retrieval will see near-duplicates.
5. **Vocabulary repair** is conservative. A glued word made only of rare words will be left as is. `Nowadays`, `everybody` and similar real words are protected because the text layer uses them.
6. Behaviour depends on your installed `pymupdf4llm` and `docling` versions. Please send the output of `pip show pymupdf4llm pymupdf docling docling-core`.
7. Not unit-tested: the `Day 7` → `Day 1` renumbering, and `_smolvlm_page` / `_picture_descriptions_only` with `do_ocr=False`.

## 6. Applying and checking (no source-control commands needed)

1. Unzip this folder next to the project, then from the project root run:
   `python <path>\v5_7\apply_v5_7.py .`
   It checks every edit anchor first, edits the four files (keeping each file's CRLF/LF style), and copies the two modules and the tests. Running it twice is harmless.
2. `$env:PYTHONUTF8=1; $env:PYTHONIOENCODING="utf-8"` before any run, so the mojibake in the console stops hiding real problems.
3. Run the tests: `python -m pytest tests/parsing_arch/v5_7 tests/parsing_arch/v5_6 tests/parsing_arch/v5_5 -q`
4. Run `python <path>\v5_7\verify_v5_7.py <path-to-pdf>` and send me `v5_7_chunks.txt` plus the console output.

`v5_7.patch` is a plain unified diff of the same change, provided for reading and review only. The apply script is the supported way to install it.
