# PDF Parser Implementation Plan: Version 1.0 (Foundation & Package Architecture)

## Executive Summary
PDF v1.0 establishes the modular package architecture for PDF handling inside `core/parsers/pdf/`, implementing `PdfParser` as a first-class subclass of `BaseParser`. It wires PDF parsing cleanly into `ParserRouter` alongside `TextParser`, `DoclingParser`, and `LibreOfficeConverter`.

In v1.0, `PdfParser` provides a robust, lazy-loaded baseline using Docling's `DocumentConverter(allowed_formats=[InputFormat.PDF])`. This guarantees that `.pdf` files are immediately supported by the system architecture with 0 risk, setting the stable foundation for per-page triage (v2.0) and domain transforms (v3.0–v4.0).

---

## 1. Architectural Scope & Invariants

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        PDF v1.0 Scope Boundary                         │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Active Working Branch                                               │
│    └── pdf_refactor (clean baseline off dev)                           │
│                                                                        │
│ 2. Package Creation                                                    │
│    ├── core/parsers/pdf/__init__.py                                    │
│    └── core/parsers/pdf/parser.py                                      │
│                                                                        │
│ 3. Router Integration                                                  │
│    ├── core/parsers/router.py (Register PdfParser in ParserRouter)     │
│    └── core/parsers/__init__.py (Re-export PdfParser)                  │
│                                                                        │
│ 4. System Invariants                                                   │
│    ├── Zero changes to core/retriever.py, core/uploader.py             │
│    ├── Zero changes to core/chunker.py                                 │
│    └── Zero circular imports between core/parsers/ and core/           │
│                                                                        │
│ 5. Automated Tests                                                     │
│    └── tests/parsers/test_pdf_parser_v1.py                             │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Implementation Deliverables

### Phase 1: Package Structure & Subsystem Module
Create `core/parsers/pdf/`:

#### 1. `core/parsers/pdf/parser.py`
* **Class**: `PdfParser(BaseParser)`
* **Attributes**:
  - `SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".pdf"})`
  - `_converter: DocumentConverter | None = None` (lazy initialization to avoid startup delay)
* **Methods**:
  - `can_handle(ext: str) -> bool`: Returns `True` if `ext.lower() in self.SUPPORTED_EXTENSIONS`.
  - `parse(file_bytes: bytes, filename: str, **kwargs) -> DoclingDocument`:
    - Wraps `file_bytes` in `DocumentStream(name=filename, stream=io.BytesIO(file_bytes))`.
    - Lazily instantiates `DocumentConverter(allowed_formats=[InputFormat.PDF])` if not already initialized.
    - Executes `self._converter.convert(stream)`.
    - Returns `conv_result.document`.

#### 2. `core/parsers/pdf/__init__.py`
* Clean public exports:
  ```python
  from .parser import PdfParser

  __all__ = ["PdfParser"]
  ```

---

### Phase 2: Router Integration & Global Re-exports

#### 1. `core/parsers/router.py`
* Import `PdfParser` from `.pdf`.
* In `ParserRouter.__init__()`:
  ```python
  self.register(TextParser())           # .txt / .md
  self.register(DoclingParser())        # .docx / .pptx
  self.register(LibreOfficeConverter()) # .doc / .ppt
  self.register(PdfParser())            # .pdf [NEW]
  ```

#### 2. `core/parsers/__init__.py`
* Add `"PdfParser"` to imports and `__all__`.

---

### Phase 3: Unit Testing & Verification

* **Test File**: `tests/parsers/test_pdf_parser_v1.py`
* **Test Cases**:
  1. `test_can_handle_pdf`: Asserts `PdfParser().can_handle(".pdf")` and `can_handle(".PDF")` return `True`.
  2. `test_can_handle_non_pdf`: Asserts `.docx`, `.txt`, `.png` return `False`.
  3. `test_router_registration`: Asserts `ParserRouter().get_parser("report.pdf")` returns an instance of `PdfParser`.
  4. `test_router_supported_extensions`: Asserts `".pdf"` is included in `router._supported_extensions()`.
  5. `test_parse_dummy_pdf`:
     - Creates a minimal, valid in-memory PDF using PyMuPDF (`fitz.open()`, `page.insert_text((50, 50), "Honeywell Test")`).
     - Passes bytes to `PdfParser.parse(bytes, "dummy.pdf")`.
     - Asserts result is an instance of `DoclingDocument` with matching text content.

---

## 3. Verification Commands

```powershell
# 1. Run unit tests for PDF v1.0
.\venv\Scripts\python.exe -m unittest tests/parsers/test_pdf_parser_v1.py

# 2. Run existing parser test suite to guarantee 0 regression
.\venv\Scripts\python.exe -m unittest discover -s tests/parsers

# 3. Check git status to ensure zero dirty core files
git status
```

---

## 4. Definition of Done
- [ ] `core/parsers/pdf/` package exists with `PdfParser`.
- [ ] `core/parsers/router.py` automatically registers `PdfParser`.
- [ ] `tests/parsers/test_pdf_parser_v1.py` passes with 100% success rate.
- [ ] All other parser tests (`.docx`, `.txt`, `.doc`) continue to pass with 0 regressions.
- [ ] `core/` files (`chunker.py`, `retriever.py`, `uploader.py`) remain completely untouched.

