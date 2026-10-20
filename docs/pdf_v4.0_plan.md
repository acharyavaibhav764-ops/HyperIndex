# PDF Parser Implementation Plan: Version 4.0 (High-Fidelity Domain Transforms)

## Executive Summary
PDF v4.0 completes the transformation pipeline by adding advanced visual and text recovery heuristics ported and modularized from `parser_v1`:
1. **Table Availability Marks (`cellmarks.py`)**: Honeywell manuals frequently contain feature tables where availability is indicated by tiny inline raster checkmarks/ticks (rather than text). In raw Docling or PyMuPDF extraction, these cells appear blank or contain unmapped icons. `cellmarks.py` uses bounding-box collision detection between table cells and image centres, converting checkmark icons into readable `"Yes"` / `"No"` values.
2. **Deterministic Figure Cards (`figures.py`)**: Builds structured figure description blocks linking picture items, labels, and diagram metadata without requiring heavy, expensive vision model inference.
3. **Text Coverage Safety Net (`coverage.py`)**: Compares the raw PyMuPDF text layer against the extracted/cleaned markdown per page. Any genuine body text lines dropped by upstream Docling or OCR are automatically recovered and appended inside a clean `[Recovered text]` section.

---

## 1. Architectural Scope & Invariants

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        PDF v4.0 Scope Boundary                         │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Active Working Branch                                               │
│    └── pdf_refactor (Strictly on pdf_refactor, zero branch switching)   │
│                                                                        │
│ 2. Modules to Create inside core/parsers/pdf/transforms/               │
│    ├── cellmarks.py (Table cell tick-mark image -> Yes/No conversion)  │
│    ├── figures.py (Deterministic figure card builder)                  │
│    └── coverage.py (Raw PyMuPDF text diffing & lost text recovery)     │
│                                                                        │
│ 3. Pipeline Integration                                                │
│    ├── postprocess.py (Register cellmarks, figures, and coverage passes│
│    └── parser.py (Pass fitz.Page and raw text context to pipeline)     │
│                                                                        │
│ 4. System Invariants                                                   │
│    ├── Preservation of existing comments and docstrings verbatim       │
│    ├── Zero modifications to core/chunker.py, retriever.py, uploader.py│
│    └── Fully stateless transform functions                            │
│                                                                        │
│ 5. Automated Tests                                                     │
│    ├── tests/parsers/test_pdf_cellmarks.py                             │
│    ├── tests/parsers/test_pdf_figures.py                               │
│    └── tests/parsers/test_pdf_coverage.py                              │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Implementation Deliverables

### Phase 1: Table Availability Marks (`core/parsers/pdf/transforms/cellmarks.py`)
Ported and modularized from `parser_v1:parsers/pdf_cellmarks.py`:
* **Core Heuristics**:
  - `scan_legend(page_texts: list[str]) -> dict | None`: Identifies whether the document defines availability legends (e.g. `"[tick] = available"` $\rightarrow$ `{"tick": "Yes", "dots": "No"}`).
  - Bounding Box Collision (`_bbox_to_tuple`, `_flip_if_needed`, `_inside`): Maps the coordinates of inline raster images to Docling table cell bounding boxes.
  - Image Hashing: Hashes recurring inline graphics (`xref == 0` or small raster images) so repeated ticks in feature tables are clustered reliably.
  - `inject_marks(doc: DoclingDocument, page_fitz: fitz.Page, page_no: int, legend: dict | None = None)`:
    - Iterates over `doc.tables`.
    - Locates cells containing tick images and updates the cell text to `"Yes"` (or `"No"` for crossmarks).
    - Ensures the updated text survives Docling's markdown serialization.

---

### Phase 2: Deterministic Figure Cards (`core/parsers/pdf/transforms/figures.py`)
Ported and modularized from `parser_v1:parsers/pdf_figures.py`:
* **Core Heuristics**:
  - `build_figure_card(picture: PictureItem) -> str`: Builds clean caption text for figures without triggering VLM inference.
  - `_has_repeated_ngram` and `_zlib_ratio`: Filters out garbage or hallucinated repetitive captions.
  - `inject_figure_cards(doc: DoclingDocument)`:
    - Injects figure captions as structured `DocItemLabel.CAPTION` items linked to their parent `PictureItem`.

---

### Phase 3: Text Coverage Safety Net (`core/parsers/pdf/transforms/coverage.py`)
Ported and modularized from `parser_v1:parsers/pdf_coverage.py`:
* **Core Heuristics**:
  - `check_page(md: str, raw_text: str, running_lines: set[str], recall_min: float = 0.85) -> str`:
    - Normalizes both extracted markdown and raw PyMuPDF text lines.
    - Matches raw lines against markdown lines using `SequenceMatcher`.
    - Skips table of contents dot-leader lines (`..... 12`).
    - Recovers un-extracted body text by appending:
      ```markdown
      [Recovered text]
      <missing line 1>
      <missing line 2>
      ```
    - Prevents crucial specifications, side-notes, or warnings from being silently lost during extraction.

---

### Phase 4: Post-Processing Pipeline & Parser Integration
* **`core/parsers/pdf/postprocess.py`**:
  - Add `process_coverage(markdowns: list[str], raw_texts: list[str]) -> list[str]`.
  - Add `process_visuals(doc: DoclingDocument, pdf: fitz.Document)` to invoke `inject_marks` on each page's tables and `inject_figure_cards`.
* **`core/parsers/pdf/parser.py`**:
  - Preserves all existing comments and docstrings verbatim.
  - Passes `page.get_text()` strings to `post_processor.process_coverage()`.
  - Passes `pdf` to `post_processor.process_visuals()` before returning the `DoclingDocument`.

---

### Phase 5: Automated Unit Tests
* **`tests/parsers/test_pdf_cellmarks.py`**:
  - Tests table cell tick detection and text conversion.
* **`tests/parsers/test_pdf_figures.py`**:
  - Tests deterministic figure card formatting and n-gram deduplication.
* **`tests/parsers/test_pdf_coverage.py`**:
  - Tests missing text line recovery: asserts that text present in raw text but omitted from markdown is appended as `[Recovered text]`.

---

## 3. Verification Commands

```powershell
# 1. Run v4.0 unit tests
.\venv\Scripts\python.exe -m unittest tests/parsers/test_pdf_cellmarks.py
.\venv\Scripts\python.exe -m unittest tests/parsers/test_pdf_figures.py
.\venv\Scripts\python.exe -m unittest tests/parsers/test_pdf_coverage.py

# 2. Run full parser test suite
.\venv\Scripts\python.exe -m unittest discover -s tests/parsers

# 3. Check git diff to verify comment preservation and clean core/
git diff core/chunker.py core/retriever.py core/uploader.py
```

---

## 4. Definition of Done
- [ ] `cellmarks.py`, `figures.py`, and `coverage.py` added to `core/parsers/pdf/transforms/`.
- [ ] Pipeline runs coverage recovery and visual/cellmark enrichment.
- [ ] All existing comments and docstrings preserved verbatim.
- [ ] Zero changes to `core/chunker.py`, `core/retriever.py`, or `core/uploader.py`.
- [ ] All parser unit tests pass with 100% success rate.

