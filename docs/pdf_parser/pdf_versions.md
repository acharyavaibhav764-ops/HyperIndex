# PDF Parser Incremental Rollout Strategy (`pdf_versions.md`)

This document defines the phased, incremental version roadmap to refactor the monolithic PDF parser from `parser_v1` into the clean, modular `core/parsers/pdf/` architecture designed in [`docs/pdf_parser_refactoring_plan.md`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/docs/pdf_parser_refactoring_plan.md).

Each version represents an independent, fully testable, and commit-ready milestone.

---

## 🛠️ Execution Protocol: Zero Branch-Switching Workflow

> [!IMPORTANT]
> **Active Implementation Branch**: `pdf_refactor` (branched from `dev`).
> **Reference Branch**: `parser_v1` (remote/local reference containing original heuristics).
> 
> **No branch switching is needed during execution**:
> 1. The developer and assistant remain strictly on the active branch **`pdf_refactor`**.
> 2. The assistant (Antigravity/Gemini) extracts, references, and adapts the original implementation heuristics directly from `parser_v1` using Git object inspection (`git show parser_v1:<path>`) without ever switching the active workspace branch.
> 3. All modules are built and verified incrementally in `core/parsers/pdf/` against `dev`'s unified pipeline configuration and test suites.
> 4. Once all versions (PDF v1.0 through v5.0) are completed, `pdf_refactor` can be merged cleanly into `dev` with **zero merge conflicts**.

---

## Rollout Overview

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        PDF Refactoring Roadmap                         │
├───────────────┬──────────────────────────┬─────────────────────────────┤
│ Version       │ Focus                    │ Scope & Key Deliverables    │
├───────────────┼──────────────────────────┼─────────────────────────────┤
│ PDF v1.0      │ Foundation & Package     │ core/parsers/pdf/, BaseParser│
│               │ Architecture             │ router integration, stub    │
├───────────────┼──────────────────────────┼─────────────────────────────┤
│ PDF v2.0      │ Triage & Multi-Backend   │ triage.py, backends.py,     │
│               │ Extraction Engine        │ provenance stamping         │
├───────────────┼──────────────────────────┼─────────────────────────────┤
│ PDF v3.0      │ Document Normalization   │ structure.py, cleanup.py,   │
│               │ & Structural Repairs     │ glyphs.py                   │
├───────────────┼──────────────────────────┼─────────────────────────────┤
│ PDF v4.0      │ High-Fidelity Domain     │ cellmarks.py, figures.py,   │
│               │ Transforms               │ coverage.py                 │
├───────────────┼──────────────────────────┼─────────────────────────────┤
│ PDF v5.0      │ Core Decoupling &        │ Purge chunker/retriever PDF │
│               │ Repository Cleanup       │ hacks, delete root parsers/ │
└───────────────┴──────────────────────────┴─────────────────────────────┘
```

---

## Version Breakdown

### 🔷 PDF v1.0: Foundation & Package Architecture
**Goal**: Establish the clean package structure inside `core/parsers/pdf/`, register `PdfParser` in `core.parsers.ParserRouter`, and create a safe baseline that matches `DoclingParser` / `TextParser`.

* **Components Touched / Created**:
  * `core/parsers/pdf/__init__.py` [NEW]
  * `core/parsers/pdf/parser.py` [NEW]
  * `core/parsers/router.py` [UPDATE: Register `PdfParser`]
  * `core/parsers/__init__.py` [UPDATE: Export `PdfParser`]
  * `tests/parsers/test_pdf_parser_base.py` [NEW]
* **Deliverables**:
  1. Define `class PdfParser(BaseParser)` with `SUPPORTED_EXTENSIONS = frozenset({".pdf"})`.
  2. Implement fallback baseline parsing using vanilla Docling `DocumentConverter(allowed_formats=[InputFormat.PDF])`.
  3. Wire into `ParserRouter` so `.pdf` is officially handled by `core/parsers/` without throwing `UnsupportedFileError`.
* **Testing & Verification**:
  * Verify `router.get_parser("sample.pdf")` returns `PdfParser`.
  * Verify `router.parse(pdf_bytes, "sample.pdf")` produces a valid `DoclingDocument`.
* **Why it can be pushed independently**:
  * Zero risk: establishes the new package, registration, and interface contracts without introducing complex triage or regexes yet.

---

### 🔷 PDF v2.0: Triage & Multi-Backend Extraction Engine
**Goal**: Implement the per-page triage classification and modular extraction adapters (PyMuPDF4LLM + Docling Table + SmolVLM) with bulletproof page provenance.

* **Components Touched / Created**:
  * `core/parsers/pdf/triage.py` [NEW]
  * `core/parsers/pdf/backends.py` [NEW]
  * `core/parsers/pdf/parser.py` [UPDATE: Integrate triage and backend dispatch]
  * `tests/parsers/test_pdf_triage.py` [NEW]
  * `tests/parsers/test_pdf_backends.py` [NEW]
* **Deliverables**:
  1. `PageTriager` in `triage.py`:
     - Inspects PyMuPDF page descriptors (`page.find_tables()`, `page.get_images()`, text density).
     - Emits routes: `PAGE_ROUTE.TEXT`, `PAGE_ROUTE.TABLE`, `PAGE_ROUTE.IMAGE`.
  2. Extraction backends in `backends.py`:
     - `PyMuPdfBackend`: Fast markdown extraction for text pages.
     - `DoclingBackend`: Table structure extraction for table pages.
     - `VlmBackend`: Lazy SmolVLM picture descriptions.
  3. Single-page document merger that guarantees every text, table, and picture item has an accurate `ProvenanceItem(page_no=...)`.
* **Testing & Verification**:
  * Unit tests verifying correct route assignment for text-heavy vs table-heavy PDF pages.
  * Integration tests asserting page numbers are preserved on all items in the merged `DoclingDocument`.
* **Why it can be pushed independently**:
  * Delivers the core speed and accuracy improvements of multi-backend routing with clean provenance.

---

### 🔷 PDF v3.0: Document Normalization & Structural Repairs
**Goal**: Integrate heading freeze repairs, section hierarchy normalization, Wingdings font translation, and text cleanup into modular transform passes.

* **Components Touched / Created**:
  * `core/parsers/pdf/transforms/structure.py` [NEW]
  * `core/parsers/pdf/transforms/cleanup.py` [NEW]
  * `core/parsers/pdf/transforms/glyphs.py` [NEW]
  * `core/parsers/pdf/postprocess.py` [NEW: Pipeline runner]
  * `core/parsers/pdf/parser.py` [UPDATE: Hook post-process pipeline]
  * `tests/parsers/test_pdf_structure.py` [NEW]
* **Deliverables**:
  1. `StructureTransform`:
     - Converts PyMuPDF `# H1` page-level title items to deterministic `SectionHeaderItem` levels (eliminates the heading-freeze bug in `HybridChunker`).
     - Detects and tags Table of Contents (`[TOC]`) structures.
     - Dotted numbered section recognition (`"7.6 Specificity"`).
  2. `CleanupTransform`:
     - Scrubs SmolVLM completion artifacts (e.g. `<end_of_utteranc>`).
     - Filters out boilerplate running headers, footers, and micro-labels.
  3. `GlyphsTransform`:
     - Translates Wingdings, Dingbats, and symbol bullets into clean Unicode equivalents.
* **Testing & Verification**:
  * Unit tests validating that subsection headings on later pages correctly clear the heading stack.
  * Regression tests confirming no raw model completion tokens appear in output text.
* **Why it can be pushed independently**:
  * Resolves all AST and markdown structure bugs without needing the heavier raster image heuristics yet.

---

### 🔷 PDF v4.0: High-Fidelity Domain Transforms (Cellmarks, Figures & Coverage)
**Goal**: Bring in the advanced visual and text recovery features (table cell tick marks, figure cards, and dropped text recovery).

* **Components Touched / Created**:
  * `core/parsers/pdf/transforms/cellmarks.py` [NEW]
  * `core/parsers/pdf/transforms/figures.py` [NEW]
  * `core/parsers/pdf/transforms/coverage.py` [NEW]
  * `core/parsers/pdf/postprocess.py` [UPDATE: Add visual and coverage passes]
  * `tests/parsers/test_pdf_cellmarks.py` [NEW]
  * `tests/parsers/test_pdf_coverage.py` [NEW]
* **Deliverables**:
  1. `CellmarksTransform`:
     - Detects inline raster image checkmarks/crossmarks inside table cell bounding boxes and converts them into readable text (`"Yes"`, `"No"`).
  2. `FiguresTransform`:
     - Extracts standalone figure cards linking images, captions, and bounding boxes.
  3. `CoverageTransform`:
     - Compares raw PyMuPDF text against Docling parsed text, recovering any dropped text runs inside `[Recovered text]` blocks.
* **Testing & Verification**:
  * Verify tables with green tick graphics produce markdown cells containing `"Yes"`.
  * Verify dropped text (e.g. warnings, side notes) is recovered in output chunks.
* **Why it can be pushed independently**:
  * The PDF parser now has 100% feature parity with the most advanced behavior of `parser_v1`, but fully contained in clean modules.

---

### 🔷 PDF v5.0: Core Decoupling & Repository Cleanup
**Goal**: Purge all hacky PDF special-casing from `core/chunker.py` and `core/retriever.py`, and delete all obsolete files and patch scripts.

* **Components Touched / Deleted**:
  * `core/chunker.py` [CLEANUP: Remove PDF file-extension branches]
  * `core/retriever.py` [CLEANUP: Generalize metadata filters]
  * `core/chunk_cleanup.py` [REMOVE or merge into parser transforms]
  * Top-level `parsers/` directory [DELETE]
  * Obsolete patch files (`docs/v5_*.patch`, etc.) [DELETE]
  * `tests/parsing_arch/` [MIGRATE to standard `tests/parsers/`]
* **Deliverables**:
  1. Clean `core/chunker.py`: Chunker operates purely on `DoclingDocument` items without caring whether the source file was `.pdf`, `.docx`, or `.txt`.
  2. Clean repository: zero duplicate files, zero loose patch files in `docs/`, 100% adherence to `core/parsers/` standard.
  3. Full integration test suite passing on all document formats (`.pdf`, `.docx`, `.pptx`, `.doc`, `.ppt`, `.txt`, `.md`).
* **Why it can be pushed independently**:
  * Completes the architectural cleanup, leaving the repository production-grade and maintainable.

