# Formal Implementation Plan: Porting Functional Features from `parser_v1` into `parser_docs`

## 1. Executive Summary
- **Source:** Branch `parser_v1` (upstream features from collaborator).
- **Target:** Branch `parser_docs` (canonical architecture using `core/parsers/` and structured testing).
- **Objective:** Port only the pending functional components—specifically **LibreOffice Headless Bridge for `.doc`/`.ppt` (v3)** and **Docling Lazy-Initialization Performance Fix**—into the modular architecture of `parser_docs`.
- **Pre-Conditions Verified:** 
  - All v2.1 changes (`_promote_pptx_pseudo_headings`, `page_numbers` span in chunker, `test_serialize_fix.py`, `v2.1.md`) are **already implemented** on `parser_docs`.
  - The working tree is clean.

---

## 2. Phased Rollout Architecture

The implementation is structured into **5 sequential phases**. Each phase is self-contained, introduces specific functional increments, and has a dedicated verification gate and test suite that must pass before advancing to the next phase.

```
┌────────────────────────────────────────────────────────┐
│ Phase 1: Environment & Runtime Configuration           │
│ (config.py, Dockerfile)                                │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ Phase 2: Performance Fix — Docling Lazy-Init           │
│ (core/parsers/docling_parser.py)                       │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ Phase 3: Core Converter — Headless LibreOffice Bridge  │
│ (core/parsers/libreoffice_converter.py, __init__.py)   │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ Phase 4: ParserRouter Integration & Extension Binding  │
│ (core/parsers/router.py)                               │
└──────────────────────────┬─────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────┐
│ Phase 5: Full Regression & Pipeline Verification       │
│ (All test suites under tests/parsers/ & tests/unit/)   │
└────────────────────────────────────────────────────────┘
```

---

## Phase 1: Environment & Runtime Configuration

### Objective
Equip the application environment and Docker container image with runtime settings and system-level dependencies required for headless LibreOffice document processing.

### File Modifications
1. **`config.py`**
   - Add LibreOffice runtime configuration fields to `Settings`:
     ```python
     # Parsing Architecture v3 — LibreOffice headless converter (.doc / .ppt)
     libreoffice_binary: str = os.getenv("LIBREOFFICE_BINARY", "")
     libreoffice_timeout_seconds: int = int(os.getenv("LIBREOFFICE_TIMEOUT_SECONDS", "60"))
     ```
2. **`Dockerfile`**
   - Add LibreOffice headless runtime packages:
     ```dockerfile
     RUN apt-get update \
         && apt-get install -y --no-install-recommends \
            antiword \
            libreoffice-core \
            libreoffice-writer \
            libreoffice-impress \
            default-jre-headless \
         && rm -rf /var/lib/apt/lists/*
     ```

### Phase 1 Tests
- **Test File:** `tests/parsers/test_config.py` (or programmatic assertion script).
- **Test Cases:**
  1. `test_default_libreoffice_settings`: Assert `settings.libreoffice_binary == ""` and `settings.libreoffice_timeout_seconds == 60`.
  2. `test_env_override_libreoffice_settings`: Assert environment variables (`LIBREOFFICE_BINARY=/custom/soffice`, `LIBREOFFICE_TIMEOUT_SECONDS=120`) are parsed accurately.

### Phase 1 Verification Gate
```bash
python -c "from config import settings; assert hasattr(settings, 'libreoffice_binary'); assert settings.libreoffice_timeout_seconds == 60"
```

---

## Phase 2: Performance Fix — Docling Lazy-Init

### Objective
Eliminate the ~8-second startup freeze during application startup, script execution, and test discovery caused by eagerly instantiating `DocumentConverter()` at module/class import time.

### File Modifications
1. **`core/parsers/docling_parser.py`**
   - In `__init__()`:
     ```python
     # Lazy-init converters on demand
     self._converter: DocumentConverter | None = None
     self._converter_vlm: DocumentConverter | None = None
     ```
   - In `parse()`:
     ```python
     if settings.enable_picture_description:
         doc = self._convert_with_vlm(stream, filename)
     else:
         if self._converter is None:
             self._converter = DocumentConverter()
         result = self._converter.convert(stream)
         doc = result.document
     ```
   - In `_convert_with_vlm()`:
     Ensure the fallback branch checks `if self._converter is None: self._converter = DocumentConverter()`.

### Phase 2 Tests
- **Test File:** `tests/parsers/test_docling.py`
- **Test Cases:**
  1. `test_docling_parser_instantiation_is_fast`: Assert instantiating `DoclingParser()` executes in < 50ms and does not initialize PyTorch models immediately.
  2. `test_docling_parser_converts_plain_docx`: Verify that on first `parse()` call, `_converter` is initialized and valid `DoclingDocument` is returned.
  3. `test_existing_docling_suite`: Run all existing unit tests in `test_docling.py` to ensure zero regression in `.docx` and `.pptx` parsing.

### Phase 2 Verification Gate
```bash
python -m unittest tests/parsers/test_docling.py
```

---

## Phase 3: Core Converter — Headless LibreOffice Bridge

### Objective
Implement the `LibreOfficeConverter` component inside `core/parsers/` to convert binary `.doc` to `.docx` and `.ppt` to `.pptx` via an isolated headless LibreOffice subprocess, delegating the resulting OpenXML stream to `DoclingParser`.

### File Modifications
1. **Create `core/parsers/libreoffice_converter.py`**
   - Implement `LibreOfficeNotFoundError(RuntimeError)` and `LibreOfficeConversionError(RuntimeError)`.
   - Implement `find_libreoffice_binary() -> str`:
     - Checks `settings.libreoffice_binary`
     - Checks `PATH` via `shutil.which`
     - Searches standard Windows `Program Files\LibreOffice\program\soffice.exe`
     - Searches standard Unix paths (`/usr/bin/soffice`, `/usr/local/bin/soffice`, etc.)
     - Raises `LibreOfficeNotFoundError` with clear remediation instructions if not found.
   - Implement `LibreOfficeConverter(BaseParser)`:
     - `SUPPORTED_EXTENSIONS = frozenset({".doc", ".ppt"})`
     - `TARGET_FORMAT_MAP = {".doc": "docx", ".ppt": "pptx"}`
     - `convert_to_openxml(file_bytes, filename)`:
       - Runs subprocess with dedicated sandbox profile: `-env:UserInstallation=file:///<temp>/lo_profile` to prevent concurrency file locks.
       - Enforces configurable timeout (`settings.libreoffice_timeout_seconds`).
       - Validates output file generation and non-zero exit codes.
     - `parse(file_bytes, filename, **kwargs) -> DoclingDocument`:
       - Invokes `convert_to_openxml()`.
       - Hands converted OpenXML bytes directly to `self._docling_parser.parse()`.

2. **Update `core/parsers/__init__.py` and `core/__init__.py`**
   - Export `LibreOfficeConverter`, `LibreOfficeNotFoundError`, and `LibreOfficeConversionError`.

### Phase 3 Tests
- **Create Test File:** `tests/parsers/test_libreoffice_converter.py` (ported and adapted to `core.parsers`).
- **Test Cases:**
  1. `test_uses_configured_path_if_file_exists`: Verifies `settings.libreoffice_binary` preference.
  2. `test_falls_back_to_which`: Verifies `shutil.which` PATH discovery.
  3. `test_raises_when_not_found`: Verifies `LibreOfficeNotFoundError` is raised when binary is absent.
  4. `test_doc_conversion_uses_correct_format_flag`: Verifies subprocess args include `--convert-to docx`.
  5. `test_ppt_conversion_uses_pptx_format`: Verifies subprocess args include `--convert-to pptx`.
  6. `test_sandbox_user_installation_flag`: Verifies `-env:UserInstallation=` is present in the subprocess call.
  7. `test_timeout_raises_conversion_error`: Verifies `subprocess.TimeoutExpired` maps to `LibreOfficeConversionError`.
  8. `test_nonzero_exit_raises_conversion_error`: Verifies non-zero process exits raise `LibreOfficeConversionError`.
  9. `test_missing_output_file_raises_conversion_error`: Verifies missing output produces `LibreOfficeConversionError`.
  10. `test_unsupported_format_raises_value_error`: Verifies non-`.doc`/`.ppt` input raises `ValueError`.
  11. `test_can_handle_doc_and_ppt`: Verifies `can_handle(".doc")` and `can_handle(".ppt")` return True.
  12. `test_parse_delegates_to_docling_parser`: Verifies parsed output is forwarded to `DoclingParser.parse()`.

### Phase 3 Verification Gate
```bash
python -m unittest tests/parsers/test_libreoffice_converter.py
```

---

## Phase 4: ParserRouter Integration & Extension Binding

### Objective
Register `LibreOfficeConverter` into `ParserRouter` so that legacy `.doc` and `.ppt` files automatically route through the conversion bridge.

### File Modifications
1. **`core/parsers/router.py`**
   - Import `LibreOfficeConverter`:
     ```python
     from .libreoffice_converter import LibreOfficeConverter
     ```
   - In `ParserRouter.__init__()`:
     ```python
     # v1: .txt, .md
     self.register(TextParser())
     # v2: .docx, .pptx
     self.register(DoclingParser())
     # v3: .doc, .ppt
     self.register(LibreOfficeConverter())
     ```
   - Update docstrings to reflect v3 format support.

### Phase 4 Tests
- **Update Test File:** `tests/parsers/test_router.py`
- **Test Cases:**
  1. `test_doc_routes_to_libreoffice_converter`: Replaces legacy `test_doc_legacy_unsupported` to assert `router.get_parser(".doc")` is an instance of `LibreOfficeConverter`.
  2. `test_ppt_routes_to_libreoffice_converter`: Asserts `router.get_parser(".ppt")` is an instance of `LibreOfficeConverter`.
  3. `test_supported_extensions_includes_doc_and_ppt`: Asserts `.doc` and `.ppt` are present in `router.supported_extensions`.
  4. `test_case_insensitive_doc_and_ppt`: Asserts `.DOC` and `.PPT` correctly resolve to `LibreOfficeConverter`.
  5. `test_pdf_still_unsupported`: Asserts `.pdf` still raises `ValueError` (pending v5 PDF branch).

### Phase 4 Verification Gate
```bash
python -m unittest tests/parsers/test_router.py
```

---

## Phase 5: Full Regression & Integration Verification

### Objective
Validate complete end-to-end compatibility across the entire parser subsystem and ensure no regression in text chunking or legacy APIs.

### Test Matrix to Execute
1. `tests/parsers/test_base.py` (BaseParser contract tests)
2. `tests/parsers/test_text.py` (TextParser .txt / .md tests)
3. `tests/parsers/test_docling.py` (DoclingParser .docx / .pptx tests)
4. `tests/parsers/test_picture_description.py` (VLM picture description tests)
5. `tests/parsers/test_serialize_fix.py` (Heading visibility & serialization tests)
6. `tests/parsers/test_libreoffice_converter.py` (New LibreOffice bridge tests)
7. `tests/parsers/test_router.py` (Full router resolution tests)
8. `tests/unit/test_chunker.py` (HybridChunker & provenance tests)
9. `tests/unit/test_parse.py` (Parser integration test)

### Phase 5 Verification Gate
```bash
python -m unittest discover -s tests/parsers
python -m unittest discover -s tests/unit
```

---

## 6. Git Safety & Rollback Procedures

- A dedicated backup branch `backup-parser_v1-documented-work` has already been recorded at commit `70a8782`.
- Work is performed strictly on `parser_docs`.
- Each phase can be committed with an atomic commit message:
  - Phase 1: `feat(config): add LibreOffice settings and container packages`
  - Phase 2: `perf(parsers): lazy-initialize DocumentConverter in DoclingParser`
  - Phase 3: `feat(parsers): implement LibreOfficeConverter for legacy .doc/.ppt`
  - Phase 4: `feat(router): register LibreOfficeConverter for .doc and .ppt`
  - Phase 5: `test(parsers): full regression and integration validation`
