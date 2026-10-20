# PDF Parser Implementation Plan: Version 3.0 (Document Normalization & Structural Repairs)

## Executive Summary
PDF v3.0 establishes the modular post-processing transformation pipeline inside `core/parsers/pdf/transforms/` and `core/parsers/pdf/postprocess.py`.

In raw PDF extraction (especially with PyMuPDF4LLM and Docling), documents suffer from four severe structural defects:
1. **The Heading Freeze Bug**: PyMuPDF4LLM evaluates font sizes independently per page. A sub-section heading that happens to be the largest font on page 3 is tagged as `# H1` (`TitleItem`, level 0). In Docling's `HybridChunker`, a level-0 title freezes the heading hierarchy for all subsequent pages.
2. **Wingdings & Symbol Glyph Mojibake**: Honeywell manuals use Wingdings font code points (e.g. `\uf0fc`, `\uf0fe` for green checkmarks, `\uf0e8` for arrows, and `\uf0b7` for bullets). These extract as empty boxes/private-use characters (`U+F0xx`), which are completely lost to vector embeddings.
3. **SmolVLM Completion Leaks & Markdown Debris**: Raw vision models leak completion artifacts (e.g., `<end_of_utteranc>`), while extracted markdown often carries duplicated headers, broken paragraph glue, and running headers/footers.
4. **Table of Contents (ToC) Clutter**: Unflagged ToC entries pollute vector similarity searches with duplicate keyword lists.

PDF v3.0 introduces a clean, composable transform pipeline (`core/parsers/pdf/transforms/`) that resolves these defects before the document is passed to the chunker.

---

## 1. Architectural Scope & Invariants

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        PDF v3.0 Scope Boundary                         │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Active Working Branch                                               │
│    └── pdf_refactor (0 branch switching, purely on pdf_refactor)       │
│                                                                        │
│ 2. Modules to Create inside core/parsers/pdf/                          │
│    ├── transforms/                                                     │
│    │   ├── __init__.py                                                 │
│    │   ├── glyphs.py (Wingdings & symbol Unicode translation)          │
│    │   ├── cleanup.py (Token scrubbing, running lines, markdown clean) │
│    │   └── structure.py (Heading freeze repair & ToC tagging)          │
│    └── postprocess.py (Sequential transformation pipeline runner)      │
│                                                                        │
│ 3. Module to Update                                                    │
│    └── parser.py (Connect post-processing pipeline after page merger)  │
│                                                                        │
│ 4. System Invariants                                                   │
│    ├── Zero modifications to core/chunker.py, retriever.py, uploader.py│
│    ├── Pure, stateless transform functions                            │
│    └── Backward-compatible DoclingDocument output                      │
│                                                                        │
│ 5. Automated Tests                                                     │
│    ├── tests/parsers/test_pdf_glyphs.py                                │
│    ├── tests/parsers/test_pdf_cleanup.py                               │
│    └── tests/parsers/test_pdf_structure.py                             │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Implementation Deliverables

### Phase 1: Symbol & Glyph Translation (`core/parsers/pdf/transforms/glyphs.py`)
Ported and streamlined from `parser_v1:parsers/pdf_glyphs.py`:
* **Functionality**:
  - `_PUA_RE`: Regex detecting Private Use Area code points (`\ue000-\uf8ff`).
  - `_TEXT_MAP`: Maps Wingdings ticks (`\uf0fc` $\rightarrow$ `✓`), crosses (`\uf0fb` $\rightarrow$ `✗`), arrows (`\uf0e8` $\rightarrow$ `→`), and bullets (`\uf0b7` $\rightarrow$ `•`).
  - Circled digits: Maps `0xF081..0xF08A` to Unicode circled numbers `①..⑩`.
  - Table Cell Transformation: Converts table cells containing only checkmark glyphs directly to `" Yes "` and crosses to `" No "`.
* **Public APIs**:
  - `normalize_glyphs(md: str) -> str`: Normalizes markdown string before ingestion.
  - `strip_glyphs(text: str) -> str`: Strips private use characters for raw text comparisons.

---

### Phase 2: Token Scrubbing & Text Cleaning (`core/parsers/pdf/transforms/cleanup.py`)
Ported and streamlined from `parser_v1:parsers/pdf_cleanup.py`:
* **Functionality**:
  - `strip_vlm_tokens(text: str) -> str`: Removes `<end_of_utteranc>`, `<unused0>`, and XML-style model artifacts.
  - `strip_running_lines(page_markdowns: list[str]) -> list[str]`: Identifies and strips repeating header/footer boilerplate across consecutive pages.
  - `clean_markdown(md: str) -> str`: Fixes broken bold markup (`** text **`), trims excessive whitespace, and normalizes table pipe delimiters.
  - `is_noise_paragraph(text: str) -> bool`: Filters micro-labels and orphaned single-word page artifacts.

---

### Phase 3: Heading Hierarchy & Structure Normalization (`core/parsers/pdf/transforms/structure.py`)
Ported and streamlined from `parser_v1:parsers/pdf_structure.py` and `_repair_pdf_headings`:
* **Functionality**:
  - **Heading Freeze Fix**:
    - Converts all `DocItemLabel.TITLE` items on pages $> 1$ into `SectionHeaderItem`.
    - Determines heading depth deterministically from dotted numbers (e.g. `"7.3"` $\rightarrow$ level 2, `"9.4.2"` $\rightarrow$ level 3).
    - Prevents single-page `# H1` titles from freezing the hierarchical heading stack in `HybridChunker`.
  - **Pseudo-Heading Demotion**:
    - Detects button text / call-to-action lines (e.g. `"Click here to download"`, `"Order now"`) erroneously tagged as headings and demotes them to `DocItemLabel.TEXT`.
  - **Table of Contents Detection**:
    - Identifies pages containing repeating `"... <page_num>"` lines and tags items with `[TOC]`.

---

### Phase 4: Pipeline Runner & Parser Integration (`postprocess.py` & `parser.py`)

* **`core/parsers/pdf/postprocess.py`**:
  - Implements `PdfPostProcessor`:
    ```python
    class PdfPostProcessor:
        def process_markdowns(self, markdowns: list[str]) -> list[str]:
            # 1. Glyphs normalization
            # 2. Running lines & footer stripping
            # 3. Token cleanup
            return markdowns

        def process_document(self, doc: DoclingDocument) -> DoclingDocument:
            # 1. Heading structure repair (freeze fix)
            # 2. Pseudo-heading demotion & ToC tagging
            return doc
    ```
* **`core/parsers/pdf/parser.py`**:
  - Calls `post_processor.process_markdowns(page_markdowns)` before `merge_pages_to_docling()`.
  - Calls `post_processor.process_document(combined_doc)` before returning the final `DoclingDocument`.

---

### Phase 5: Automated Unit Tests

1. **`tests/parsers/test_pdf_glyphs.py`**:
   - Tests Wingdings tick/cross replacement in table cells (`| \uf0fc |` $\rightarrow$ `| Yes |`).
   - Tests arrow and bullet point normalization in prose text.
2. **`tests/parsers/test_pdf_cleanup.py`**:
   - Tests removal of `<end_of_utteranc>` and leaked tokens.
   - Tests stripping of repeating running footers across 3 dummy pages.
3. **`tests/parsers/test_pdf_structure.py`**:
   - Creates a multi-page `DoclingDocument` with a `TitleItem` on page 2.
   - Verifies `repair_headings()` converts it to a `SectionHeaderItem` with correct depth, unfreezing `HybridChunker`.

---

## 3. Verification Commands

```powershell
# 1. Run v3.0 unit tests
.\venv\Scripts\python.exe -m unittest tests/parsers/test_pdf_glyphs.py
.\venv\Scripts\python.exe -m unittest tests/parsers/test_pdf_cleanup.py
.\venv\Scripts\python.exe -m unittest tests/parsers/test_pdf_structure.py

# 2. Run full parser test suite
.\venv\Scripts\python.exe -m unittest discover -s tests/parsers

# 3. Verify clean core/ diff
git diff core/
```

---

## 4. Definition of Done
- [ ] `core/parsers/pdf/transforms/` modules created (`glyphs.py`, `cleanup.py`, `structure.py`).
- [ ] `core/parsers/pdf/postprocess.py` coordinates markdown and AST transformations.
- [ ] Heading freeze bug is resolved without touching `core/chunker.py`.
- [ ] Wingdings private-use characters are normalized to clean Unicode text and table `"Yes"`/`"No"`.
- [ ] All parser unit tests pass with 100% success rate.

