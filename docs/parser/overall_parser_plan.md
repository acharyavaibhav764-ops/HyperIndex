# Master Document Parsing Architecture & Version Release Plan

**Document:** `docs/overall_parser_plan.md`  
**Purpose:** Consolidated master roadmap for the document parsing architecture in the Honeywell Virtual Assistant, synthesizing the technical specifications, version releases (v1 through v6), per-page PDF triage logic, and production serving migration.

---

## 1. Executive Summary & System Architecture

The goal of this architecture is to replace ad-hoc, brittle text extractors with a unified, high-fidelity document parsing and chunking pipeline. Rather than forcing every file through a single monolithic tool or creating fragmented extraction formats, all inputs are normalized into a unified, structure-preserving schema (`DoclingDocument` / block-level format) that flows seamlessly into a structure-aware `HybridChunker`.

```
                                      INCOMING FILE
                                            │
                                 Extension / MIME Detection
                                            │
        ┌──────────┬──────────────┬─────────┴──────────┬──────────────┬────────────────┐
        ▼          ▼              ▼                    ▼              ▼                ▼
     TXT / MD     DOCX           PPTX             Legacy DOC/PPT     PDF (v4 Stub)   Images / Scans
        │          │              │                    │              │                │
    TextParser     └──────┬───────┘             LibreOffice Headless  │ (v5 Triage)    │
   (convert_str)          │ (v2)                  → Docling (v3)      │                │
        │           DoclingParser                      │              ▼                ▼
        │          (DocumentStream)                    │        PdfPageRouter     DeepSeek-OCR2
        │                 │                            │       (PyMuPDF4LLM /     (Single Model
        │                 │                            │        Docling / OCR)      OCR + VLM)
        │                 ▼                            │              │                │
        └─────────► DoclingDocument ◄──────────────────┴──────────────┴────────────────┘
                          │
                          ▼
                 Structure-Aware Chunking
             (HybridChunker + contextualize())
                          │
                          ▼
                 ChromaDB Embeddings
```

---

## 2. Version Release Roadmap

| Version | Status | Target Branch | Key Deliverables & Scope | Merge / Integration Point |
|---|---|---|---|---|
| **v1** | **COMPLETED** | `feat/parsing-architecture` | `BaseParser` interface, `TextParser` (TXT/MD via `convert_string`), `ParserRouter` scaffold, `HybridChunker` integration in `Chunker`. | Internal only; legacy routes untouched. |
| **v2** | **COMPLETED** | `feat/parsing-architecture` | `DoclingParser` for `.docx` & `.pptx`; critical `contextualize()` heading-loss fix & synthetic heading chunks; local lightweight picture description (SmolVLM-256M / Granite-Vision via Ollama). | Internal only; legacy routes untouched. |
| **v3** | **PLANNED** | `feat/parsing-architecture` | `LibreOfficeConverter` for legacy binary formats (`.doc`, `.ppt`) via headless conversion to modern XML formats then routed through `DoclingParser`; deprecates `antiword`. | Internal only; legacy routes untouched. |
| **v4** | **PLANNED** | `feat/parsing-architecture` | `PdfStubParser` for initial PDF support; complete extension coverage in `ParserRouter`; **switch ingestion endpoint (`POST /api/v1/documents`) to `ParserRouter`**. | **Milestone: Merge `feat/parsing-architecture` into `main`**. |
| **v5** | **PLANNED** | `feat/pdf-deep-parser` | Deep PDF Engine: `PdfPageRouter` with 3-signal per-page triage (`PyMuPDF4LLM` for clean text, `Docling TableFormer` for tables, `DeepSeek-OCR2` for scans/diagrams); unified block reassembly by `(page, y_pos)`; front-matter heuristics. | Separate branch off `main` post-v4. |
| **v6** | **FUTURE PLANNED** | `feat/pdf-deep-parser` | Production vLLM migration for `DeepSeek-OCR2` serving (`AsyncLLMEngine`); batch inference optimization on target hardware (≥8GB VRAM). | Production deployment optimization. |

---

## 3. Detailed Version Specifications

### v1: Foundation & Plaintext Parsing (COMPLETED)
* **Objective:** Establish the pluggable parser framework and backward-compatible chunking.
* **Core Components:**
  - `parsers/base.py`: Abstract `BaseParser` requiring `can_handle(ext)` and `parse(file_bytes, filename)`.
  - `parsers/text.py`: `TextParser` handling `.txt`, `.text`, `.md`, `.markdown` with robust UTF-8/Latin-1 encoding fallbacks and Docling `DocumentConverter.convert_string()`.
  - `parsers/router.py`: Initial `ParserRouter` registry mapping file extensions to parser instances.
  - `core/chunker.py`: Upgraded `Chunker.split()` supporting `DoclingDocument` inputs via `HybridChunker` while maintaining legacy tuple fallback.
  - `config.py`: Added `chunker_tokenizer` setting (`sentence-transformers/all-MiniLM-L6-v2`).

---

### v2: Office Documents & Local Picture Description (COMPLETED)
* **Objective:** In-memory parsing for Word (`.docx`) and PowerPoint (`.pptx`) with table preservation, heading retention, and local image captioning.
* **Core Components:**
  - `parsers/docling_parser.py`: In-memory `DoclingParser` streaming raw bytes via `DocumentStream` into `DocumentConverter.convert()`.
  - **Critical Fix (`contextualize()`)**:
    - Replaced `chunk.text` with `chunker.contextualize(chunk)` to prevent section and slide titles from being stripped from chunk embeddings.
    - Added synthetic chunk generation for heading-only divider slides/sections.
  - **Local Picture Description Tier**:
    - Enabled local VLM enrichment (`smolvlm` preset / Granite-Vision via Ollama) to describe diagrams/photos in DOCX/PPTX without external cloud dependencies.
    - Two-stage regex stripping for special tokens (`<end_of_utterance>`) and unclosed trailing token fragments (`<end_of_utteranc`).
    - Standardized `[Figure description]` text tagging and `'source': 'image_description'` metadata injection.

---

### v3: Legacy Formats (.doc & .ppt) (PLANNED)
* **Objective:** Eliminate brittle external scrapers (e.g. `antiword`) and bring legacy binary Office formats into the structured `DoclingDocument` pipeline.
* **Architecture & Flow:**
  ```
  Binary (.doc / .ppt) ──► LibreOffice Headless (convert-to docx/pptx) ──► DoclingParser ──► DoclingDocument
  ```
* **Core Components:**
  - `core/parsers/libreoffice_converter.py`: Subprocess wrapper calling `soffice --headless --convert-to docx/pptx` in an isolated temp environment, returning converted bytes.
  - `core/parser_router.py`: Register `.doc` and `.ppt` to route through the converter into `DoclingParser`.
  - **Error Handling & Fallbacks**: Graceful error handling if LibreOffice binary is missing from host environment.

---

### v4: PDF Stub & Full Ingestion Pipeline Switch (PLANNED)
* **Objective:** Complete format coverage in `ParserRouter`, switch live ingestion traffic away from legacy `core/parser.py`, and merge `feat/parsing-architecture` into `main`.
* **Architecture & Flow:**
  - `core/parsers/pdf_stub.py`: Fast initial PDF parser (using PyMuPDF or basic Docling PDF pipeline) to satisfy full format coverage.
  - `api/dependencies.py`: Expose `get_parser_router()` singleton.
  - `api/v1/endpoints/documents.py`: Switch ingestion pipeline to call `ParserRouter.parse()` and pass `DoclingDocument` directly to `Chunker`.
* **Milestone**: At the completion of v4, all supported file types (.txt, .md, .docx, .pptx, .doc, .ppt, .pdf) route through `ParserRouter`. The `feat/parsing-architecture` branch merges into `main`.

---

### v5: PDF Deep Parser & Per-Page Triage Engine (PLANNED)
* **Objective:** High-performance, compute-efficient PDF parsing using millisecond per-page triage. Avoids sending clean text pages to heavy AI parsers while applying specialized models where needed.
* **Per-Page Triage Specification (PyMuPDF `fitz`):**
  1. `text_tokens = len(page.get_text().split())` -> `has_text = text_tokens > 10`
  2. `image_ratio = image_bbox_area(page) / page_area(page)`
  3. `has_table = len(page.find_tables().tables) > 0`

  ```python
  if not has_text or image_ratio > 0.5:
      route = "OCR_VLM_TIER"     # Scanned / image-heavy -> DeepSeek-OCR2
  elif has_table:
      route = "DOCLING"          # Table detected -> Docling (TableFormer)
  else:
      route = "PYMUPDF4LLM"      # Clean digital text -> PyMuPDF4LLM (fastest & highest text fidelity)

  # Cover page heuristic
  is_front_matter = (page_number <= 2) and (text_tokens < 30) and (image_ratio > 0.6)
  ```

* **OCR + Vision Strategy (Single Unified Model):**
  - Use **DeepSeek-OCR2** for both document OCR and diagram/figure description (prompt-switched: transcription prompt for text; descriptive prompt for diagrams).
  - Escalate to **Qwen2.5-VL (7B)** only if empirical evaluation reveals DeepSeek-OCR2 captions on complex photographic hardware are insufficient.
* **Block Reassembly:**
  - Standardize page blocks into `{ text, page, bbox, source_backend }`.
  - Reassemble document by sorting all blocks by `(page_number, y_position)`.
  - Feed ordered blocks into structure-aware `HybridChunker`.

---

### v6: Production vLLM Migration for DeepSeek-OCR2 (FUTURE PLANNED)
* **Objective:** High-throughput batch serving for the PDF OCR/VLM tier on production infrastructure.
* **Hardware & Environment Context:**
  - *Dev Machine (GTX 1650, 4GB VRAM)*: Runs lightweight local models (SmolVLM / Granite-Vision). DeepSeek-OCR2 requires ≥8GB VRAM.
  - *Target Production Machine (≥8GB VRAM / Server GPU)*: Runs DeepSeek-OCR2 via vLLM `AsyncLLMEngine`.
* **Scope:**
  - Replace standalone HuggingFace Transformers inference wrapper with a vLLM serving backend (`services/deepseek_ocr2_server.py`).
  - Update `config.py` with vLLM OpenAI-compatible endpoint configurations.
  - Measure and optimize batch parsing latency and GPU memory recycling.

---

## 4. File Ownership & Modification Matrix

| File Path | Version | Action | Purpose |
|---|---|---|---|
| `core/parsers/__init__.py` | v1 | [NEW] | Export base parser and router interfaces |
| `core/parsers/base.py` | v1 | [NEW] | Abstract `BaseParser` contract |
| `core/parsers/text.py` | v1 | [NEW] | Plaintext & Markdown parser |
| `core/parsers/router.py` | v1, v2, v3, v4, v5 | [MODIFY] | Register parsers per extension (.txt, .docx, .doc, .pdf) |
| `core/chunker.py` | v1, v2 | [MODIFY] | Add `HybridChunker`, `contextualize()` fix, image metadata tagging |
| `config.py` | v1, v2, v5, v6 | [MODIFY] | Add tokenizer, VLM presets, OCR settings, vLLM endpoints |
| `core/parsers/docling_parser.py` | v2 | [NEW] | DOCX/PPTX parser + local VLM image description |
| `core/parsers/libreoffice_converter.py` | v3 | [NEW] | Headless converter for `.doc` and `.ppt` |
| `core/parsers/pdf_stub.py` | v4 | [NEW] | Baseline PDF parser for complete format coverage |
| `api/dependencies.py` | v4 | [MODIFY] | Add `ParserRouter` dependency injection |
| `api/v1/endpoints/documents.py` | v4 | [MODIFY] | Switch live ingestion endpoint to `ParserRouter` |
| `core/parsers/pdf_router.py` | v5 | [NEW] | Per-page triage router (`PyMuPDF4LLM` + `Docling` + `DeepSeek-OCR2`) |
| `services/deepseek_ocr2_server.py` | v5, v6 | [NEW / MODIFY] | OCR/VLM backend (HF Transformers in v5 -> vLLM in v6) |

---

## 5. Test Harness & Verification Directory Structure

```
tests/
├── v0.3/                          # (Locked baseline — never touch)
├── v0.4/                          # (Locked baseline — never touch)
└── parsing_arch/
    ├── v1/                        # Foundation & Text parser unit tests
    │   ├── test_base.py
    │   ├── test_text.py
    │   └── test_router.py
    ├── v2/                        # Office & Picture description tests
    │   ├── test_docling_parser.py
    │   ├── test_serialize_fix.py
    │   └── test_picture_description.py
    ├── v3/                        # Legacy format conversion tests (.doc, .ppt)
    ├── v4/                        # Full ingestion integration & router tests
    ├── v5/                        # PDF triage, block reassembly & DeepSeek-OCR2 eval
    └── v6/                        # vLLM batch serving benchmarks
```

---

## 6. Core Engineering Guidelines

1. **Zero Regression Guarantee:** Every version must run and pass the full historical test suite (`pytest tests/`).
2. **Public API Immutability:** The ingestion response schema (`POST /api/v1/documents`), status codes, and query endpoints remain strictly backward-compatible.
3. **Comment & Docstring Integrity:** Existing comments, docstrings, and architectural rationale must be preserved during edits.
4. **Additive Transitions:** New parsers and routers operate alongside legacy implementations until explicit cutover milestones (v4 for ingestion, v5 for deep PDF).

