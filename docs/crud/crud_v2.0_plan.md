# CRUD v2.0 Implementation Plan: Read Endpoints & Clean Schema Decoupling

## Executive Summary
CRUD v2.0 exposes the read operations of the Document Lifecycle API defined in [`docs/crud.md`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/docs/crud.md) and [`docs/crud_versions.md`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/docs/crud_versions.md).

Furthermore, v2.0 completes the scheduled **elimination of backward-compatibility dependencies**:
1. All ingestion endpoints and services switch to direct imports from [`schemas/ingestion.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/schemas/ingestion.py).
2. The legacy re-export bridge in [`schemas/document.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/schemas/document.py) is permanently purged, enforcing 100% strict domain isolation.

---

## 1. Architectural Scope & Invariants

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        CRUD v2.0 Scope Boundary                        │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Core Layer (core/retriever.py, core/uploader.py)                    │
│    └── UNTOUCHED (100% infrastructure isolation maintained)            │
│                                                                        │
│ 2. Schema Decoupling                                                   │
│    ├── schemas/ingestion.py: Ingest models (DocumentIngestItem, ...)   │
│    └── schemas/document.py:  Lifecycle models ONLY (Bridge removed)   │
│                                                                        │
│ 3. Service Layer (services/document_service.py)                        │
│    └── Consume already tested list_documents, get_document, chunks     │
│                                                                        │
│ 4. API Endpoints (api/v1/endpoints/documents.py)                       │
│    ├── GET /api/v1/documents (List with filters & pagination)          │
│    ├── GET /api/v1/documents/{document_id} (Detailed metadata)        │
│    └── GET /api/v1/documents/{document_id}/chunks (Vector transparency)│
│                                                                        │
│ 5. Automated Tests                                                     │
│    └── Integration tests for all read routes + edge cases (404, empty) │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Implementation Phases

### Phase 1: Purge Backward-Compatibility Dependencies
* **Files to Modify**:
  * [`services/ingestion_service.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/services/ingestion_service.py):
    - Change `from schemas.document import DocumentIngestItem, DocumentIngestResponse`
    - To: `from schemas.ingestion import DocumentIngestItem, DocumentIngestResponse`
  * [`api/v1/endpoints/documents.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/api/v1/endpoints/documents.py):
    - Change `from schemas.document import DocumentIngestResponse`
    - To: `from schemas.ingestion import DocumentIngestResponse`
  * [`schemas/document.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/schemas/document.py):
    - Delete lines importing and re-exporting `DocumentIngestItem` and `DocumentIngestResponse`.
    - Retain only lifecycle models: `DocumentDescription`, `GetDocumentsResponse`, `ChunkDescription`, `GetDocumentChunksResponse`, `UpdateDocumentRequest`, `DeleteDocumentResponse`.
* **Verification**: Run existing tests (`tests/unit/test_document_service.py`) and verify zero regression.

---

### Phase 2: Implement Read Endpoints in `api/v1/endpoints/documents.py`
Add the three non-mutating endpoints to the existing router:

#### 1. `GET /api/v1/documents` (List Documents)
* **Summary**: List indexed documents with filtering and pagination.
* **Query Parameters**:
  - `product_id: Optional[str] = Query(None, description="Filter by product identifier")`
  - `name_search: Optional[str] = Query(None, description="Substring search on filename")`
  - `status: Optional[str] = Query(None, description="Filter by indexing status (e.g. indexed)")`
  - `uploaded_after: Optional[datetime] = Query(None, description="Filter documents uploaded after timestamp")`
  - `uploaded_before: Optional[datetime] = Query(None, description="Filter documents uploaded before timestamp")`
  - `limit: int = Query(50, ge=1, le=100, description="Page size limit")`
  - `skip: int = Query(0, ge=0, description="Offset cursor for pagination")`
* **Dependency**: `service: DocumentService = Depends(get_document_service)`
* **Response Model**: `GetDocumentsResponse`
* **Behavior**: Delegates to `service.list_documents(...)`.

#### 2. `GET /api/v1/documents/{document_id}` (Get Document Details)
* **Summary**: Retrieve detailed metadata for a specific document.
* **Path Parameter**: `document_id: str`
* **Dependency**: `service: DocumentService = Depends(get_document_service)`
* **Response Model**: `DocumentDescription`
* **Behavior**: Delegates to `service.get_document(document_id)`. Returns 404 if not found.

#### 3. `GET /api/v1/documents/{document_id}/chunks` (Inspect Chunks)
* **Summary**: Inspect vector chunks, extracted text, and chunk-level metadata stored in ChromaDB.
* **Path Parameter**: `document_id: str`
* **Query Parameters**:
  - `limit: int = Query(50, ge=1, le=100, description="Maximum number of chunks to return")`
  - `offset: int = Query(0, ge=0, description="Starting offset index for pagination")`
* **Dependency**: `service: DocumentService = Depends(get_document_service)`
* **Response Model**: `GetDocumentChunksResponse`
* **Behavior**: Delegates to `service.get_document_chunks(document_id, limit, offset)`. Returns 404 if document is not found.

---

### Phase 3: Comprehensive Integration Testing
* **Test File**: `tests/integration/test_documents_read_api.py`
* **Fixtures**:
  - `TestClient(app)` with database session overrides.
  - Injected sample records into SQLite and mock/in-memory ChromaDB chunks.
* **Test Matrix**:
  1. `test_list_documents_empty`: Returns `total_count=0, documents=[]`.
  2. `test_list_documents_pagination`: Tests `limit=2, skip=0` and `skip=2` cursor boundaries.
  3. `test_list_documents_filter_by_product_id`: Confirms only documents with specified `product_id` are returned.
  4. `test_list_documents_name_search`: Substring search matching filename.
  5. `test_get_document_by_id_success`: Fetches document metadata.
  6. `test_get_document_by_id_404`: Non-existent UUID returns 404 with standard error detail.
  7. `test_get_document_chunks_success`: Validates returned `total_chunks`, chunk text, page, and chunk IDs.
  8. `test_get_document_chunks_404`: Non-existent document ID returns 404.
  9. `test_schema_isolation_cleanliness`: Asserts `DocumentIngestResponse` is not present in `schemas.document`.

---

### Phase 4: Final Verification & Health Checks
1. Execute `tests/integration/test_documents_read_api.py`.
2. Run full unit suite: `tests/unit/`.
3. Check FastAPI documentation (`/openapi.json`) to confirm query parameters, docstrings, and response models render accurately.

