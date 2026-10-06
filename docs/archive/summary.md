# Summary of Changes (since commit `2dadc28c`)

**Base Commit:** `2dadc28c4a152cabda6527069eb8d2a7a31cae4e` ("*fix: lazy-init DocumentConverter in DoclingParser to avoid ~8s startup delay on import*")  
**Current HEAD:** `8a523c4673152c2e8760bc238638e238610fdf86`  
**Branch:** `parser_v1` (pulled into `parser_docs`)  
**Scope:** Parsing Architecture versions **v4 through v5.8.1**

---

## 1. Executive Summary

Since commit `2dadc28c`, the parsing pipeline underwent a massive transformation. What started as an initial placeholder stub for PDF files (`v4`) evolved into a production-grade, multi-tiered, self-healing PDF parsing and document restructuring pipeline (`v5` through `v5.8.1`).

### The Main Shifts:
1. **API Pipeline Wire-Up (`v4`)**: Wired the live FastAPI ingestion endpoint (`POST /api/v1/documents`) to use `ParserRouter` and Docling's `HybridChunker` across all supported document types (.txt, .md, .docx, .pptx, .doc, .ppt, and .pdf).
2. **Dynamic Per-Page Triage (`v5`)**: Replaced the basic PDF stub with `PdfPageRouter`. Each page is triaged using PyMuPDF (`fitz`) and routed to the most efficient/accurate engine:
   - **Fast Text Tier**: `PyMuPDF4LLM` for text-dense pages (fast, low overhead).
   - **Table Tier**: `Docling` table structure parser for tabular pages.
   - **Visual / VLM Tier**: `SmolVLM` (`SmolVLM-256M-Instruct`) for image and diagram descriptions.
3. **Deep Structural & Heading Repair (`v5.1` – `v5.6`)**: Solved critical edge cases discovered during real-PDF benchmarking:
   - Restored missing page provenance (`page=None`) by tracking and stamping `prov` across pages.
   - Fixed the **"Heading Freeze"** bug where level-0 titles (`TitleItem`) locked hierarchical context across dozens of unrelated chunks.
   - Fixed **tail orphans** where synthetic heading chunks were appended to the end of the document instead of placed in chronological page order.
   - Reverted `_flatten_document()` after discovering it caused table data loss (`v5.4`).
4. **OCR Protection, Text Sanitization & Chunk Post-Processing (`v5.7` – `v5.8.1`)**:
   - Prevented Docling from running destructive OCR over pages with existing native text layers.
   - Extracted standalone modules: `parsers/pdf_cleanup.py`, `parsers/pdf_structure.py`, and `core/chunk_cleanup.py`.
   - Repaired broken words without an external dictionary using a PDF-derived vocabulary dynamic programming segmenter (`basedon` $\rightarrow$ `based on`).
   - Cleaned leaked markdown markup (`###`, `**`, `*italic*`), glued headings, button debris, corrupted TOCs, and micro-label orphans (`Calisthenics Family`).

---

## 2. Commit Timeline & Milestones

| Commit | Tag / Milestone | Primary Focus |
|---|---|---|
| `2dadc28` | *Base Commit* | Lazy-init of `DocumentConverter` in `DoclingParser`. |
| `3434640` | **v4 & v5** | Implemented `PdfStubParser`, wired FastAPI endpoints to `ParserRouter`, introduced `PdfPageRouter` with per-page triage (PyMuPDF4LLM / Docling / SmolVLM). |
| `d80aabd` | **v5.1** | **Page Provenance Fix**: Stamped `ProvenanceItem` during page merge to fix `page=None` / `page_numbers=[]`. Recalibrated triage character thresholds. |
| `bd3fdff` | **v5.2** | **VLM Pipeline Options Fix**: Switched to `PdfPipelineOptions(generate_page_images=True)`. Added initial heading repair pass (`_repair_pdf_headings`). |
| `f2f584a` | **v5.3** | Stripped raw SmolVLM generation tokens (`<image>`, `<end_of_utterance>`). Added `_flatten_document()` to fix ordering. |
| `ab2fe0f` | **v5.3 Hotfix** | Stamped provenance on tables and pictures, not just text items. |
| `418c084` | **v5.4** | **Reverted `_flatten_document()`** (it had dropped all tables). Added read-only Diagnostic A & B (`PDF_DEBUG_HEADING_DUMP`). |
| `333970c` | **v5.4 Fix** | Routed diagnostics to `print()` rather than `logger.info` for test runners without logger configuration. |
| `9289d10` | **v5.5** | **Heading Freeze Fix**: Normalized all headings into `SectionHeaderItem` with explicit depth levels (eliminated `TitleItem` level-0 lock). **Tail Orphan Fix**: Inserted synthetic heading chunks at page positions. |
| `df3b1c9` | **v5.8.1** (inc. v5.6–v5.8) | Leaked markup stripping, heading renumbering, 2-column TOC repair, OCR bypass for text layers, vocabulary segmenter, table Markdown serialization, and micro-label drop. |
| `8a523c4` | *Housekeeping* | Removed duplicate diagnostic scripts and temporary chunk text dumps (`v5_7_chunks.txt`, `v5_8_chunks.txt`). |

---

## 3. Core Architectural Modules

```
                    Incoming File (.pdf)
                             │
                             ▼
                parsers/router.py (ParserRouter)
                             │
                             ▼
              parsers/pdf_router.py (PdfPageRouter)
               ├── 1. fitz page triage (_triage_page)
               │      ├── Text tier   ──> pymupdf4llm
               │      ├── Table tier  ──> Docling (do_ocr=False if text layer exists)
               │      └── Image tier  ──> SmolVLM (PdfPipelineOptions)
               │
               ├── 2. Markdown Cleanup (parsers/pdf_cleanup.py)
               │      └── Vocabulary word segmentation, soft hyphens, URL fixes
               │
               ├── 3. Page Merge & Provenance Stamping (_merge_pages)
               │
               ├── 4. Heading & Depth Normalization (_repair_pdf_headings)
               │      └── Normalize to SectionHeaderItem, strip TitleItem level-0
               │
               └── 5. Structure Normalization (parsers/pdf_structure.py)
                      └── TOC repair, demote CTA buttons, caption binding
                             │
                             ▼
                   DoclingDocument Object
                             │
                             ▼
                  core/chunker.py (Chunker)
               ├── 1. HybridChunker (with MarkdownTableSerializer)
               ├── 2. Chunk Cleanup (core/chunk_cleanup.py)
               │      └── Strip leaked ###, **, trailing glued headings
               ├── 3. Gap-B Synthetic Heading Insertion (in page order)
               └── 4. Micro-label suppression (skip lone brand labels)
                             │
                             ▼
                  Final Output: List[Chunk]
```

### New Files Created
- `parsers/pdf_router.py`: Full PDF orchestration engine with per-page triage, tier routing, and provenance merge.
- `parsers/pdf_stub.py`: Minimal baseline parser using Docling (kept for fallback and stub testing).
- `parsers/pdf_cleanup.py`: Pure Python string-level sanitizer (no Docling dependency; easy to unit test).
- `parsers/pdf_structure.py`: Docling document-tree structure repair (TOC detection, caption binding, CTA demotion).
- `core/chunk_cleanup.py`: Post-processing on chunk text to remove formatting leaks and drop duplicate/echo chunks.
- Comprehensive test suites under `tests/parsing_arch/` (`v4`, `v5`, `v5_1`, `v5_2`, `v5_3`, `v5_4`, `v5_5`, `v5_6`, `v5_7`, `v5_8`).

---

## 4. Deep-Dive: Version-by-Version Breakdown

### v4: PDF Stub & Pipeline Wire-Up
- **Goal**: Full format coverage and deprecating the legacy parser.
- **Changes**:
  - Implemented `PdfStubParser` in `parsers/pdf_stub.py`.
  - Switched `api/v1/endpoints/documents.py` and `api/dependencies.py` to route through `ParserRouter`.
  - Connected chunking directly through `HybridChunker` in `core/chunker.py`.

### v5: PDF Per-Page Triage Router
- **Goal**: Stop treating all PDF pages the same way.
- **Mechanism**:
  - Opened PDFs with PyMuPDF (`fitz`).
  - Evaluated character count, image count, and table markers.
  - Routed text-only pages to `pymupdf4llm` (fast, clean markdown), complex tables to Docling, and images to SmolVLM.
  - Assembled parsed markdown pages into a merged `DoclingDocument`.

### v5.1: Page-Provenance Repair
- **Problem**: In v5, `_merge_pages()` joined all page markdown into one big string and converted it once. Docling's markdown converter created items with `prov=[]`, causing `chunk.metadata["page"]` to be `None` and `page_numbers` to be `[]`.
- **Fix**: Converted each page individually, preserved each page's items, and explicitly assigned `ProvenanceItem(page_no=page_no, ...)` to every text item.

### v5.2: VLM Pipeline Crash & Initial Heading Repair
- **Problem 1**: Pages sent to SmolVLM crashed with: `'ConvertPipelineOptions' object has no attribute 'generate_page_images'`.
- **Fix 1**: Replaced generic options with `PdfPipelineOptions(generate_page_images=True)`.
- **Problem 2**: Chunks froze on heading `"5.5 Mobility"` across 35+ chunks spanning pages 13–19, and page footers were being parsed as headings.
- **Fix 2**: Added `_repair_pdf_headings()` to identify repeated footer lines and convert headings into `SectionHeaderItem`.

### v5.3 & v5.4: The `_flatten_document` Regression & Diagnostics
- **v5.3**:
  - Added regex cleaning for raw SmolVLM generation tokens (`<image>`, `<end_of_utterance>`) and prepended `[Figure description]`.
  - Attempted to fix document traversal order by introducing `_flatten_document()`.
- **v5.4 Discovery**:
  - Real-PDF testing revealed `_flatten_document()` completely wiped out every `TableItem` from the document.
  - **Revert**: Reverted `_flatten_document()` entirely.
  - **Instrumentation**: Added Diagnostic A (printing heading labels, levels, and text) and Diagnostic B (verifying item order) via `print()` to uncover the root cause using real runtime data.

### v5.5: Heading Freeze & Tail Orphan Fixes
- **Heading Freeze Root Cause**: PyMuPDF4LLM emits top-level section headers as `# Heading`. Docling's markdown converter mapped this to a `TitleItem` (level 0). Docling's `HierarchicalChunker` locks level-0 headings as persistent context until another level-0 `TitleItem` clears it. Since all subsequent numbered headings (`7.1` to `7.9`) were parsed as `SectionHeaderItem` (level 1+), they could never replace the active title context.
- **Fix 1**: Pass 2 of `_repair_pdf_headings()` was rewritten to convert **all** headings into `SectionHeaderItem` with calculated levels based on numbering depth (`7.3` $\rightarrow$ level 2, `7.3.1` $\rightarrow$ level 3; unnumbered $\rightarrow$ level 1). No `TitleItem` survives.
- **Fix 2 (Tail Orphans)**: Gap-B synthetic chunks (heading-only slides/pages) were previously appended to the end of the chunk list. Updated `core/chunker.py` to insert synthetic chunks at their exact page position in reading order, followed by chunk renumbering.

### v5.6: Heading Refinements & Glued Text
- **Embedded Headings**: Added `_split_embedded_headings()` to detach heading lines that were accidentally concatenated into paragraph bodies (`### 7.1 Principles`).
- **Misplaced Numbers**: Added `_extract_misplaced_number()` to reattach lone numbers separated from their title strings.
- **Parent/Child Nesting**: Reclassified all-caps chapter titles (e.g., `10 CRUCIAL TRAINING PRINCIPLES`) so numerical subheadings nest underneath them rather than beside them.

### v5.7: OCR Suppression & Standalone Cleaners
- **Bitmap OCR Discovery**: Real PDFs containing full-page background images had a clean digital text layer, but Docling was running full OCR by default, overwriting clean text with garbled OCR text and breaking table headers.
- **Fix**: Added `_build_text_layer_converter(do_ocr=False)`. Pages with $\ge 40$ characters in their native text layer bypass OCR entirely.
- **`parsers/pdf_cleanup.py`**:
  - **Vocabulary Segmenter**: Dynamically builds a word frequency dictionary from the PDF text layer to split joined words (`basedon` $\rightarrow$ `based on`, `RingDips` $\rightarrow$ `Ring Dips`) without dictionary collisions.
  - **Soft Line Breaks**: Repaired broken numbers and hyphenated breaks (`15\n-\n30` $\rightarrow$ `15-30`).
  - **URL & Typo Snapping**: Cleans broken URL spaces and known corpus typos.
- **`parsers/pdf_structure.py`**:
  - Demoted CTA buttons (`Start Now`, `Get The Program`) from headings to normal body text.
  - Bound table captions (`Day 1`, `Day 2`) directly to their following tables.
- **Markdown Tables in Chunker**: Implemented `MarkdownTableSerializer` in `core/chunker.py` so tables are chunked as clean markdown tables rather than triplet format (`col, row = value`), with `repeat_table_header=True`.

### v5.8 & v5.8.1: Chunk Postprocessing & TOC Repair
- **`core/chunk_cleanup.py` & `CHUNK_POSTPROCESS`**:
  - Stripped leftover formatting tokens (`###`, `**`, `*italic*`) re-introduced by Docling serialization.
  - Dropped trailing lines in chunks that were actually the starting heading of the next chunk.
- **Table of Contents (TOC) Repair**: `_try_toc()` detects 2-column contents tables and formats them into an aligned `No. / Section / Page` table.
- **Heading Number Sequence Repair**: Corrected OCR/source sequence slips (e.g., `6.2.2 Core Circuit` following `6.5.1 Chest Circuit` renumbered to `6.5.2`).
- **Micro-Label Suppression (`v5.8.1`)**: Synthetic Gap-B heading generation now skips standalone running labels (e.g., `Calisthenics Family` $\le 3$ words, $< 40$ chars, no digits).

---

## 5. Summary of New Configuration Settings (`config.py`)

| Setting Name | Default | Purpose |
|---|---|---|
| `chunk_postprocess` | `True` | Runs `core/chunk_cleanup.py` to strip leaked markdown, heading tails, and micro-labels. |
| `pdf_v57_cleanup` | `True` | Master kill-switch for `parsers/pdf_cleanup.py` and `parsers/pdf_structure.py`. |
| `pdf_allow_ocr_on_text_pages` | `False` | When `False`, disables OCR if a native text layer has $\ge 40$ characters. |
| `pdf_enable_smolvlm_triage` | `True` | Enables SmolVLM routing for visual/image-heavy pages. |
| `pdf_text_layer_min_chars` | `40` | Minimum character threshold to qualify a page as having a valid native text layer. |
| `pdf_min_text_chars_for_text_route`| `800` | Minimum character threshold to route a page to the fast `PyMuPDF4LLM` path. |
| `pdf_debug_heading_dump` | `False` | Prints heading and traversal diagnostic traces during parsing. |

---

## 6. How to Verify & Test

Run the unit tests covering the parsing architecture updates:

```powershell
# Run using the project virtual environment
.\venv\Scripts\pytest tests/parsing_arch/v5_8 tests/parsing_arch/v5_6 tests/parsing_arch/v5_5 -v
```

All 11 unit tests in `v5_8` pass cleanly in $< 0.3$s, verifying:
- Leaked `###`, `**`, `*` cleanup and space normalization.
- Glued next-heading chunk tail dropping.
- 2-column Table of Contents normalization.
- Section header number sequence repairs.
- Micro-label identification and filtering.
