# v5.9 plan: availability marks, table serialization, figures, text coverage

> **Revision 2** — incorporates corrections from the codebase verification report (2026-10-13)
> and a second code-read review. Changes vs the original plan are marked **[Rev2]**.

Scope: PDF parser only.
Delivery: one `.patch` file plus this doc. No VLM is needed for WP0-WP4 and WP6-WP7; WP5 ships
the deterministic figure card only (**[Rev2]** VLM A/B deferred to v5.10).

---

## 1. Verified facts

| Question | Answer | How checked |
|---|---|---|
| Are the green ticks images, vectors or glyphs? | **Tiny inline raster images**, 27x26 px, drawn at 8-14 pt, all identical. p.5 has 15 of them, each inside a table cell. No tick glyphs, no private-use characters, no green vector paths. | PyMuPDF `get_image_info()` / `get_drawings()` on p.5, 16, 17, 20, 21 |
| Is "..." (unavailable) in the PDF text layer? | **Yes** (p.5: 3, p.17: 9, p.20/21: 14 each). Removed by `_clean_cell` because `_FILLER` contains `"..."`. | probe + grep |
| Is lost text recoverable? | **Yes.** p.11 steps, p.12 unlock warning, p.18 "No presence 2", p.28 "be set" are all in the PDF text layer. | `page.get_text()` substring checks |
| Why separator-only chunks? | `MarkdownTableSerializer` pads the separator to the widest cell width -> inflated prefix -> "prefix too long" warnings -> junk chunks, header not repeated. | chunker code + warnings |
| Can small images be marks everywhere? | **No.** p.20 has 454 small decomposed-graphics images. A mark must be inside a cell bbox **and** hash-repeat >= 3 times in that table. | probe |

Not yet verified (do in WP0): why bold runs (`No`, `SF12`, `be set.`) are dropped; whether `_pic` in `clean_page_markdown` (pdf_cleanup.py ~526) removes step text inside picture regions; whether the dropped p.30 cell is `V-O`; **[Rev2]** whether `export_to_markdown` uses a cached grid (affects WP3 approach); whether a sentinel prefix survives the markdown backend (affects WP1/WP6 metadata).

---

## 2. Key corrections vs the original plan **[Rev2]**

| # | Original claim | Correction |
|---|---|---|
| 1 | WP3 requires refactoring `_docling_page` to return a doc | **Wrong.** `_docling_page` already holds `doc` from `_docling_full()` before calling `export_to_markdown()`. Cellmarks is one call inserted between those two lines - no refactor needed. |
| 2 | Cellmarks should be called in `_picture_descriptions_only` | **Wrong.** That method returns only caption strings, never table content. Cellmarks goes in `_docling_page` and `_smolvlm_page` only. |
| 3 | WP4 should store `self._pdf_bytes` as instance state | **Wrong.** `PdfPageRouter` is shared across requests; instance state is unsafe. Instead: `parse()` already builds `page_texts`; also build `page_raw_texts` (list of str, one per page) there and pass it to `_merge_pages` as an extra argument. |
| 4 | WP3 should remove "..." from `_FILLER` | **Wrong - causes regression.** Cellmarks writes `Yes`/`No`/`n/a` directly into the cell text **before cleanup** runs. `_FILLER` stays unchanged. Cellmarks only converts "..." when a legend exists or the table has tick images; otherwise leaves it alone and cleanup blanks it as today. |
| 5 | Chroma metadata can be a list (`heading_path`, `page_numbers`) | **Bug.** `chromadb==0.5.15` accepts only scalar metadata values. Fix: convert `page_numbers` to a comma-separated string and `heading_path` to a `" > "` separated string. Add `_flatten_meta` in `core/chunker.py`. Validate with one real upsert in WP0. |
| 6 | Table/figure metadata fields can ride through the markdown round-trip | **Wrong.** `_merge_pages` converts markdown back through Docling's backend, which discards non-text attributes. Use a sentinel prefix (e.g. `[ct:table]`) written before the round-trip and stripped in the chunker. WP0 must verify this survives. |
| 7 | WP4 coverage is straightforward | **Risk.** Must not re-add footers (removed by `strip_running_lines`), noise (`is_noise_paragraph` rejects), ToC lines (WP2), or figure labels (WP5). Add four explicit exclusion filters. |
| 8 | (Not in original plan) Grid caching | **Unverified risk.** If `TableItem.data.grid` is cached, mutating cell text will not change what `export_to_markdown()` prints. WP0 must test this. |

---

## 3. Work packages

**Order:** WP0/0b -> WP1 + WP2 (parallel) -> WP3 + WP4 (parallel, both touch `pdf_router.py`) -> WP5 (can overlap WP3/WP4) -> WP7 -> WP6.
**Effort:** S <= 0.5 day, M ~1 day, L = 2+ days.

---

### WP0 Baseline and diagnostics (S) **[Rev2: expanded]**

Files: `tests/parsing_arch/v5_9/verify_v5_9.py`, `test_parse.py`, `core/chunker.py` (WP0b flatten).

1. Create `tests/parsing_arch/v5_9/` and `verify_v5_9.py`. Use in-memory cosine similarity with the same MiniLM model (no running Chroma/MinIO needed). The 15 golden questions are chunk assertions (substring or regex on top-5 retrieved texts).

2. Make `test_parse.py` write `chunks_<doc>.json` (UTF-8, full untruncated text). Run with `PYTHONUTF8=1`. Verify no mojibake.

3. **WP0b - metadata flatten** *(pulled forward from WP6 so all checks can run)*:
   Add `_flatten_meta(meta: dict) -> dict` in `core/chunker.py`:
   - `page_numbers: list[int]` -> `"1,2,3"` (comma string)
   - `heading_path` (from `chunk.meta.headings`) -> `" > "` separated string
   - `page: None` -> omit key
   Validate with a real Chroma upsert.

4. **Sentinel survival test**: write a single-cell markdown table with a `[ct:table]` prefix through Docling's MD->DoclingDocument converter. Check if the prefix survives in the text item.

5. Log dropped/orphan cells in `MatchingPostProcessor` fallbacks (p.30 `V-O`).

6. Print Docling text items around "presence 2" and "SF12" to diagnose dropped bold runs.

7. **Grid-caching test**: create a synthetic 2x2 `TableItem`, mutate one cell's text, call `export_to_markdown()`, check if mutation appears.

**Done when:** baseline golden-question score printed (~6 of 15 fail today); Chroma upsert confirmed; sentinel and grid-caching results recorded.

---

### WP1 Table serialization and junk chunks (M) **[Rev2: serializer approach changed; merge-not-drop]**

Files: `core/chunker.py`, `core/chunk_cleanup.py`.

1. **Custom table serializer** built from `item.data.grid` directly (avoids `MarkdownTableSerializer` signature uncertainty):
   - Emit `| col1 | col2 |` header from grid row 0.
   - Emit `|---|---|` separator (fixed narrow, no padding).
   - Emit data rows.
   Replace the implementation in `_MarkdownTableChunkSerializer`.

2. Cap the repeated-header prefix at **64 tokens** (truncate long header cell text).

3. **Post-filter** (`core/chunk_cleanup.py`):
   - Drop chunks matching `^[\s|:\-.]*$` (separator-only junk).
   - **Merge** heading-only chunks into the *next* chunk (current `postprocess_chunks` drops them - behaviour change).

4. Strip `\.{4,}` runs globally in `strip_markup`.

**Done when:** zero separator-only chunks; every table chunk has a header row; no "prefix too long" warnings; p.17, p.21, p.30 data chunks carry their headers.

---

### WP2 Table of contents out of the index (S) **[Rev2: doc_outline dropped; content_type=toc + retriever filter]**

Files: `parsers/pdf_cleanup.py`, `core/retriever.py`.

1. **Second ToC detection branch** in `_emit_clean_table`:
   - (a) Preceding heading matches `Content|Contents|Table of contents|Inhalt`, or
   - (b) >=50% of rows match `\.{4,}\s*\d+`, or last column all-numeric + first column has section-number prefixes.

2. Strip dot leaders; emit one compact chunk tagged `content_type=toc`.

3. **Retriever filter**: add `where={"content_type": {"$ne": "toc"}}` to `collection.query()`. Add `include_toc=False` param to `retrieve()`.

4. Assign `content_type="text"` as default for all other chunks.

**Done when:** retriever returns 0 ToC chunks; ~80 chunks total.

---

### WP3 Availability marks in table cells (M) **[Rev2: hook corrected; _FILLER unchanged; grid-caching contingency]**

Files: new `parsers/pdf_cellmarks.py`, `parsers/pdf_router.py`.

**Hook point**: in `_docling_page()` and `_smolvlm_page()`, between `_docling_full(...)` and `export_to_markdown()`. **Not** in `_picture_descriptions_only`.

**Legend scan** in `parse()`: scan all `page_texts` for `"= available"` / `"= unavailable"`. Pass legend dict down to `_docling_page` / `_smolvlm_page` -> cellmarks.

**`pdf_cellmarks.inject_marks(doc, page_fitz, legend)`**:

1. For each `TableItem`: get cell bboxes from `item.data.grid`. Convert origin (Docling bottom-left vs PyMuPDF top-left) using `page_fitz.rect.height`. Get image bboxes from `page_fitz.get_image_info(xrefs=True)`.

2. **Mark**: image fully inside a cell (2 pt tolerance), area <= ~400 pt^2, aspect 0.7-1.4, crop hash repeats >= 3 times in that table, dominant colour green -> tick.

3. **Cell text rule**:
   - Empty + tick -> `"Yes"`
   - Non-empty + tick -> `"Yes (<text>)"`
   - `"..."` cell, no tick, legend defines dots as unavailable -> `"No"`. Otherwise -> leave as-is.

4. **Write path**: mutate `cell.text` directly if grid not cached; otherwise serialise to markdown manually (contingent on WP0 test).

5. **Fallbacks**: unicode tick glyphs; vector paths via `get_drawings()`.

6. **Icon-with-text cells**: try `page_fitz.get_text("words", clip=cell_bbox)` first; else OCR on crop.

7. **Product-thumbnail columns**: drop column from serialization; add note `"Column 'Figure' holds product pictures."`.

8. **Table card**: prepend to every table chunk: `Table: <cols> | Section: <path> | Context: <prev sentence> | Legend: <legend>`. Matrix tables (>=60% Yes/No/-): add one-line row summaries.

**Done when:** golden questions on p.5, p.17, p.20, p.21 pass.

---

### WP4 Page text-coverage safety net (M) **[Rev2: data-flow redesigned; exclusion filters added]**

Files: new `parsers/pdf_coverage.py`, `parsers/pdf_router.py`, `parsers/pdf_cleanup.py`.

**Data flow**: `parse()` builds `page_raw_texts: list[str]` alongside `page_texts`. Signature: `_merge_pages(page_markdowns, filename, page_raw_texts)`. No instance state.

**`pdf_coverage.check_page(page_md, raw_text, running_lines, toc_page) -> str`**:

1. Normalise both sides (lowercase, collapsed whitespace, stripped punctuation).

2. **Exclusions** (not re-added):
   - Lines in `running_lines` set.
   - Lines where `is_noise_paragraph()` is True.
   - If `toc_page=True`: skip entire page.
   - Lines matching WP5 figure-card label patterns.

3. Covered = normalised raw line is a substring of normalised `page_md`.

4. **Near-match repair** (ratio >= 0.75): replace in-place. Fixes `"No presence 2"`, `"SF12 ... must not be set."`.

5. **Uncovered lines**: group by PyMuPDF block index, attach under active heading, emit `content_type=recovered_text`.

6. **`_pic` narrowing** (pdf_cleanup.py ~526): keep paragraphs that start with a digit, imperative verb, or are >6 words.

7. Log pages where (covered / total) < 0.9.

**Done when:** p.9, 11, 12 steps and p.12 warning present; p.18 and p.28 sentences correct; every page recall >= 0.9.

---

### WP5 Figure pipeline - deterministic part only (M) **[Rev2: VLM A/B deferred; PDF_FIGURE_MODE flag]**

Files: new `parsers/pdf_figures.py`, `parsers/docling_parser.py`, `config.py`.

New config: `PDF_FIGURE_MODE` = `off | labels_only | vlm_fallback` (default `labels_only`). v5.9 implements `off` and `labels_only` only.

**`pdf_figures.process_pictures(doc, page_fitz, heading_path, mode)`**:

1. **Inventory**: for each `PictureItem`, get bbox, caption, heading path.

2. **Skip rules**: same hash on >= 3 pages (decorative); bbox area < 1000 pt^2 (tiny); inside a table cell (WP3); assembly illustration with caption + adjacent steps (emit caption only).

3. **Text-layer extraction**: `page_fitz.get_text("words", clip=bbox)`. Deduplicate labels (fixes `"Out 4 Out 4 In 4 In 4"`). Keep reading order and numbers.

4. **Figure card**: `Figure: <caption> | Section: <path> | Labels: <deduped> | Numbers: <list>`.

5. **Guards**: drop if zlib ratio < 0.35; any 4-gram repeats >= 3; starts with `"In this image there is a"` or < 12 words; numbers in description absent from labels.

6. **Metadata** (all scalar): `content_type=figure`, `figure_id`, `class_hint` (Docling label string), `confidence` (`"high"` / `"low"`).

**Done when:** p.6 chunk contains `120/115/46` and no "home theater"; no looped text; no classifier labels in chunk text; run-time drops.

---

### WP6 Headings, section ids, metadata, cross-links (M) **[Rev2: all-scalar schema]**

Files: `parsers/pdf_structure.py`, `parsers/pdf_router.py`, `core/chunker.py`.

1. **Heading blacklist**: drop `Titelseite`, `GB Version`, `(TEXT wird aus LV Texte ...)`, `Fig.\d+`, `Abb.\d+`.

2. **Numbering regex** override: `^\d+(\.\d+)*\s` takes precedence. Detect `4.5.5`. Treat `Profile \d+` as level-3 headings. Nest `Features:` / `Functions:` under their `Profile N`.

3. **`section_id`**: `p{page}:{heading_number}` (e.g. `p28:1.2`), computed in `core/chunker.py`. Scalar string.

4. **Full metadata schema** (all scalar, always present):

   | Key | Type | Notes |
   |---|---|---|
   | `document_id` | str | existing |
   | `file_id` | str | existing |
   | `filename` | str | existing |
   | `chunk_index` | int | existing |
   | `heading_path` | str | `" > "` separated |
   | `section_id` | str | e.g. `"p28:1.2"` |
   | `content_type` | str | text / table / figure / toc / recovered_text |
   | `page_numbers` | str | comma string e.g. `"5,6"` |
   | `doc_number` | str | e.g. `"89470K2.GB0"` |
   | `doc_version` | str | e.g. `"V2"` |
   | `doc_date` | str | e.g. `"11.2020"` |

   Optional (omit key if not applicable): `table_id`, `figure_id`, `class_hint`, `confidence`, `source`.

5. **Cross-link R-codes**: match door/PoC combinations rows (R1-R7) to `4.5.x` headings by normalised text. Inject `R<n>` + row text into diagram chunk; inject diagram `section_id` into row chunk. Add last.

**Done when:** `"Which room type uses 3 x P4 and D3?"` retrieves R5; every 4.5.x figure chunk has its R-code; no `Titelseite` in any chunk.

---

### WP7 Spec table p.30 (M)

Files: `parsers/pdf_router.py`.

Re-extract p.30 with `page.find_tables()`; diff grid against Docling's `TableItem.data.grid`; prefer better-formed one; log diff. Normalise `?` -> `TBD`. Collapse colspan repeats into `"applies to: SEM+, SEM, SCL"`.

**Done when:** `V-0` fire class and SEM+ idle/max current (60/140 mA) are retrievable and unpolluted.

---

## 4. Tests

Golden questions (pass = top-5 retrieved chunk contains the expected fact):

| Question | Expected | Fixed by |
|---|---|---|
| Does Profile 1 have presence 2? | No | WP4 |
| How to mount the nameplate on the SEM? | 5 steps incl. blue marking on ribbon cable | WP4 |
| How to release the standalone nameplate? | press lock with a tool, do not pull without unlocking | WP4 |
| SEM dimensions / hole spacing? | 120 x 115 x 46 mm; 85 mm | WP5 |
| Does V05 support firmware update for SEM? | No | WP3 |
| Which door variants work with SEM+? | D1, D2, D3 | WP3 |
| Which PoC variants support discrete speech? | P4 | WP3 |
| Is R-ABUS available on SEM? | No (SEM+ only) | WP3 |
| SCL position for 6-wire direct connection? | ID2 / WRGY | WP3 |
| Mode switch position for duty room? | II - SCVIP | WP3 |
| Fire protection class? | V-0 | WP7 |
| SEM+ idle / max current? | 60 mA / 140 mA | WP7 |
| Room type with 3 x P4 and D3? | R5 | WP6 |
| Wire diameter accepted by terminals? | 0.6 / 0.8 mm | (already passes - regression guard) |
| Max DBUS cable length? | 400 m | (already passes - regression guard) |

Automated checks in `verify_v5_9.py` **[Rev2: updated]**:
- No chunk matching `^[\s|:\-.]*$` after breadcrumb strip; no `\.{5,}`.
- ToC chunks returned by default retriever = 0 (filter active).
- Every table chunk has a header row; tables with legend and >60% empty cells = 0.
- Per-page text recall >= 0.9; negation word counts match text layer per page.
- Figure sanity: no zlib-repetition, no generic phrases, no classifier labels in chunk text, numbers in description appear in extracted labels.
- Headings: no `Titelseite`; every `N.N.N`-prefixed source line exists as a heading.
- Encoding regex check on stored chunk JSON.
- Metadata completeness: `heading_path`, `content_type`, `page_numbers`, `section_id` on every chunk (all str).
- Chroma upsert smoke test: no `InvalidMetadataError`.

Regression guard: re-run Calisthenics doc and Systevo function table; compare chunk counts and golden answers before and after every WP.

---

## 5. Config flags **[Rev2: new section]**

| Flag | Default | Controls |
|---|---|---|
| `CHUNK_V59_TABLES` | `true` | WP1 custom serializer + junk-chunk filter |
| `PDF_V59_TOC` | `true` | WP2 ToC detection and retriever filter |
| `PDF_V59_CELLMARKS` | `true` | WP3 availability-mark injection |
| `PDF_V59_COVERAGE` | `true` | WP4 text-coverage safety net |
| `PDF_FIGURE_MODE` | `labels_only` | WP5: `off` / `labels_only` / `vlm_fallback` |
| `PDF_V59_TABLE_CROSSCHECK` | `true` | WP7 find_tables() vs Docling diff |

Thresholds:

| Setting | Default | Controls |
|---|---|---|
| `PDF_COVERAGE_RECALL_MIN` | `0.9` | WP4 per-page recall floor |
| `PDF_COVERAGE_NEAR_MATCH` | `0.75` | WP4 difflib near-match threshold |
| `CHUNK_HEADER_CAP_TOKENS` | `64` | WP1 repeated-header prefix cap |
| `PDF_MARK_REPEAT_MIN` | `3` | WP3 minimum hash repeats for a mark |

---

## 6. Risks and open points **[Rev2: updated]**

- **Grid caching** (WP3): if `TableItem.data.grid` is cached, mutation approach breaks. WP0 test determines fallback.
- **Sentinel survival** (WP1/WP6): if `[ct:table]` doesn't survive Docling's markdown backend, use a post-chunking position-keyed side-channel dict.
- **Chroma scalar constraint** (WP0b): `_flatten_meta` must run before every upsert.
- **`_pic` narrowing** (WP4): keep the heuristic narrow and keyword-gated to avoid noise regression on other documents.
- **Mark detection on other PDFs**: glyph + vector fallbacks kept for documents using unicode ticks.
- **Coordinate origin** (WP3): explicit conversion + unit test on p.5 cell 0.
- **Source defects** (swapped bed counts, SKU typos): reproduced faithfully. Not a parser bug.
- **Python version**: stay on 3.11/3.12; `langchain_core` (Pydantic V1) incompatible with 3.14.

---

## 7. Deferred to v5.10 **[Rev2: new section]**

- VLM A/B benchmark: SmolVLM-256M vs Granite Vision vs Qwen2.5-VL 3B on 12 gold figures.
- Structured JSON VLM prompt (`kind`, `title`, `components`, `connections`, `summary`).
- Flowchart "approximate" sequence marking.
- Real bboxes for UI source highlighting.

---

## 8. Research basis

- Row-level table chunks + repeated header: arXiv 2408.17008.
- Table format for LLMs: Sui et al., WSDM 2024.
- Contextual retrieval: Anthropic (2024).
- Image summaries on industrial manuals: Riedler & Langer, arXiv 2410.21943.
- Page-image retrieval: ColPali, arXiv 2407.01449.
- Grounding VLMs with text: olmOCR arXiv 2502.18443; arXiv 2412.08746.
- VLM hallucination: DianJin-OCR-R1 arXiv 2508.13238; FlowLearn (2024).
