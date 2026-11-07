# Qdrant Migration: Incremental Version & Rollout Plan

This document outlines the phased, incrementally committable versions for executing the ChromaDB to Qdrant migration defined in [`docs/qdrant_plan.md`](file:///home/prathamgbhat/Desktop/honeywell-virtual-assistant/docs/qdrant_plan.md).

To ensure production stability and zero downtime, the migration is structured into **5 distinct, self-contained versions**. Each version can be reviewed, tested, and pushed in an independent git commit without breaking existing application workflows or leaving the repository in an unrunnable state.

---

## Rollout Overview

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 Qdrant Migration Roadmap                               │
├──────────────┬──────────────────────────────────────────┬──────────────────────────────┤
│ Version      │ Focus                                    │ Scope                        │
├──────────────┼──────────────────────────────────────────┼──────────────────────────────┤
│ Qdrant v1.0  │ Embeddings Decoupling & Dependencies    │ requirements, embeddings.py  │
├──────────────┼──────────────────────────────────────────┼──────────────────────────────┤
│ Qdrant v2.0  │ Infra, Config & Core Qdrant Retriever    │ docker-compose, config, core │
├──────────────┼──────────────────────────────────────────┼──────────────────────────────┤
│ Qdrant v3.0  │ Ingestion & RAG Pipeline Integration     │ ingestion & rag services     │
├──────────────┼──────────────────────────────────────────┼──────────────────────────────┤
│ Qdrant v4.0  │ Document Service CRUD Migration          │ document_service & mocks     │
├──────────────┼──────────────────────────────────────────┼──────────────────────────────┤
│ Qdrant v5.0  │ Chroma Deprecation, Cleanup & Docs       │ docker, env, docs & cleanup  │
└──────────────┴──────────────────────────────────────────┴──────────────────────────────┘
```

---

## Version Breakdown

---

### 🔷 Qdrant v1.0: Embeddings Decoupling & Dependency Setup
**Goal**: Decouple `core/embeddings.py` from ChromaDB's internal `embedding_functions` and introduce `qdrant-client` into the project dependencies, keeping the rest of the application completely unchanged.

* **Components Touched**:
  * `requirements.txt` [UPDATE]
  * `core/embeddings.py` [UPDATE]
  * `tests/unit/test_embeddings.py` [UPDATE]

* **Deliverables**:
  1. **Direct SentenceTransformer Integration**:
     - Remove `from chromadb.utils.embedding_functions import DefaultEmbeddingFunction, SentenceTransformerEmbeddingFunction`.
     - Replace with native `sentence_transformers.SentenceTransformer` (or lightweight fallback).
     - Maintain the exact public interface: `embed(texts: list[str]) -> list[list[float]]`.
  2. **Dependencies**:
     - Add `qdrant-client>=1.12.0` and `sentence-transformers>=3.0.0` to `requirements.txt`.
     - Keep `chromadb` temporarily so existing endpoints and services continue running without interruption.
  3. **Unit Tests**:
     - Refactor `tests/unit/test_embeddings.py` to assert embeddings generation without Chroma utilities.

* **Testing & Verification**:
  ```bash
  pytest tests/unit/test_embeddings.py
  ```
  - Verify that embeddings are generated accurately for CPU/GPU device configurations.
  - Verify that existing ingestion and search endpoints remain functional.

* **Commit Message Template**:
  `feat(embeddings): decouple Embeddings from Chroma and add qdrant-client dependency`

---

### 🔷 Qdrant v2.0: Infrastructure, Configuration & Core Retriever
**Goal**: Provision the Qdrant service in Docker, add unified configuration settings, and implement the core `Qdrant`-backed `Retriever` with support for both in-memory testing and networked production modes.

* **Components Touched**:
  * `docker-compose.yml` [UPDATE]
  * `.env.example` [UPDATE]
  * `config.py` [UPDATE]
  * `core/retriever.py` [UPDATE]
  * `tests/unit/test_retriever.py` [NEW / UPDATE]

* **Deliverables**:
  1. **Infrastructure**:
     - Add `qdrant` service in `docker-compose.yml` on port `6333:6333` with volume `qdrant_data:/qdrant/storage`.
     - Configure healthcheck pointing to `http://localhost:6333/readyz`.
  2. **Configuration**:
     - Add `qdrant_host`, `qdrant_port`, `qdrant_path`, `qdrant_collection` to `config.py` and `.env.example`.
  3. **Core `Retriever` Engine**:
     - Rewrite `core/retriever.py` to wrap `QdrantClient`:
       - If `qdrant_host` is specified: connect via HTTP client (`QdrantClient(host=..., port=...)`).
       - If `qdrant_path` is specified: connect via local directory or in-memory (`QdrantClient(path=...)` or `":memory:"`).
     - **Collection Setup**: Auto-create collection with `models.VectorParams(size=768, distance=models.Distance.COSINE)` upon initialization.
     - **Deterministic Point IDs**: Convert chunk string IDs into deterministic UUIDv5s (`uuid.uuid5(uuid.NAMESPACE_DNS, chunk_id)`).
     - **`upsert(ids, documents, metadatas, embeddings)`**: Upload points with full payload dictionaries.
     - **`retrieve(query, k)`**: Execute vector search via `client.query_points()` and return normalized dictionary:
       `{"documents": [docs], "metadatas": [metas], "distances": [dists]}`.

* **Testing & Verification**:
  - Run unit tests with `QdrantClient(":memory:")` verifying collection auto-creation, upserting, and vector retrieval without requiring Docker.
  - Test health check endpoint in Docker:
    ```bash
    curl -I http://localhost:6333/readyz
    ```

* **Commit Message Template**:
  `feat(retriever): implement Qdrant-backed Retriever and add docker infrastructure`

---

### 🔷 Qdrant v3.0: Ingestion & RAG Pipeline Integration
**Goal**: Connect `IngestionService` and `RAGService` to the new Qdrant retriever, verifying that document ingestion and Ollama-grounded querying operate seamlessly.

* **Components Touched**:
  * `services/ingestion_service.py` [UPDATE]
  * `services/rag_service.py` [UPDATE]
  * `api/v1/endpoints/query.py` [UPDATE docs/descriptions]
  * `api/v1/endpoints/documents.py` [UPDATE docs/descriptions]
  * `tests/parsers/test_integration.py` [UPDATE]

* **Deliverables**:
  1. **Ingestion Pipeline**:
     - Ensure `IngestionService.process_document` uploads chunks, metadata, and vectors to Qdrant.
     - Retain SQLite record creation (`Document` model) with identical SHA-256 deduplication logic.
     - Verify rich payload format (storing `document_id`, `product_id`, `filename`, `page_numbers`, and chunk text).
  2. **RAG Pipeline**:
     - Ensure `RAGService.answer_question` queries Qdrant vectors and correctly formats sources and distances.
     - Verify Ollama prompt construction receives top-k chunks with complete source citations.
  3. **Endpoint Verification**:
     - `POST /api/v1/documents` indexes into Qdrant.
     - `POST /api/v1/query` returns grounded answers from Qdrant vectors.

* **Testing & Verification**:
  - Upload a test PDF / document via `POST /api/v1/documents` and verify points appear in Qdrant:
    ```bash
    curl http://localhost:6333/collections/my_documents/points/count
    ```
  - Send a question to `POST /api/v1/query` and verify valid grounded response from Ollama.

* **Commit Message Template**:
  `feat(pipeline): integrate IngestionService and RAGService with Qdrant`

---

### 🔷 Qdrant v4.0: Document Service CRUD Migration
**Goal**: Migrate all document lifecycle operations (`list`, `get_chunks`, `update_metadata`, and cascading `delete`) in `services/document_service.py` to native Qdrant filter and payload operations.

* **Components Touched**:
  * `services/document_service.py` [UPDATE]
  * `tests/unit/test_document_service.py` [UPDATE]
  * `tests/unit/test_documents_mutation_api.py` [UPDATE]
  * `tests/unit/test_documents_read_api.py` [UPDATE]

* **Deliverables**:
  1. **Efficient Chunk Counting** (`list_documents`, `get_document`):
     - Replace Chroma `len(collection.get()["ids"])` with Qdrant's high-speed `client.count(collection_name, count_filter=Filter(...))` call.
  2. **Chunk Discovery & Inspection** (`get_document_chunks`):
     - Use `client.scroll()` with `limit` and `offset` filters for paginated chunk reading.
  3. **Atomic Payload Updates** (`update_document_metadata`):
     - Replace the multi-step fetch-modify-rewrite loop with a single atomic call:
       `client.set_payload(collection_name, payload={"product_id": product_id}, points=Filter(...))`.
  4. **Cascade Deletion** (`delete_document`):
     - Replace `collection.delete(where=...)` with Qdrant's `client.delete(points_selector=FilterSelector(...))`.
  5. **Mock & Unit Test Updates**:
     - Update mock fixtures in `tests/unit/test_document_service.py` to emulate Qdrant's `count()`, `scroll()`, `set_payload()`, and `delete()` responses.

* **Testing & Verification**:
  ```bash
  pytest tests/unit/test_document_service.py
  ```
  - Verify that updating `product_id` updates both SQLite and Qdrant points.
  - Verify that deleting a document purges vectors from Qdrant, rows from SQLite, and binaries from MinIO.

* **Commit Message Template**:
  `refactor(service): migrate DocumentService CRUD operations to Qdrant native APIs`

---

### 🔷 Qdrant v5.0: Chroma Deprecation, Cleanup & Final Polish
**Goal**: Completely remove all remaining ChromaDB references, purge obsolete configuration variables, update developer documentation, and establish the clean baseline for future hybrid search.

* **Components Touched**:
  * `requirements.txt` [UPDATE: remove `chromadb`]
  * `docker-compose.yml` [UPDATE: remove `chroma` service and volume]
  * `config.py` [UPDATE: delete `chroma_*` attributes]
  * `.env` / `.env.example` [UPDATE: purge `CHROMA_*` keys]
  * `.gitignore` [UPDATE: remove `chroma_data/`, add `qdrant_data/`]
  * `README.md` [UPDATE: badges, diagrams, service tables, and curl examples]
  * `docs/archive/` [UPDATE: archive any legacy Chroma references]

* **Deliverables**:
  1. **Dependency Cleanup**:
     - Remove `chromadb` from `requirements.txt`.
     - Remove `chroma_data` volume from `docker-compose.yml`.
  2. **Configuration Cleanliness**:
     - Purge all dead `CHROMA_*` settings from code and documentation.
  3. **Updated Documentation**:
     - Update architecture diagrams in `README.md` to reflect Qdrant on port 6333.
     - Document Qdrant Web Dashboard URL (`http://localhost:6333/dashboard`).
  4. **Embeddings Consolidation**:
     - Collapse `SentenceTransformerCallable` directly into `Embeddings`.
     - Eliminate transitional `__call__` wrapper and redundant list conversions since Qdrant takes vectors directly without Chroma's callback protocol.
  5. **Full Test Suite Run**:
     - Ensure the entire test suite passes cleanly with zero Chroma dependencies.

* **Testing & Verification**:
  ```bash
  git grep -i "chroma" -- ':!docs/'
  ```
  - Verify zero active code references to Chroma in `core/`, `services/`, `api/`, or `config.py`.
  - Full end-to-end stack startup:
    ```bash
    docker compose down -v
    docker compose up -d
    ```
  - Confirm all 4 containers (`api`, `qdrant`, `minio`, `ollama`) start cleanly and pass health checks.

* **Commit Message Template**:
  `chore: remove ChromaDB dependencies, clean configuration, and update documentation`

---

## Workflow & Commit Checklist

All changes are implemented sequentially on the working branch without creating separate feature branches. Each version is prepared, tested, and handed over for the user to commit manually:

- [ ] Implement version deliverables sequentially on the active branch.
- [ ] Run test suite and manual verification for that milestone.
- [ ] User reviews the changes and executes `git commit` using the provided commit message template.
- [ ] Proceed to the next version milestone.

