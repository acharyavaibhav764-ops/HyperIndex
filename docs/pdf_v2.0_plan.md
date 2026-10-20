# PDF Parser Implementation Plan: Version 2.0 (Triage & Multi-Backend Extraction Engine)

## Executive Summary
PDF v2.0 implements the core speed and accuracy engine of the PDF parser: **per-page triage routing** and **modular extraction backends** with **strict single-page provenance**.

Instead of treating an entire PDF as a uniform document, v2.0 inspects each page and routes it to the optimal extractor:
- **Text-heavy pages** $\rightarrow$ `PyMuPdfBackend` (PyMuPDF4LLM: fast, high-quality markdown).
- **Table-bearing pages** $\rightarrow$ `DoclingBackend` (Docling: structural table extraction).
- **Image/diagram pages** $\rightarrow$ `VlmBackend` (SmolVLM / Docling VLM pipeline: vision descriptions).
- **Dual Table + Image pages** $\rightarrow$ Docling table markdown combined with VLM figure descriptions.

Each page is extracted in isolation and merged into a single unified `DoclingDocument` with **guaranteed `ProvenanceItem(page_no=...)` stamping** across all item types (texts, tables, pictures).

---

## 1. Architectural Scope & Invariants

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        PDF v2.0 Scope Boundary                         │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Active Working Branch                                               │
│    └── pdf_refactor (branch remains pdf_refactor, 0 branch switches)   │
│                                                                        │
│ 2. Reference Source (Via git show parser_v1:...)                       │
│    └── Adapt battle-tested triage heuristics and provenance fixes      │
│                                                                        │
│ 3. Modules to Create inside core/parsers/pdf/                          │
│    ├── triage.py (Page classification enum & heuristics)               │
│    └── backends.py (PyMuPDF4LLM, Docling Table, SmolVLM adapters)      │
│                                                                        │
│ 4. Module to Update                                                    │
│    └── parser.py (Integrate triager, backend extraction, & page merger)│
│                                                                        │
│ 5. System Invariants                                                   │
│    ├── Zero changes to core/retriever.py, core/chunker.py, uploader.py │
│    ├── Single-page byte slicing for true isolation                     │
│    └── Stamped ProvenanceItem on texts, tables, and pictures           │
│                                                                        │
│ 6. Automated Unit Tests                                                │
│    ├── tests/parsers/test_pdf_triage.py                                │
│    └── tests/parsers/test_pdf_backends.py                              │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Implementation Deliverables

### Phase 1: Page Triage Classifier (`core/parsers/pdf/triage.py`)

* **Enum**:
  ```python
  class PageRoute(str, Enum):
      TEXT = "text"
      TABLE = "table"
      IMAGE = "image"
  ```
* **Class**: `PageTriager`
* **Configuration**:
  - `min_text_chars_for_text_route: int = 200`
  - Tunable via `pipeline_config.pipeline_settings`.
* **Heuristics (`triage_page(page: fitz.Page) -> list[PageRoute]`)**:
  1. **Table Detection**: `page.find_tables().tables` is non-empty $\rightarrow$ append `PageRoute.TABLE`.
  2. **Image Detection**: `page.get_images()` is non-empty AND `len(page.get_text().strip()) < min_text_chars` $\rightarrow$ append `PageRoute.IMAGE`.
  3. **Default**: If neither table nor image, return `[PageRoute.TEXT]`.
  4. **Dual Capability**: Allows returning `[PageRoute.TABLE, PageRoute.IMAGE]` simultaneously for rich pages.

---

### Phase 2: Extraction Backends & Page Merger (`core/parsers/pdf/backends.py`)

* **Single-Page Slicer**:
  ```python
  def single_page_bytes(pdf: fitz.Document, page_no: int) -> bytes:
      """Extract page_no as an isolated single-page PDF byte buffer."""
  ```
* **Extraction Backends**:
  1. **`PyMuPdfBackend`**:
     - Calls `pymupdf4llm.to_markdown(pdf, pages=[page_no])`.
     - Fast markdown extraction with header/footer suppression.
  2. **`DoclingTableBackend`**:
     - Converts single-page bytes using Docling `DocumentConverter(allowed_formats=[InputFormat.PDF])`.
     - Returns rendered markdown or intermediate document.
  3. **`VlmPictureBackend`**:
     - Runs single-page bytes through Docling VLM pipeline (`SmolVLM`).
     - Includes `extract_picture_descriptions_only(page_bytes)` for dual table+image pages so table text is not duplicated.
* **Document Page Merger (`merge_pages_to_docling`)**:
  - Converts per-page markdown back into a unified `DoclingDocument`.
  - **Critical Provenance Stamping (Fixing v5.1/v5.3 bug)**:
    Iterates through all items (`page_doc.iterate_items()`) and stamps:
    ```python
    prov = ProvenanceItem(
        page_no=page_no,  # 1-indexed for human readability and chunk metadata
        bbox=BoundingBox(l=0, t=0, r=0, b=0),
        charspan=(0, 0),
    )
    if hasattr(item, "prov"):
        item.prov = [prov]
    ```
    Stamps texts, tables, and picture items alike so table chunks never become orphaned tail chunks.

---

### Phase 3: Update `PdfParser` in `core/parsers/pdf/parser.py`

* Update `PdfParser.parse(file_bytes, filename)`:
  1. Open document with PyMuPDF: `doc = fitz.open(stream=file_bytes, filetype="pdf")`.
  2. Triage each page: `routes = [self.triager.triage_page(page) for page in doc]`.
  3. Extract markdown per page based on triage route.
  4. Merge pages into a unified `DoclingDocument` with accurate `ProvenanceItem(page_no=...)`.
  5. Close PyMuPDF document cleanly.

---

### Phase 4: Unit Testing & Verification

1. **`tests/parsers/test_pdf_triage.py`**:
   - `test_triage_pure_text_page`: Synthesizes text-only PDF $\rightarrow$ verifies `[PageRoute.TEXT]`.
   - `test_triage_table_page`: Synthesizes table graphic/lines $\rightarrow$ verifies `[PageRoute.TABLE]`.
   - `test_triage_image_page`: Embeds image with low text count $\rightarrow$ verifies `[PageRoute.IMAGE]`.
2. **`tests/parsers/test_pdf_backends.py`**:
   - `test_single_page_slicing`: Asserts sliced bytes open as a 1-page PDF.
   - `test_page_provenance_stamped`: Parses a multi-page PDF and asserts that items on page 1 have `page_no=1`, and items on page 2 have `page_no=2`.
   - `test_dual_table_image_merging`: Asserts table content and image captions co-exist without text duplication.

---

## 3. Verification Commands

```powershell
# 1. Run v2.0 unit tests
.\venv\Scripts\python.exe -m unittest tests/parsers/test_pdf_triage.py
.\venv\Scripts\python.exe -m unittest tests/parsers/test_pdf_backends.py

# 2. Run full parser suite to ensure zero regressions
.\venv\Scripts\python.exe -m unittest discover -s tests/parsers

# 3. Check git diff to ensure core/ remains clean
git diff core/
```

---

## 4. Definition of Done
- [ ] `core/parsers/pdf/triage.py` implements clean per-page classification.
- [ ] `core/parsers/pdf/backends.py` encapsulates PyMuPDF, Docling Table, and VLM extraction.
- [ ] Multi-page PDFs correctly retain `ProvenanceItem(page_no=...)` on all text and table items.
- [ ] All new and existing parser unit tests pass with 100% success rate.
- [ ] `core/` infrastructure (`chunker.py`, `retriever.py`, `uploader.py`) remains 100% untouched.

