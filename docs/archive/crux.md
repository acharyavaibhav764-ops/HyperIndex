# The Crux: What You Need to Know for `parser_docs`

This document cuts through the noise of the ~10 micro-patches (v5.1 through v5.8.1) and outlines **the core architectural reality**, the **essential files to pull**, and the **minimum concepts you need to understand** before writing documentation in `parser_docs`.

---

## 1. The Big Picture (What actually was built)

Between commit `2dadc28c` and `HEAD`, the parsing system shifted from a monolithic parser to a **modular, multi-tiered document triage and self-healing extraction pipeline**:

```
                       Input File (.pdf, .docx, .pptx, etc.)
                                         │
                                         ▼
                      parsers/router.py (ParserRouter)
                                         │
                        ┌────────────────┴────────────────┐
                        │ (.pdf)                          │ (other formats)
                        ▼                                 ▼
         parsers/pdf_router.py (PdfPageRouter)     parsers/docling_parser.py
                        │                          parsers/text_parser.py
                        │                          parsers/libreoffice_parser.py
                        ▼
            Stage 1: Page-by-Page Triage
            ┌───────────────┬─────────────────┬──────────────────┐
            ▼               ▼                 ▼                  ▼
       pymupdf4llm       Docling           SmolVLM            Docling
       (Fast Text)    (Tables Only)    (Visual/Images)     (Text-layer fallback)
            │               │                 │                  │
            └───────────────┴────────┬────────┴──────────────────┘
                                     │
                                     ▼
            Stage 2: Text Normalization (parsers/pdf_cleanup.py)
            (Lost-space segmenter, soft hyphens, URLs, footer strip)
                                     │
                                     ▼
            Stage 3: Page Merge & Provenance Stamping
            (Stamps page_no on every text, table, and picture item)
                                     │
                                     ▼
            Stage 4: Structural Repair (parsers/pdf_structure.py)
            (Normalize heading levels, demote CTAs, fix TOCs, bind captions)
                                     │
                                     ▼
                       Unified DoclingDocument
                                     │
                                     ▼
            Stage 5: Intelligent Chunking (core/chunker.py)
            (Markdown tables + post-cleanup + in-order synthetic headings)
```

---

## 2. File Triage: What to Pull vs. What to Ignore

You do **not** need to document the 60 files changed in git diff. 70% of those files were intermediate patches, diagnostics, and test iterations.

### Group A: The Core Source Files (MUST UNDERSTAND & PULL)

These 6 files are the actual production architecture:

| File | What it does | What to document |
|---|---|---|
| [`parsers/pdf_router.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/parsers/pdf_router.py) | **The PDF Orchestrator**: Replaces the old stub. Inspects each page with PyMuPDF (`fitz`), triages pages into 3 tiers (Text, Table, Image), merges them, and stamps page provenance. | Document the triage algorithm, why 3 tiers exist, and how pages are merged into one `DoclingDocument`. |
| [`parsers/pdf_cleanup.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/parsers/pdf_cleanup.py) | **Text Sanitizer**: Pure-Python string cleaning. Dynamically builds a vocabulary from the PDF text layer to fix joined words (`basedon` $\rightarrow$ `based on`), fixes soft hyphens (`15\n-\n30`), strips recurring footers, and fixes URLs. | Document the dynamic vocabulary segmenter and text-cleaning rules. |
| [`parsers/pdf_structure.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/parsers/pdf_structure.py) | **Document Structure Repair**: Operates on the `DoclingDocument` AST. Demotes CTA buttons from headings to body text, fixes 2-column TOCs, and renumbers broken heading sequences. | Document how heading hierarchy and table captions are normalized before chunking. |
| [`core/chunk_cleanup.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/core/chunk_cleanup.py) | **Chunk Sanitizer**: Pure-Python post-processor. Strips leaked markdown syntax (`###`, `**`, `*italic*`), drops trailing lines that belong to the next heading, and drops micro-labels. | Document how chunk strings are sanitized before storage/embedding. |
| [`core/chunker.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/core/chunker.py) | **Chunking Engine**: Serializes tables as clean markdown (`MarkdownTableSerializer`), inserts Gap-B synthetic headings at their chronological page positions, and applies chunk cleanup. | Document table markdown serialization and page-order chunk preservation. |
| [`config.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/config.py) | **Settings**: Holds feature flags (`chunk_postprocess`, `pdf_v57_cleanup`, `pdf_allow_ocr_on_text_pages`) and tuning thresholds. | Document the configuration flags and how they act as kill-switches. |

### Group B: The Pipeline Wiring Files (QUICK PULL)
- [`parsers/router.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/parsers/router.py): Registers `PdfPageRouter` alongside other parsers.
- [`api/v1/endpoints/documents.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/api/v1/endpoints/documents.py) & [`api/dependencies.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/api/dependencies.py): Connects FastAPI upload routes to `ParserRouter`.

### Group C: Noise / Intermediate Files (DO NOT FOCUS ON)
Ignore these when writing high-level documentation:
- `docs/v5_*.patch`: Temporary patch diffs used during iterative test cycles.
- `docs/v5_*_plan.md`: Step-by-step developer scratchpads. (All their final outcomes are captured in `summary.md`).
- `tests/parsing_arch/v5_1/` through `v5_7/`: Historical test fixtures. Only `tests/parsing_arch/v5_8/test_v58_repairs.py` reflects the final state.

---

## 3. The 4 Essential Concepts You Must Understand

When documenting in `parser_docs`, you only need to be able to explain these four design decisions:

### Concept 1: Why Per-Page Triage? (The "Tiered Routing" Idea)
- **The Problem**: Running heavy vision models (SmolVLM) or deep OCR on every page of a 100-page document is unacceptably slow (~10–30s/page) and often degrades text quality. Conversely, naive text extractors break completely on complex tables or diagrams.
- **The Solution**: 
  - If a page has $>800$ characters and no complex tables/images $\rightarrow$ route to **PyMuPDF4LLM** ($\sim 50$ms/page, preserves layout and bolding).
  - If a page has tables $\rightarrow$ route to **Docling Table Former** (accurately recovers columns and cells).
  - If a page has diagrams/pictures and text $<800$ chars $\rightarrow$ route to **SmolVLM** (generates descriptive figure captions).

### Concept 2: Page Provenance Stamping
- **The Problem**: When markdown text from individual pages is joined and parsed, Docling assigns empty provenance (`prov=[]`), meaning every chunk loses its page number (`page: None`).
- **The Solution**: Each page is parsed independently; during the merge step in `pdf_router.py`, `ProvenanceItem(page_no=page_no)` is stamped on every text item, table, and image. This guarantees `chunk.metadata["page"]` and `chunk.metadata["page_numbers"]` are always accurate.

### Concept 3: The Heading Hierarchy & "Freeze" Prevention
- **The Problem**: In Docling, `TitleItem` is level 0. Once a level-0 title is encountered, Docling's `HierarchicalChunker` keeps that title active across all subsequent chunks until another level-0 title appears. Markdown headings like `# Section` produced `TitleItem`s that locked headings like `"5.5 Mobility"` across 35 unrelated chunks.
- **The Solution**: `pdf_structure.py` and `pdf_router.py` strip all `TitleItem`s and convert them into `SectionHeaderItem` with explicit numerical levels based on dot depth (`7` $\rightarrow$ 1, `7.3` $\rightarrow$ 2, `7.3.1` $\rightarrow$ 3). Unnumbered headings default to level 1. Context now resets cleanly across sections.

### Concept 4: Three-Stage Sanitization
1. **Stage 1 (Raw Markdown)**: `parsers/pdf_cleanup.py` runs before Docling sees the markdown. Uses document vocabulary to segment words (`basedon` $\rightarrow$ `based on`), removes soft hyphens, and drops repeating running footers.
2. **Stage 2 (Docling Tree)**: `parsers/pdf_structure.py` runs on the parsed document AST. Replaces 2-column TOCs, demotes buttons/promo codes (`Start Now!`), and links table captions.
3. **Stage 3 (Chunk Strings)**: `core/chunk_cleanup.py` runs on the final text chunks. Cleans stray `###` or `**`, removes heading lines mistakenly glued to the bottom of previous chunks, and discards single-line brand logos (`Calisthenics Family`).

---

## 4. Suggested Documentation Structure for `parser_docs`

When you switch to your `parser_docs` branch, organize your documentation around these sections:

1. **Architecture Overview**: The Triage Pipeline diagram and why the multi-engine approach was adopted.
2. **Supported Formats & Routing**:
   - Office docs (.docx, .pptx) $\rightarrow$ `DoclingParser`
   - Legacy office (.doc, .ppt) $\rightarrow$ `LibreOfficeConverter`
   - Plain text / markdown (.txt, .md) $\rightarrow$ `TextParser`
   - PDFs (.pdf) $\rightarrow$ `PdfPageRouter`
3. **PDF Ingestion Deep-Dive**:
   - Page triage logic and thresholds.
   - Text vs. Table vs. Image paths.
   - Provenance stamping mechanics.
4. **Data Normalization & Self-Healing Pipeline**:
   - Text level (`pdf_cleanup.py`).
   - Structure level (`pdf_structure.py`).
   - Chunk level (`chunk_cleanup.py`).
5. **Chunking & Metadata Output**:
   - `HybridChunker` with Markdown table formatting.
   - Page-accurate synthetic heading chunks.
   - Metadata schema (`file_id`, `filename`, `page`, `page_numbers`, `chunk_index`, `headings`).
6. **Configuration Reference**: Table of all `Settings` toggles in `config.py`.

---

## 5. How to Bring These Changes Into `parser_docs`

When you are ready to update `parser_docs`:

```powershell
# 1. Switch to your parser_docs branch
git checkout parser_docs

# 2. Pull the clean core files directly from parser_v1:
git checkout parser_v1 -- parsers/pdf_router.py parsers/pdf_cleanup.py parsers/pdf_structure.py core/chunk_cleanup.py core/chunker.py config.py parsers/router.py

# 3. Pull the summaries for reference:
git checkout parser_v1 -- summary.md crux.md
```

This brings over all the production code and reference guides without cluttering your branch with the dozens of temporary `.patch` and scratch files.
