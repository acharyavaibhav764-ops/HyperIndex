# CRUD Implementation Versions & Rollout Plan

This document outlines the independent, incrementally pushable versions for implementing the full Document Lifecycle CRUD defined in [`docs/crud.md`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/docs/crud.md).

Adhering to **Separation of Concerns**, the low-level **`core/`** modules (`retriever.py`, `uploader.py`) remain completely untouched as pure RAG engine and storage gateways. All document lifecycle, multi-store cascades, and business logic live in the dedicated **Service Layer** (`services/document_service.py`).

---

## Rollout Overview

```text
┌────────────────────────────────────────────────────────────────────────┐
│                            CRUD Version Map                            │
├───────────────┬──────────────────────────┬─────────────────────────────┤
│ Version       │ Focus                    │ Scope                       │
├───────────────┼──────────────────────────┼─────────────────────────────┤
│ CRUD v1.0     │ Service & Schemas Layer  │ schemas/ & document_service │
├───────────────┼──────────────────────────┼─────────────────────────────┤
│ CRUD v2.0     │ Read Operations (API)    │ GET endpoints (List/Chunks) │
├───────────────┼──────────────────────────┼─────────────────────────────┤
│ CRUD v3.0     │ Mutation & Cascade (API) │ DELETE & PATCH endpoints    │
└───────────────┴──────────────────────────┴─────────────────────────────┘
```

---

## Version Breakdown

### 🔷 CRUD v1.0: Document Service Layer & Schemas
**Goal**: Build the complete, isolated document lifecycle business logic in `services/document_service.py` and decoupled schemas across `schemas/ingestion.py` and `schemas/document.py`, keeping `core/` untouched.

* **Components Touched**:
  * `schemas/ingestion.py` [NEW]
  * `schemas/document.py` [UPDATE]
  * `schemas/__init__.py` [UPDATE]
  * `services/document_service.py` [NEW]
  * `api/deps.py`
  * `tests/unit/test_document_service.py` [NEW]
* **Deliverables**:
  1. **Modular Schemas**:
     * `schemas/ingestion.py`: `DocumentIngestItem`, `DocumentIngestResponse`
     * `schemas/document.py`: `DocumentDescription`, `GetDocumentsResponse`, `ChunkDescription`, `GetDocumentChunksResponse`, `UpdateDocumentRequest`, `DeleteDocumentResponse`
     * `schemas/__init__.py`: Centralized re-exports
  2. **Dedicated Service** `DocumentService` in `services/document_service.py`:
     * `list_documents(...)`: Query SQLite with filters (`product_id`, `name_search`, date bounds) and live Chroma chunk counts.
     * `get_document(document_id)`: Single document metadata retrieval.
     * `get_document_chunks(document_id, limit, offset)`: Fetch chunk text, pages, and chunk IDs from Chroma.
     * `update_document_metadata(document_id, product_id)`: Update SQLite record and synchronize Chroma chunk metadata.
     * `delete_document(document_id)`: Cascade deletion in strict sequence:
       - Step 1: Purge Chroma vectors (halts RAG retrieval immediately).
       - Step 2: Delete SQLite row (liberates SHA-256 fingerprint).
       - Step 3: Delete MinIO binary (reclaims physical storage).
  3. **Dependency Injection**: Add `get_document_service` in `api/deps.py`.
* **Testing & Verification**:
  * Unit tests with in-memory SQLite and mocked/ephemeral Chroma and MinIO:
    - Test filtering and pagination.
    - Test chunk extraction and transparency.
    - Test metadata update synchronization.
    - Test cascade deletion order and SHA-256 fingerprint release.
* **Why it can be pushed independently**:
  * `core/` is completely untouched.
  * Encapsulates all domain and business rules into the service layer without modifying existing HTTP routes.

---

### 🔷 CRUD v2.0: Read Endpoints (Listing, Details & Chunks Inspection)
**Goal**: Expose safe, non-mutating HTTP endpoints for document discovery and vector chunk inspection.

* **Components Touched**:
  * `api/v1/endpoints/documents.py`
  * `api/v1/endpoints/ingestion.py` (Switch to direct import from `schemas.ingestion`)
  * `services/ingestion_service.py` (Switch to direct import from `schemas.ingestion`)
  * `schemas/document.py` (Remove backward-compatibility re-exports of `DocumentIngestItem`/`DocumentIngestResponse`)
  * `tests/integration/test_documents_read_api.py` [NEW]
* **Deliverables**:
  1. `GET /api/v1/documents`:
     * Query params: `product_id`, `name_search`, `status`, `uploaded_after`, `uploaded_before`, `limit`, `skip`.
     * Response: `GetDocumentsResponse`.
  2. `GET /api/v1/documents/{document_id}`:
     * Response: `DocumentDescription` (404 if not found).
  3. `GET /api/v1/documents/{document_id}/chunks`:
     * Query params: `limit`, `offset`.
     * Response: `GetDocumentChunksResponse`.
  4. **Purge Backward Compatibility Dependency**:
     * Update `services/ingestion_service.py` and `api/v1/endpoints/ingestion.py` to import directly from `schemas.ingestion`.
     * Completely remove `from schemas.ingestion import DocumentIngestItem, DocumentIngestResponse` from `schemas/document.py`, achieving 100% strict domain isolation without legacy bridge aliases.
* **Testing & Verification**:
  * Test listing documents with pagination (`skip=0, limit=2`).
  * Test case-insensitive substring search (`name_search="manual"`).
  * Test filtering by `product_id`.
  * Test chunk inspection returns correct text, page numbers, and chunk IDs.
* **Why it can be pushed independently**:
  * Introduces purely additive read endpoints.
  * Zero risk of data mutation.
  * Clients and Swagger UI immediately gain visibility into all indexed documents.

---

### 🔷 CRUD v3.0: Mutation & Cascade Deletion Endpoints
**Goal**: Expose the mutating endpoints (`DELETE` and `PATCH`) to complete the full document lifecycle.

* **Components Touched**:
  * `api/v1/endpoints/documents.py`
  * `tests/integration/test_documents_mutation_api.py` [NEW]
  * `README.md` (Update API documentation table and curl examples)
* **Deliverables**:
  1. `DELETE /api/v1/documents/{document_id}`:
     * Executes cascade delete across Chroma, SQLite, and MinIO.
     * Returns `DeleteDocumentResponse` with counts of deleted chunks.
  2. `PATCH /api/v1/documents/{document_id}`:
     * Updates document metadata (`product_id`) across SQLite and Chroma.
     * Returns updated `DocumentDescription`.
  3. Documentation updates in `README.md` for the new endpoints.
* **Testing & Verification**:
  * **End-to-End Lifecycle Test**:
    1. Upload file via `POST /api/v1/documents`.
    2. Confirm present in `GET /api/v1/documents`.
    3. Query question via `POST /api/v1/query` and verify citations.
    4. Call `DELETE /api/v1/documents/{document_id}`.
    5. Query again via `POST /api/v1/query` and verify no citations from the deleted file appear.
    6. Re-upload the exact same file and verify `status: "indexed"` (proving SHA-256 was cleanly liberated).
* **Why it can be pushed independently**:
  * Finalizes the full CRUD lifecycle.
  * Builds on top of thoroughly tested service methods and read routes.
