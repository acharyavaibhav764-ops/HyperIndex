# Project Context & Agent Continuity Guide

> **CRITICAL DIRECTIVE FOR ANY AI AGENT READING THIS FILE:**  
> You are collaborating with the user to pull code from `parser_v1` into `parser_docs` in logical phases and document the architecture.  
> **MANDATORY AUTO-UPDATE RULE:** After completing any phase from `pdf_doc_phases.md`, you **MUST** automatically update the **[Phase Tracker & Progress Log](#phase-tracker--progress-log)** section at the bottom of this file. Record what code was pulled, what documentation was written, and advance the active phase pointer **without waiting for the user to ask**.

---

## 1. Environment & Branch Context

- **Current Repository:** `honeywell-project`
- **Source Branch (`parser_v1`):** Contains the complete, battle-tested PDF parsing architecture (versions `v4` through `v5.8.1`, commit `8a523c4`).
- **Target Branch (`parser_docs`):** The documentation and clean integration branch. Code is pulled here in modular, capability-based phases rather than via bulk git merges.
- **Base Anchor Commit:** `2dadc28c4a152cabda6527069eb8d2a7a31cae4e` ("*fix: lazy-init DocumentConverter in DoclingParser*"). Everything after this commit represents the new PDF architecture.

---

## 2. The Core Production Files (The 6 Invariants)

Out of the 60 files modified on `parser_v1`, ignore the intermediate `.patch` files and scratch notes. Only these 6 files represent the final production architecture:

1. [`parsers/pdf_router.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/parsers/pdf_router.py):
   - Entry point: `PdfPageRouter(BaseParser)` registered in `parsers/router.py`.
   - Per-page triage (`_triage_page`) using PyMuPDF (`fitz`): detects character count, table presence, and images.
   - Routes to 3 backends: `pymupdf4llm` (text), Docling TableFormer (tables), SmolVLM (images).
   - Merges pages into a unified `DoclingDocument` and stamps `ProvenanceItem` for exact page numbers.
2. [`parsers/pdf_cleanup.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/parsers/pdf_cleanup.py):
   - Pure-Python string cleaner (no Docling dependency).
   - Dynamic vocabulary word segmenter: splits fused words (`basedon` $\rightarrow$ `based on`) using words extracted from the PDF itself.
   - Normalizes soft hyphens/linebreaks (`15\n-\n30` $\rightarrow$ `15-30`), repairs broken URLs, and strips recurring footers.
3. [`parsers/pdf_structure.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/parsers/pdf_structure.py):
   - Operates on the `DoclingDocument` AST.
   - Eliminates the **Heading Freeze**: strips `TitleItem` (level 0) and sets explicit numeric levels on `SectionHeaderItem` based on dot depth (`7.3` = depth 2).
   - Repaired 2-column Table of Contents into a structured 3-column table (`No. / Section / Page`).
   - Demotes CTA button text (`Start Now!`) from headings to normal body text.
4. [`core/chunk_cleanup.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/core/chunk_cleanup.py):
   - Pure-Python post-processing on chunk strings.
   - Strips leaked markdown syntax (`###`, `**bold**`, `*italic*`).
   - Drops trailing lines that duplicate the starting heading of the subsequent chunk.
   - Filters out standalone running logos/micro-labels (`is_micro_label`: $\le 3$ words, $< 40$ chars, no digits, e.g. `Calisthenics Family`).
5. [`core/chunker.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/core/chunker.py):
   - Uses `MarkdownTableSerializer(repeat_table_header=True)` so tables are chunked as clean markdown tables rather than triplet format (`col, row = value`).
   - Fixes **Tail Orphans**: inserts Gap-B synthetic heading chunks at their chronological page positions instead of appending them at the end.
6. [`config.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/config.py):
   - Kill-switches: `chunk_postprocess` (default `True`), `pdf_v57_cleanup` (default `True`), `enable_pdf_page_router` (default `False`/configurable).
   - Tuning thresholds: `pdf_min_text_chars_for_text_route` (800), `pdf_text_layer_min_chars` (40), `pdf_allow_ocr_on_text_pages` (False).

---

## 3. Four Core Pitfalls & Design Invariants (Must Retain)

1. **Page Provenance Loss:** Docling's markdown backend leaves `item.prov = []`. Never remove the manual `ProvenanceItem(page_no=page_no + 1)` stamping in `pdf_router._merge_pages()`.
2. **Heading Freeze:** Never allow Docling to emit a `TitleItem` (level 0) for section headings. `HierarchicalChunker` treats level 0 as an un-clearable global context. All headings must be `SectionHeaderItem` with depth $\ge 1$.
3. **Bitmap OCR Overwrite:** Docling defaults to `do_ocr=True`. On PDFs with background image layers, Docling's OCR will wipe out the clean native text layer and corrupt table headers unless `_build_text_layer_converter(do_ocr=False)` is used when text chars $\ge 40$.
4. **VLM Pipeline Options:** Always use `PdfPipelineOptions(generate_page_images=True)` for PDFs. `ConvertPipelineOptions` lacks `generate_page_images` and will crash at runtime.

---

## 4. Companion Reference Documents

- [`summary.md`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/summary.md): Comprehensive historical changelog of all commits from `2dadc28c` to `HEAD`.
- [`crux.md`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/crux.md): High-level architectural explanation and file matrix.
- [`pdf_doc_phases.md`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/pdf_doc_phases.md): The step-by-step phased pulling and documentation plan.

---

## 5. Phase Tracker & Progress Log

> **NOTE TO AGENT:** Update the status column (`[PENDING]` $\rightarrow$ `[IN PROGRESS]` $\rightarrow$ `[COMPLETED]`) and append notes to the log below as you finish each phase.

| Phase | Description | Status | Completed At | Key Files Touched |
|---|---|---|---|---|
| **Phase 1** | Router Skeleton, Registration & Page Triage | `[COMPLETED]` | 2026-10-02 | `core/parsers/pdf_router.py`, `core/parsers/router.py`, `config.py`, `docs/parser/v5_phase1_router_triage.md` |
| **Phase 2** | Fast-Text Path & Page Provenance Stamping | `[COMPLETED]` | 2026-10-02 | `core/parsers/pdf_router.py`, `docs/parser/v5_phase2_fast_text_and_provenance.md`, `tests/parsers/test_pdf_router.py` |
| **Phase 3** | Table Tier & Native Text-Layer Protection | `[PENDING]` | - | `parsers/pdf_router.py`, `config.py` |
| **Phase 4** | Visual/Image Tier (SmolVLM Captioning) | `[PENDING]` | - | `parsers/pdf_router.py`, `config.py` |
| **Phase 5** | Pre-Merge Text Sanitization (`pdf_cleanup.py`) | `[PENDING]` | - | `parsers/pdf_cleanup.py` |
| **Phase 6** | AST Structure & Heading Hierarchy (`pdf_structure.py`) | `[PENDING]` | - | `parsers/pdf_structure.py`, `parsers/pdf_router.py` |
| **Phase 7** | Downstream Chunking, Table Markdown & Chunk Cleanup | `[PENDING]` | - | `core/chunker.py`, `core/chunk_cleanup.py` |
| **Phase 8** | API Wire-Up, Full Config Reference & Verification | `[PENDING]` | - | `api/...`, `config.py`, tests |

### Active Phase Pointer
**Current Active Phase:** **Phase 3 (Table Tier & Native Text-Layer Protection)**

### Session Notes & Log
*(Agents should append brief bullet points here when completing a phase)*
- **Baseline Set (2026-10-02):** Initialized `summary.md`, `crux.md`, `pdf_doc_phases.md`, and `context.md`. Full context audited against commit `2dadc28c` through `8a523c4`.
- **Phase 1 Completed (2026-10-02):** Implemented `PdfPageRouter` skeleton (`can_handle`, `_triage_page`, `_docling_full`), registered `PdfPageRouter` in `core.parsers.router`, added PDF configuration settings to `config.py`, documented triage decision tree in `docs/parser/v5_phase1_router_triage.md`, and verified unit tests. Note: `_single_page_bytes()` was deferred to Phase 3/4 where per-page Docling/SmolVLM extraction actually requires it.
- **Phase 2 Completed (2026-10-02):** Implemented fast-text markdown extraction via `pymupdf4llm` in `_page_markdown()`, implemented isolated per-page markdown streams with explicit `ProvenanceItem` stamping across `page_doc.iterate_items()` in `_merge_pages()`, added documentation in `docs/parser/v5_phase2_fast_text_and_provenance.md`, and verified all 11 unit tests pass.
