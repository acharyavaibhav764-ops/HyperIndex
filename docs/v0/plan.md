# Project Plan: Make It Right

> **Philosophy**: *Make it work, make it right, make it fast.*  
> **Current Status**: v0.1 (Working Prototype) $\rightarrow$ Evolving to clean, standard architecture without modifying core logic or adding new features.

---

## 1. Current Problems (v0.1)

- **Odd & Non-Standard Endpoints**: Verb-centric routes (`/upload`, `/chunk-and-embed/{file_id}`, `/generate`), missing `/api/v1` version prefix, missing health endpoint, and improper HTTP status codes (`200` instead of `201 Created`).
- **Untyped API Contracts**: Handlers return raw Python dictionaries (`dict`), preventing OpenAPI/Swagger schema documentation and leaving response contracts unvalidated.
- **Scattered Configuration**: `os.getenv` calls with conflicting defaults are spread across 5 files rather than managed in a single validated source.
- **Leaky Route Handlers**: Multi-step business workflows (storage download, parsing, chunking, embedding, vector upsert) are written directly inside route functions.
- **Global State & Deprecated Lifecycle**: Components are instantiated as module-level global objects, and `@app.on_event("startup")` is used instead of modern FastAPI `lifespan`.
- **Inconsistent Error Handling**: Repetitive `try...except` blocks in every endpoint rather than centralized exception handling.

---

## 2. Incremental Version Roadmap

| Version | Focus | Summary | Detail File |
| :--- | :--- | :--- | :--- |
| **v0.2** | **Foundation & Resilience** | Centralized config (`config.py`), modern `lifespan` handler, global exception handlers, and dead code cleanup. | [v0.2.md](v0.2.md) |
| **v0.3** | **Data Contracts & Typing** | Explicit Pydantic request/response schemas, typed `response_model` on endpoints, and identifier unification (`document_id`). | [v0.3.md](v0.3.md) |
| **v0.4** | **RESTful Routing & Endpoints** | Resource-based URLs (`/api/v1/documents`, `/api/v1/query`, `/health`), `APIRouter` modularization, and standard HTTP status codes. | [v0.4.md](v0.4.md) |
| **v0.5** | **Service Layer & Decoupling** | Dedicated services (`IngestionService`, `RAGService`), FastAPI dependency injection (`Depends`), and clean directory layout. | [v0.5.md](v0.5.md) |
