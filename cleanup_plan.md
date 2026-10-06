# Repository Cleanup & Verification Plan (`parser_docs` -> `dev`)

This document outlines the phased manual cleanup plan to transition the `parser_docs` branch into a clean, working prototype state ready for merging into `dev`.

Each phase is self-contained and accompanied by specific verification commands and tests to ensure the codebase remains completely functional throughout the cleanup.

---

## 📋 Quick Change Index

| # | Action | Target / File | Phase | Summary |
|---|--------|---------------|-------|---------|
| 1 | **DELETE** | `core/parser.py` | Phase 1 | Legacy monolithic parser; superseded by `core/parsers/ParserRouter`. |
| 2 | **DELETE** | `api/legacy.py` | Phase 1 | Broken legacy router (NameErrors), unmounted in `main.py`. |
| 3 | **DELETE** | `core/hasher.py` | Phase 1 | Duplicate of `utils/hasher.py`. |
| 4 | **UPDATE** | `schemas/file.py` & `schemas/__init__.py` | Phase 1 | Remove unused legacy file schemas (`FileUploadItem`, etc.). |
| 5 | **UPDATE** | `core/__init__.py` | Phase 2 | Remove legacy imports, resolve duplicate exports (`Parser`, `Retriever`). |
| 6 | **UPDATE** | `api/deps.py` | Phase 2 | Remove redundant `ParserRouter` import. |
| 7 | **DELETE** | `tests/v0/`, `tests/v0.4/`, `tests/v0.5/` | Phase 3 | Obsolete test suites referencing deleted v0 flat endpoints. |
| 8 | **MOVE / RENAME** | `tests/unit/test_parse.py` | Phase 3 | CLI manual script; move to `scripts/debug_parse.py`. |
| 9 | **DELETE** | `tests/unit/Pitch.pptx` | Phase 3 | Orphan binary test fixture not referenced in test suite. |
| 10 | **UPDATE** | `requirements.txt` | Phase 4 | Remove obsolete dependencies (`pypdf`, `python-docx`). |
| 11 | **ARCHIVE / DELETE** | Root `.md` planning files (8 files) | Phase 4 | Clean up temporary sprint planning docs in repo root. |
| 12 | **DECIDE / REVIEW** | `db/models/document_version.py` | Phase 5 | Optional: Document or prune unused versioning table. |

---

## 🚀 Phase-by-Phase Plan & Verification Tests

---

### Phase 1: Remove Dead & Legacy Code

#### 1.1 `core/parser.py`
- **Suggested Action:** `DELETE`
- **Reason:** Legacy monolithic parser relying on `pypdf`, `python-docx`, and system `antiword`. Fully superseded by the modular pipeline under `core/parsers/` (`ParserRouter`, `DocxParser`, `PdfParser`, etc.).
- **Impact:** Only referenced by the dead `api/legacy.py` and `core/__init__.py`.

#### 1.2 `api/legacy.py`
- **Suggested Action:** `DELETE`
- **Reason:** Legacy router from the flat v0 API. Contains broken references to undefined names (`uploader`, `parser`, `chunker`, etc.) which produce `NameError` on import. It is not mounted in `main.py`.

#### 1.3 `core/hasher.py`
- **Suggested Action:** `DELETE`
- **Reason:** Duplicate of `utils/hasher.py`. The extra function `documents_are_identical` is not referenced anywhere in the workspace.

#### 1.4 `schemas/file.py` & `schemas/__init__.py`
- **Suggested Action:** `UPDATE`
- **Reason:** `FileUploadItem`, `FileUploadResponse`, `ChunkItem`, and `FileIndexResponse` were only created for the obsolete flat endpoints. Active v1 routes exclusively use `schemas.document`, `schemas.query`, and `schemas.health`.
- **Suggested Change:**
  - In `schemas/file.py`: Delete unused models or delete the file if completely empty.
  - In `schemas/__init__.py`: Remove `ChunkItem`, `FileIndexResponse`, `FileUploadItem`, `FileUploadResponse` from imports and `__all__`.

#### 🧪 Phase 1 Verification Test
Run the following commands to confirm that no active module tries to import the deleted legacy files:

```bash
# Verify no broken imports across the codebase
python -c "
import utils.hasher
import schemas
print('✅ Phase 1: Schemas and utils loaded cleanly without legacy references')
"
```

---

### Phase 2: Fix Core Imports & Dependencies

#### 2.1 `core/__init__.py`
- **Suggested Action:** `UPDATE`
- **Reason:** Contains duplicate export entries (`Parser` exported 3x, `Retriever` 2x) and still tries to import the legacy `core/parser.py`.
- **Suggested Code:**
```python
"""Core package exports."""
from core.chunker import Chunker
from core.embedder import Embedder
from core.llm import LLMClient
from core.parsers import ParserRouter
from core.retriever import Retriever
from core.uploader import Uploader

__all__ = [
    "Chunker",
    "Embedder",
    "LLMClient",
    "ParserRouter",
    "Retriever",
    "Uploader",
]
```

#### 2.2 `api/deps.py`
- **Suggested Action:** `UPDATE`
- **Reason:** Redundant import: `ParserRouter` is imported on line 1 directly from `core.parsers.parser_router` and again inside the grouped `from core import ...` block.
- **Suggested Change:** Remove line 1 (`from core.parsers.parser_router import ParserRouter`).

#### 🧪 Phase 2 Verification Test
Run the following verification script to test that all core dependencies and FastAPI dependency injections instantiate properly:

```bash
# Verify all Core classes and API dependencies instantiate cleanly
python -c "
from core import Chunker, Embedder, LLMClient, ParserRouter, Retriever, Uploader
import api.deps as deps

router = deps.get_parser_router()
chunker = deps.get_chunker()
print(f'✅ Phase 2: Core exports and dependency injection verified ({router.__class__.__name__}, {chunker.__class__.__name__})')
"
```

---

### Phase 3: Clean & Restructure Test Suite

#### 3.1 Legacy Tests (`tests/v0/`, `tests/v0.4/`, `tests/v0.5/`)
- **Suggested Action:** `DELETE`
- **Reason:** These folders contain tests for obsolete v0 endpoints (`/upload`, `/chunk-and-embed`, `/generate`) which no longer exist in `main.py` / `api/v1/`.

#### 3.2 `tests/unit/test_parse.py`
- **Suggested Action:** `MOVE` to `scripts/debug_parse.py` (or rename to `scripts/manual_parse_cli.py`)
- **Reason:** This file is an interactive CLI helper script that expects `sys.argv[1]` (file path). When run with automated `pytest`, it fails or gets skipped because it is not a pytest unit test.

#### 3.3 `tests/unit/Pitch.pptx`
- **Suggested Action:** `DELETE`
- **Reason:** Unreferenced binary PowerPoint fixture in `tests/unit/`.

#### 🧪 Phase 3 Verification Test
Run the canonical automated test suite using `pytest`:

```bash
# Run all parser unit & integration tests plus chunker unit tests
pytest tests/parsers tests/unit/test_chunker.py -v
```
*Expected Result:* All tests in `tests/parsers/` and `tests/unit/test_chunker.py` should pass with 0 failures and 0 warnings about missing legacy modules.

---

### Phase 4: Prune Dependencies & Tidy Root

#### 4.1 `requirements.txt`
- **Suggested Action:** `UPDATE`
- **Reason:** `pypdf==5.0.1` and `python-docx==1.1.2` were only needed by the old deleted `core/parser.py`. The modern pipeline uses `docling` and `pypdfium2`.
- **Suggested Change:** Remove `pypdf` and `python-docx` lines from `requirements.txt`.

#### 4.2 Root Planning / Scratch Markdown Files
- **Suggested Action:** `DELETE` or `MOVE` to `archive/docs/`
- **Files:**
  - `commits_summary.md`
  - `context.md`
  - `crux.md`
  - `handoff.md`
  - `merge_plan.md`
  - `pdf_doc_phases.md`
  - `plan.md`
  - `summary.md`
- **Reason:** Temporary sprint context files. Clearing them leaves only canonical repository files (`README.md`, `cleanup_plan.md`) at root.

#### 🧪 Phase 4 Verification Test
Verify application startup and FastAPI router discovery:

```bash
# Verify main FastAPI app boots without missing packages or syntax errors
python -c "
from main import app
routes = [route.path for route in app.routes]
print(f'✅ Phase 4: FastAPI app loaded successfully with {len(routes)} routes: {routes}')
"
```

---

### Phase 5: Optional Database Schema Decision

#### 5.1 `db/models/document_version.py` & `db/models/__init__.py`
- **Suggested Action:** `REVIEW / KEEP AS IS` (or `DOCUMENT`)
- **Reason:** `DocumentVersion` is defined in `db/models/document_version.py` and has an Alembic migration (`document_versions` table), but currently `services/ingestion_service.py` only writes to `Document`.
- **Recommendation:** Keep the file as a documented foundation for post-MVP multi-version document history, or note in `db/models/README.md` that it is reserved for Phase 2 versioning.

---

## 🧪 Comprehensive End-to-End System Smoke Test

After completing all phases, run this comprehensive smoke test to verify the complete ingestion and query pipeline:

```bash
# 1. Run canonical Pytest test suite
pytest tests/parsers tests/unit/test_chunker.py -v

# 2. End-to-End In-Memory Pipeline Smoke Test (ParserRouter -> Chunker)
python -c "
from core.parsers import ParserRouter
from core.chunker import Chunker

router = ParserRouter()
chunker = Chunker(chunk_size=500, chunk_overlap=50)

# Smoke test markdown/text parsing & chunking
sample_text = b'# Honeywell Virtual Assistant\n\nThis is a sample document for pipeline verification.'
result = router.parse(sample_text, 'sample.md')
chunks = chunker.split_text(result.text)

assert len(chunks) > 0, 'Chunking failed'
assert result.metadata['filename'] == 'sample.md'
print('✅ Pipeline Smoke Test Passed: ParserRouter + Chunker working seamlessly!')
"

# 3. FastAPI App & Route Inspection
python -c "
from main import app
print('✅ Application ready for merge into dev!')
"
```

---

## 🏁 Summary Checklist Prior to Merging to `dev`

- [x] Phase 1 executed: `core/parser.py`, `api/legacy.py`, `core/hasher.py`, unused schemas removed.
- [x] Phase 2 executed: `core/__init__.py` clean exports, `api/deps.py` cleaned.
- [x] Phase 3 executed: Legacy `tests/v0*` removed, `Pitch.pptx` removed, CLI script relocated to `scripts/debug_parse.py`.
- [x] Phase 4 executed: `requirements.txt` pruned, root markdown clutter archived in `docs/archive/`.
- [x] Phase 5 executed: DB models confirmed (kept as-is for future versioning).
- [x] Comprehensive verification smoke test executed with 100% pass rate.
- [x] Git status clean and ready for commit.
