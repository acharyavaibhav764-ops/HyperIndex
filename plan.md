# Option B: Strict YAGNI & Lean Deduplication Architecture Plan
**Branch Target:** `v0.5_upd` -> `main`  
**Philosophy:** "You Aren't Gonna Need It" (YAGNI). Deliver a concise, production-ready codebase containing *only* features that actually work, eliminating all half-baked versioning scaffolding, ghost columns, and dead code.

---

## 1. Executive Summary & Rationale

* **The Problem:** 
  The codebase currently has a two-table relational structure (`documents` and `document_versions`) with foreign keys, cascade deletes, and versioning metadata (`version_number=1`, `version_message="You are uploading version 1"`, `version_id`). However, **multi-versioning is not implemented**. All non-duplicate uploads simply create new version 1 records.
* **The Solution (Option B):** 
  Strip away the speculative versioning tables and hardcoded version messages. Consolidate into a **single, lean `documents` table** focused purely on what works: **rock-solid SHA-256 deduplication and product isolation**.
* **Benefits:**
  * **Zero Dead Columns:** No fake version numbers, no unused foreign keys, no ghost indexes.
  * **High Performance:** Deduplication becomes an indexed single-table lookup instead of a relational SQL `JOIN`.
  * **Honest API Contracts:** Clients receive clear `"indexed"` vs `"duplicate"` responses without confusing fake version numbers.
  * **Clean Future Path:** When multi-versioning is built in the future, it can be designed correctly from scratch along with ChromaDB vector lifecycle management.

---

## 2. Architecture Comparison

### Before (Speculative & Half-Baked)
```
[documents] 
   └── document_id (PK)
   └── product_id
   └── title
   └── current_version_id (UUID, never used)
          │
          ▼ (1-to-many JOIN)
[document_versions]
   └── version_id (PK)
   └── document_id (FK)
   └── version_number (Always hardcoded to 1)
   └── sha256 (Indexed)
   └── normalized_hash (Unused, 100% NULL)
   └── object_key (Duplicate of document_id)
   └── status (Always "indexed")
```

### After (Option B - Pure Minimalism)
```
[documents]
   ├── document_id (PK, UUID)
   ├── product_id (Indexed)
   ├── filename
   ├── sha256 (Indexed)
   ├── size_bytes
   └── created_at (Timestamp)
```

---

## 3. Concrete Implementation Steps

### Step 1: Database Model & Alembic Migration

1. **Delete `db/models/document_version.py`:**
   * Remove the entire file.
2. **Update `db/models/document.py`:**
   ```python
   from datetime import datetime
   from sqlalchemy import DateTime, Integer, String, func
   from sqlalchemy.orm import Mapped, mapped_column
   from db.database import Base

   class Document(Base):
       __tablename__ = "documents"

       document_id: Mapped[str] = mapped_column(String(255), primary_key=True)
       product_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
       filename: Mapped[str] = mapped_column(String(512), nullable=False)
       sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
       size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
       created_at: Mapped[datetime] = mapped_column(
           DateTime(timezone=True), server_default=func.now(), nullable=False
       )
   ```
3. **Update `db/models/__init__.py`:**
   * Export only `Document`.
4. **Single Clean Alembic Migration (`alembic/versions/20260925_0001_initial.py`):**
   * Creates only the `documents` table with indexes on `product_id` and `sha256`.

---

### Step 2: Clean API Schema Contract (`schemas/document.py`)

Remove all speculative version attributes from the response model:
```python
from pydantic import BaseModel, Field

class DocumentIngestItem(BaseModel):
    document_id: str = Field(..., description="Unique document identifier in object storage")
    product_id: str = Field(..., description="Product identifier")
    filename: str = Field(..., description="Original filename")
    size_bytes: int = Field(..., description="File size in bytes")
    collection: str = Field(..., description="ChromaDB collection name")
    total_chunks: int = Field(..., description="Number of chunks generated and indexed")
    status: str = Field(..., description="Ingestion status: 'indexed' or 'duplicate'")

class DocumentIngestResponse(BaseModel):
    message: str
    count: int
    documents: list[DocumentIngestItem]
```

---

### Step 3: Streamlined `IngestionService` (`services/ingestion_service.py`)

Single-table duplicate check with zero unnecessary `JOIN`s:
```python
# 1. Deduplication Check:
if self.db is not None:
    existing_doc = self.db.scalar(
        select(Document).where(
            Document.sha256 == file_hash,
            Document.product_id == product_id,
        )
    )
    if existing_doc is not None:
        ingested_items.append(
            DocumentIngestItem(
                document_id=existing_doc.document_id,
                product_id=existing_doc.product_id,
                filename=getattr(file, "filename", None) or existing_doc.filename,
                size_bytes=len(content),
                collection=self.retriever.collection_name,
                total_chunks=0,
                status="duplicate",
            )
        )
        continue

# 2. Ingest New Document:
# Run upload -> parse -> chunk -> embed -> upsert to ChromaDB...

# 3. Record in Database:
if self.db is not None:
    doc_record = Document(
        document_id=doc_id,
        product_id=product_id,
        filename=filename,
        sha256=file_hash,
        size_bytes=size_bytes,
    )
    self.db.add(doc_record)
    self.db.commit()

ingested_items.append(
    DocumentIngestItem(
        document_id=doc_id,
        product_id=product_id,
        filename=filename,
        size_bytes=size_bytes,
        collection=self.retriever.collection_name,
        total_chunks=len(chunks),
        status="indexed",
    )
)
```

---

### Step 4: Dead File & Repository Cleanup

1. **Delete Empty Root File:**
   * Remove 0-byte `design_version_plan.md` in root.
2. **Utils Separation:**
   * Keep `utils/hasher.py` with `calculate_sha256`.
   * Keep `core/` strictly focused on RAG pipeline components.
3. **Clean Up Tests:**
   * Update `tests/v0.4/v0.4.3/test_duplicate_uploads.py` to assert against `Document` instead of `DocumentVersion`.
   * Remove or archive obsolete prototype test directories (`tests/v0.3/`, `tests/v0.4/v0.4.1/`, `tests/v0.4/v0.4.2/`) so `pytest` runs 100% green across the entire workspace.

---

## 4. Verification & Quality Protocol

1. **Database Migration Verification:**
   * Test clean application of the single migration: `alembic upgrade head`.
2. **Unit & Service Testing:**
   * Verify all active service tests and duplicate upload tests pass with 0 warnings or errors.
3. **Git Cleanliness:**
   * Verify `git status` contains zero untracked or ghost files before pushing to `main`.
