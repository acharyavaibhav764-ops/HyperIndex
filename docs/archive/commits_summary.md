# Repository Commit Summary

This document outlines the architectural changes, code additions, and refactoring introduced in two major merges into the `parser_docs` branch. 

---

## 1. Commit `199c7bb4c13a` — The v0.5 Service-Layer & Database Refactor
**Summary:** 53 files changed, 2,645 insertions(+), 131 deletions(-).
This merge laid the structural foundation for the application, stripping raw logic out of the FastAPI endpoints and moving it into a dedicated service layer, along with initializing an SQL database for document tracking.

### A. Database & Migrations (`alembic/`, `db/`)
*   **Alembic Initialized:** Added the `alembic/` directory and `alembic.ini` to handle SQL schema migrations.
*   **SQLAlchemy Setup:** Created `db/database.py` and `db/session.py` to handle engine creation and connection pooling.
*   **SQL Models:** Introduced two primary tables:
    *   `Document` (`db/models/document.py`)
    *   `DocumentVersion` (`db/models/document_version.py`)

### B. The Service Layer (`services/`)
*   **`IngestionService`:** Created `services/ingestion_service.py` to handle the full pipeline: deduplication via SHA-256 hashing, uploading, parsing, chunking, embedding, and SQL persistence.
*   **`RAGService`:** Created `services/rag_service.py` to handle semantic search queries and LLM generation.

### C. API & Dependency Injection (`api/`)
*   **Dependency Registry:** Refactored dependency injection by creating `api/deps.py`, which sets up cached singletons (like `ParserRouter` and `Uploader`) and service initializers (`get_ingestion_service`).
*   **Endpoint Clean-Up:** `api/v1/endpoints/documents.py` and `api/v1/endpoints/query.py` were heavily refactored to simply accept HTTP requests and immediately delegate to the new service layer.

### D. Testing & Utilities (`tests/`, `utils/`)
*   **Hashing:** Added `utils/hasher.py` to calculate SHA-256 hashes for deduplication.
*   **Robust Test Suites:** Added extensive tests (`test_api_v1_services.py`, `test_services.py`, `test_duplicate_uploads.py`) to validate the new injection models and duplicate-blocking logic.
*   **Test Assets:** Committed 8 binary `.pdf` files to `documents/Documents/` for testing complex parser ingestion.

---

## 2. Commit `e1786911f6e0` — ParserRouter Integration & Migration Consolidation
**Summary:** 14 files changed, 362 insertions(+), 129 deletions(-).
This subsequent commit tied the newly built `ParserRouter` into the active ingestion flow, consolidated messy SQL migrations, and added agent skills documentation.

### A. Parser Integration (`core/`, `services/`)
*   **`core/chunker.py`:** Adjusted chunking logic to support the AST objects (like `DoclingDocument`) being emitted by the new parsers.
*   **`services/ingestion_service.py` & `api/legacy.py`:** Wired the `ParserRouter` into the ingestion flow for TXT, MD, DOCX, and PPTX pipelines.

### B. Alembic Migration Consolidation (`alembic/`, `db/`)
*   **Migration Squashing:** Deleted the two messy initial migrations (`20260925_0001_initial.py` and `20260926_0002_make_normalized_hash_optional.py`).
*   **Consolidated Revision:** Replaced them with a single, clean migration file (`b3801174c558_initial.py`) that sets up the `Document` and `DocumentVersion` tables with all the correct nullable properties in one shot.
*   **Model Tweaks:** Updated `db/models/document.py` and `db/models/document_version.py` to map accurately to the squashed migration.

### C. Application Startup (`main.py`)
*   **Refactor:** Heavily modified `main.py` (99 lines changed) to ensure the database engines and dependencies boot up correctly alongside the FastAPI instance.

### D. Documentation & Custom Skills (`skills/`)
*   **Handoff Docs:** Added `handoff.md` to document current state and next steps for the team.
*   **Agent Skills:** Introduced a `skills/skill-authoring/` directory with a `SKILL.md` instruction file and a `skills/skills_index.json`. This gives agentic assistants predefined workflows for interacting with the repository.
