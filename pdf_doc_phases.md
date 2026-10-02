# Phased Plan: Pulling & Documenting the PDF Parsing Architecture

This plan is designed for an iterative workflow in the `parser_docs` branch. Instead of pulling everything at once or following raw git commits, you pull and document the architecture **capability by capability**.

For each phase, you ask your LLM to retrieve only the relevant functions and files, verify understanding, and document that specific layer before moving to the next.

---

## Roadmap Overview

```
Phase 1: Router Skeleton, Registration & Page Triage
   │
   ▼
Phase 2: Fast-Text Path (PyMuPDF4LLM) & Page Provenance Stamping
   │
   ▼
Phase 3: Table Tier & Native Text-Layer Protection (OCR Suppression)
   │
   ▼
Phase 4: Visual/Image Tier (SmolVLM Figure Captioning)
   │
   ▼
Phase 5: Pre-Merge Text Sanitization (Vocabulary Segmenter & Cleaners)
   │
   ▼
Phase 6: AST Structure Normalization & Heading Hierarchy Repair
   │
   ▼
Phase 7: Intelligent Chunking, Table Markdown & Chunk Sanitization
   │
   ▼
Phase 8: API Wire-Up, Full Configuration Reference & Verification
```

---

## Phase 1: Router Skeleton, Registration & Page Triage

### 1. Objective
Establish the entry point for PDF processing: register `PdfPageRouter` in the central parser router and implement the per-page inspection (triage) logic that determines how each page should be handled.

### 2. Relevant Code to Retrieve
- **Files**:
  - `parsers/pdf_router.py`: Class definition `PdfPageRouter`, `can_handle()`, `_single_page_bytes()`, and `_triage_page()`.
  - `parsers/router.py`: Registration of `PdfPageRouter` replacing `PdfStubParser`.
  - `config.py`: Triage threshold settings (`enable_pdf_page_router`, `pdf_min_text_chars_for_text_route`, `pdf_page_budget`).

### 3. Key Mechanics to Understand
- **Extension Routing**: `can_handle(ext)` intercepts `.pdf` files.
- **PyMuPDF (`fitz`) Triage**: Opens the PDF bytes in memory. For each page index:
  1. Checks character count (`len(page.get_text())`).
  2. Detects tables via `page.find_tables().tables`.
  3. Detects images via `page.get_images()`.
  4. Returns a `list[str]` of tags (`["text"]`, `["table"]`, `["image"]`, or combined `["table", "image"]`).
- **Feature Flag Fallback**: If `settings.enable_pdf_page_router` is `False`, the router falls back to default full-document Docling conversion.

### 4. What to Document in `parser_docs`
- Diagram of the triage decision tree (Thresholds: $\ge 800$ characters without tables $\rightarrow$ `text`; tables present $\rightarrow$ `table`; images + low text $\rightarrow$ `image`).
- Explanation of why triage exists (speed vs. accuracy tradeoff: avoids heavy OCR/VLM when standard text extraction suffices).

---

## Phase 2: Fast-Text Path & Page Provenance Stamping

### 1. Objective
Implement the high-speed text path using `pymupdf4llm` and solve the critical **Page Provenance** issue so chunks preserve accurate page numbers.

### 2. Relevant Code to Retrieve
- **Files**:
  - `parsers/pdf_router.py`: `_fast_text_page()`, `_merge_pages()`.

### 3. Key Mechanics to Understand
- **Fast-Text Extraction**: `pymupdf4llm.to_markdown(doc, pages=[page_no])` rapidly extracts clean markdown ($\sim 50$ms/page) while preserving bolding and headers.
- **The Page Provenance Bug**: When multiple pages of markdown are concatenated and converted into a `DoclingDocument` in one shot, Docling assigns empty provenance (`prov=[]`), causing chunk metadata to have `page = None` and `page_numbers = []`.
- **The Fix (`_merge_pages`)**:
  - Converts each page's markdown into its own isolated `DoclingDocument`.
  - Iterates over every item (`texts`, `tables`, `pictures`) and attaches an explicit `ProvenanceItem(page_no=page_no + 1, ...)`.
  - Merges them into the unified document via `merged_doc.add_text()` / `add_document()`.

### 4. What to Document in `parser_docs`
- How `pymupdf4llm` works for text pages.
- The provenance data structure (`ProvenanceItem`) and why explicit per-page stamping is necessary for downstream RAG citations.

---

## Phase 3: Table Tier & Native Text-Layer Protection (OCR Suppression)

### 1. Objective
Extract complex tables using Docling's structural table model, while preventing destructive OCR from corrupting existing digital text layers.

### 2. Relevant Code to Retrieve
- **Files**:
  - `parsers/pdf_router.py`: `_docling_page()`, `_build_text_layer_converter()`, `_build_docling_converter()`.
  - `config.py`: `pdf_text_layer_min_chars` (default: 40), `pdf_allow_ocr_on_text_pages` (default: False).

### 3. Key Mechanics to Understand
- **TableFormer Extraction**: Pages tagged with `"table"` are sent to Docling's converter, which reconstructs full HTML/Markdown table grids.
- **The Bitmap OCR Trap**: In PDFs where pages are high-res background bitmaps with an embedded digital text layer, Docling's default `do_ocr=True` forces full-page OCR. This produces garbled words (`perlOOg`) and deletes white text on colored header rows (e.g. missing "Day 1" headers).
- **The Fix (`_build_text_layer_converter`)**:
  - Measures the length of the page's native digital text layer.
  - If text length $\ge 40$ chars, creates a converter with `do_ocr=False` and `TableStructureOptions(do_cell_matching=True)`.
  - Digital text is preserved perfectly while table cells and columns are extracted.

### 4. What to Document in `parser_docs`
- Docling TableFormer workflow.
- Explanation of the OCR bypass condition (`do_ocr=False` when text layer $\ge 40$ chars).

---

## Phase 4: Visual & Diagram Tier (SmolVLM Figure Captioning)

### 1. Objective
Enable vision-language model (VLM) descriptions for diagram-, chart-, and image-heavy pages, including sanitization of raw model completion tokens.

### 2. Relevant Code to Retrieve
- **Files**:
  - `parsers/pdf_router.py`: `_smolvlm_page()`, `_picture_descriptions_only()`, `_inject_picture_descriptions()`, `_build_vlm_converter()`.
  - `config.py`: `pdf_enable_smolvlm_triage`, `picture_description_preset` (`smolvlm`).

### 3. Key Mechanics to Understand
- **Pipeline Configuration**: Must use `PdfPipelineOptions(generate_page_images=True)` (using `ConvertPipelineOptions` causes an attribute crash on PDFs).
- **Combined Table + Image Pages**: When a page has both tables and images, `_picture_descriptions_only()` extracts table layout from Docling, then runs SmolVLM only on the pictures and appends `[Figure description]` without duplicating the body text.
- **Token Sanitization**: Raw SmolVLM completions often leak tokens like `<image>` or `<end_of_utterance>`. `_inject_picture_descriptions()` runs regex cleaning to strip special tokens before markdown export.

### 4. What to Document in `parser_docs`
- How SmolVLM-256M is initialized and invoked through Docling.
- The dual-handling strategy for mixed table + image pages.

---

## Phase 5: Pre-Merge Text Sanitization (`pdf_cleanup.py`)

### 1. Objective
Sanitize raw page markdown before it is parsed into the document tree. Use a document-specific vocabulary to fix missing spaces without requiring external dictionaries.

### 2. Relevant Code to Retrieve
- **Files**:
  - `parsers/pdf_cleanup.py`: `build_vocab()`, `segment_words()`, `clean_page_markdown()`, `strip_running_footers()`, `fix_soft_breaks()`.
  - `parsers/pdf_router.py`: Invocation of `clean_page_markdown()`.

### 3. Key Mechanics to Understand
- **Dynamic Vocabulary Segmenter**:
  - PDF extraction often fuses words together (`basedon`, `RingDips`).
  - Standard dictionary splitters can corrupt jargon, proper names, or promo codes (`hetCOI`, `Brinta`).
  - `build_vocab()` counts word frequencies solely from the PDF's own text layer.
  - `segment_words()` runs dynamic programming to split a fused token *only if all pieces exist in the document's own vocabulary*.
- **Soft Breaks & Hyphenation**: Normalizes `15\n-\n30` to `15-30` and replaces single linebreaks with spaces.
- **Running Footer Removal**: Collects repeated lines across $\ge 4$ pages (or 10% of the document) and strips them so footers do not pollute body chunks.

### 4. What to Document in `parser_docs`
- The dynamic programming vocabulary segmentation algorithm.
- Regex rules for soft hyphens, URLs, and repeated footer suppression.

---

## Phase 6: AST Structure Normalization & Heading Hierarchy (`pdf_structure.py`)

### 1. Objective
Repair the document object tree before chunking to fix heading freezes, normalize nested hierarchies, demote CTA buttons, and repair Table of Contents.

### 2. Relevant Code to Retrieve
- **Files**:
  - `parsers/pdf_structure.py`: `repair_heading_sequence()`, `demote_pseudo_headings()`, `bind_captions()`, `_try_toc()`.
  - `parsers/pdf_router.py`: `_repair_pdf_headings()`, `_split_embedded_headings()`, `_extract_misplaced_number()`.

### 3. Key Mechanics to Understand
- **The "Heading Freeze" Root Cause**:
  - In Docling, `TitleItem` is level 0. `HierarchicalChunker` locks level-0 titles as persistent context until another level-0 title clears it.
  - Numbered headings (e.g. `7.1` through `7.9`) are `SectionHeaderItem` (level 1+) and can never clear a level-0 title, freezing heading context across dozens of chunks.
- **Heading Level Normalization**:
  - `_repair_pdf_headings()` converts every `TitleItem` to `SectionHeaderItem`.
  - Assigns explicit numeric levels based on dot depth (`"7"` $\rightarrow$ 1, `"7.3"` $\rightarrow$ 2, `"7.3.1"` $\rightarrow$ 3; unnumbered $\rightarrow$ 1).
- **TOC Repair**: `_try_toc()` detects 2-column contents tables and formats them into an aligned 3-column table (`No. / Section / Page`).
- **Demoting Buttons**: Call-to-action buttons (`Start Now!`, `Buy Program`) are demoted from headers to ordinary text.

### 4. What to Document in `parser_docs`
- Explanation of the Docling heading freeze and the leveling fix.
- How TOCs and buttons are normalized in the AST.

---

## Phase 7: Downstream Chunking, Table Markdown & Chunk Sanitization

### 1. Objective
Ensure chunks produce clean, readable markdown (especially for tables), insert synthetic headings in chronological page order, and strip leftover markdown tokens.

### 2. Relevant Code to Retrieve
- **Files**:
  - `core/chunker.py`: `_MarkdownTableChunkSerializer`, `_MarkdownTableSerializerProvider`, Gap-B synthetic heading loop.
  - `core/chunk_cleanup.py`: `strip_markup()`, `is_micro_label()`, `postprocess_chunks()`.
  - `config.py`: `chunk_postprocess` toggle.

### 3. Key Mechanics to Understand
- **Markdown Table Serialization**:
  - By default, Docling serializes tables in triplet format (`row, col = value`), creating confusing key-value pairs for multi-column tables.
  - `MarkdownTableSerializer` forces clean markdown grid serialization with `repeat_table_header=True`.
- **Fixing "Tail Orphans"**:
  - Heading-only pages/slides produce no body chunks. Gap-B creates synthetic chunks for them.
  - Previously, these were appended to the very end of the chunk list.
  - Now, they are inserted at their exact page location in reading order, and `chunk_index` is renumbered.
- **Chunk Post-Processing**:
  - Strips leaked `###` and `**bold**` formatting.
  - Drops trailing lines that duplicate the next chunk's starting heading.
  - Skips standalone running logos/labels (`is_micro_label`: $\le 3$ words, $< 40$ chars, no digits, like `Calisthenics Family`).

### 4. What to Document in `parser_docs`
- Table serialization comparison (triplet vs. markdown table).
- Synthetic chunk insertion ordering algorithm.
- Chunk post-processing sanitization pass.

---

## Phase 8: API Integration, Configuration Reference & Verification

### 1. Objective
Wire the complete pipeline into the FastAPI application, document all configuration toggles, and establish verification procedures.

### 2. Relevant Code to Retrieve
- **Files**:
  - `api/v1/endpoints/documents.py`: Ingestion route handler.
  - `api/dependencies.py`: Dependency injection for `ParserRouter` and `Chunker`.
  - `config.py`: Complete `Settings` dataclass.
  - `tests/parsing_arch/v5_8/test_v58_repairs.py`: Final unit test suite.

### 3. Key Mechanics to Understand
- **End-to-End Flow**:
  1. `POST /api/v1/documents` receives file bytes.
  2. `ParserRouter.parse()` delegates to `PdfPageRouter` (or format-specific parser).
  3. Returns a cleaned `DoclingDocument`.
  4. `Chunker.chunk()` transforms the document into `list[Chunk]` with rich metadata (`file_id`, `filename`, `page`, `page_numbers`, `headings`, `chunk_index`).
- **Configuration Toggles**: Document the master kill-switches (`chunk_postprocess`, `pdf_v57_cleanup`, `enable_pdf_page_router`).

### 4. What to Document in `parser_docs`
- Architecture summary diagram connecting API $\rightarrow$ Router $\rightarrow$ Cleaners $\rightarrow$ Chunker.
- Master configuration reference table.
- Testing & verification guide.

---

## Summary Prompt Template for Your LLM

When you are ready to pull a phase into `parser_docs`, you can prompt your LLM like this:

> *"I am working on Phase X ([Phase Name]) of the parsing architecture documentation as outlined in `pdf_doc_phases.md`. Please retrieve only the relevant code and functions specified for Phase X from `parser_v1`, explain their internal mechanics, and generate the corresponding section for `parser_docs`."*
