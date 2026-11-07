# CRUD v3.0 Implementation Plan: Mutation & Cascade Endpoints

## Executive Summary
CRUD v3.0 completes the Document Lifecycle CRUD capability defined in [`docs/crud.md`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/docs/crud.md) and [`docs/crud_versions.md`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/docs/crud_versions.md).

It exposes mutating HTTP routes (`PATCH` and `DELETE`), connecting the API layer directly to the multi-store cascade logic already implemented and verified in `DocumentService`.

---

## 1. Architectural Scope & Invariants

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        CRUD v3.0 Scope Boundary                        │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Core Layer (core/retriever.py, core/uploader.py)                    │
│    └── UNTOUCHED (100% infrastructure isolation maintained)            │
│                                                                        │
│ 2. Schema Layer (schemas/document.py)                                  │
│    └── Consume UpdateDocumentRequest, DeleteDocumentResponse           │
│                                                                        │
│ 3. Service Layer (services/document_service.py)                        │
│    └── Consume update_document_metadata & delete_document cascades     │
│                                                                        │
│ 4. API Endpoints (api/v1/endpoints/documents.py)                       │
│    ├── PATCH  /api/v1/documents/{document_id} (Metadata sync)         │
│    └── DELETE /api/v1/documents/{document_id} (Cascade purge)          │
│                                                                        │
│ 5. Automated Tests                                                     │
│    └── Unit/Integration tests for mutation endpoints (200, 404, 422)   │
│                                                                        │
│ 6. User Documentation                                                  │
│    └── README.md: Document lifecycle API tables and curl examples       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Implementation Phases

### Phase 1: Expose Mutating Routes in `api/v1/endpoints/documents.py`

#### 1. `PATCH /api/v1/documents/{document_id}` *(Update Document Metadata)*
* **Summary**: Update document metadata attributes (`product_id`).
* **Path Parameter**: `document_id: str`
* **Request Body**: `UpdateDocumentRequest` (`product_id: str`)
* **Dependency**: `service: DocumentService = Depends(get_document_service)`
* **Response Model**: `DocumentDescription`
* **Status Code**: `200 OK`
* **Behavior**:
  - Validates request body.
  - Calls `service.update_document_metadata(document_id=document_id, product_id=body.product_id)`.
  - Atomically commits changes to SQLite and updates metadata across all chunks in ChromaDB.
  - Returns 404 if the document does not exist.

#### 2. `DELETE /api/v1/documents/{document_id}` *(Cascade Delete Document)*
* **Summary**: Permanently delete a document across all storage layers.
* **Path Parameter**: `document_id: str`
* **Dependency**: `service: DocumentService = Depends(get_document_service)`
* **Response Model**: `DeleteDocumentResponse`
* **Status Code**: `200 OK`
* **Behavior**:
  - Calls `service.delete_document(document_id=document_id)`.
  - Executes cascade:
    1. Purges Chroma vectors (halts RAG retrieval immediately).
    2. Deletes SQLite row (liberates SHA-256 fingerprint for future re-uploads).
    3. Deletes MinIO binary (frees raw physical storage).
  - Returns `DeleteDocumentResponse` (`document_id`, `status: "deleted"`, `deleted_chunks`, `database_removed: True`, `storage_removed: True`).
  - Returns 404 if the document does not exist.

---

### Phase 2: Comprehensive Test Suite for Mutations
* **Test File**: `tests/unit/test_documents_mutation_api.py`
* **Test Cases**:
  1. `test_update_document_metadata_success`:
     - Verifies `PATCH /api/v1/documents/{document_id}` calls `service.update_document_metadata` with the new `product_id`.
     - Returns updated `DocumentDescription` with 200 OK.
  2. `test_update_document_metadata_not_found`:
     - Non-existent document ID raises 404 HTTPException.
  3. `test_update_document_metadata_validation_error`:
     - Empty body or empty `product_id` returns 422 Unprocessable Entity.
  4. `test_delete_document_success`:
     - Verifies `DELETE /api/v1/documents/{document_id}` calls `service.delete_document`.
     - Returns `DeleteDocumentResponse` with 200 OK.
  5. `test_delete_document_not_found`:
     - Non-existent document ID raises 404 HTTPException.

---

### Phase 3: Documentation Updates (`README.md`)
* Add new Document Lifecycle CRUD API section to `README.md`:
  - `GET /api/v1/documents`
  - `GET /api/v1/documents/{id}`
  - `GET /api/v1/documents/{id}/chunks`
  - `PATCH /api/v1/documents/{id}`
  - `DELETE /api/v1/documents/{id}`
* Add PowerShell `curl.exe` examples for updating metadata and deleting a document.

---

### Phase 4: Full Suite Verification & Final Status Check
1. Run `tests/unit/test_documents_mutation_api.py`.
2. Run entire `tests/unit/` suite (all tests passing).
3. Verify git status and ensure zero unwanted modifications in `core/`.

