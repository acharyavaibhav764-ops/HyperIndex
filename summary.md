# Honeywell RAG Pipeline — v0.1 Decision Summary

This document summarizes the architectural and configuration decisions implemented in **v0.1** of the Honeywell RAG pipeline, covering only the specified decision boundaries. Each boundary is documented in its own dedicated table.

---

## 1. Ingestion

| Decision Point | v0.1 Implementation Choice | Details / Code Reference |
|---|---|---|
| **Supported Formats** | `.pdf`, `.txt`, `.md` | `.pdf` parsed via `pypdf.PdfReader`; plain text/markdown handled via fallback text decoders. ([parser.py:L41-L85](file:///backend/app/core/rag/parser.py#L41-L85)) |
| **Content Sanitization / Cleaning** | Multi-encoding decode + Regex control char filter | • Encodings: `["utf-8", "utf-8-sig", "latin-1", "cp1252"]` (with `errors="replace"` fallback)<br>• Control characters stripped: `[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]`<br>• Whitespace collapsed, `\n{3,}` normalized to `\n\n`. ([parser.py:L18-L32](file:///backend/app/core/rag/parser.py#L18-L32)) |
| **Ingestion Mechanism** | MinIO raw bytes buffer | Full file bytes downloaded via `storage_service.download_bytes()` and loaded into memory as `io.BytesIO(content)`. ([pipeline.py:L53](file:///backend/app/core/rag/pipeline.py#L53), [parser.py:L45](file:///backend/app/core/rag/parser.py#L45)) |
| **Extraction Granularity** | Page-level (PDF) / Document-level (Text) | PDFs: per-page extraction tagged with `{"source": filename, "page": page_idx + 1}`.<br>Text/MD: entire file treated as a single block on page 1. ([parser.py:L58-L68](file:///backend/app/core/rag/parser.py#L58-L68)) |

---

## 2. Chunking

| Decision Point | v0.1 Implementation Choice | Details / Code Reference |
|---|---|---|
| **Chunking Strategy** | Recursive Character Splitting | `RecursiveCharacterTextSplitter` from LangChain. ([chunker.py:L40](file:///backend/app/core/rag/chunker.py#L40)) |
| **Chunk Size** | `1000` characters | Configurable via `CHUNK_SIZE` env var (default: `1000`). ([config.py:L25](file:///backend/app/utils/config.py#L25)) |
| **Chunk Overlap** | `200` characters | Configurable via `CHUNK_OVERLAP` env var (default: `200`). ([config.py:L26](file:///backend/app/utils/config.py#L26)) |
| **Separator Precedence** | `["\n\n", "\n", ". ", " ", ""]` | Hierarchical recursive splitting boundaries. ([chunker.py:L43](file:///backend/app/core/rag/chunker.py#L43)) |
| **Chunk Metadata & Filtering** | Structured dict with unique ID + micro-chunk pruning | • `source`: filename string<br>• `page`: page integer<br>• `chunk_id`: `{source}_p{page}_c{idx}`<br>• `chunk_index`: integer index `idx`<br>• Sanitized to primitives (`str`, `int`, `float`, `bool`)<br>• Prunes empty/micro chunks where `len(content) < 5`. ([chunker.py:L54-L69](file:///backend/app/core/rag/chunker.py#L54-L69)) |

---

## 3. Embedding

| Decision Point | v0.1 Implementation Choice | Details / Code Reference |
|---|---|---|
| **Embedding Engine** | Chroma `DefaultEmbeddingFunction` | Wrapped in custom `ChromaDefaultEmbeddings` implementing LangChain `Embeddings`. ([embeddings.py:L17-L29](file:///backend/app/core/rag/embeddings.py#L17-L29)) |
| **Underlying Model** | `all-MiniLM-L6-v2` | Pre-packaged ONNX model bundled with ChromaDB. ([embeddings.py:L19](file:///backend/app/core/rag/embeddings.py#L19)) |
| **Vector Dimensions** | `384` | Fixed output embedding dimension of `all-MiniLM-L6-v2`. |
| **Batch Size** | `64` | Processed in bounded slices of 64 texts to prevent memory spikes. ([embeddings.py:L23](file:///backend/app/core/rag/embeddings.py#L23)) |
| **Hardware** | CPU (in-container) | Executed locally inside backend Docker container on CPU via ONNX Runtime. |

---

## 4. Storage & Persistence

| Decision Point | v0.1 Implementation Choice | Details / Code Reference |
|---|---|---|
| **Object Store Engine** | MinIO (standalone) | Image: `minio/minio:latest` via S3-compatible API. ([docker-compose.yml:L2-L18](file:///docker-compose.yml#L2-L18)) |
| **Object Bucket Name** | `honeywell-documents` | Configurable via `BUCKET_NAME` env var. ([config.py:L20](file:///backend/app/utils/config.py#L20)) |
| **Object Store Location** | Container: `minio_dev` | Internal Docker host `minio-dev:9000`, console on `9001`, volume `minio_data:/data`. ([docker-compose.yml:L2-L18](file:///docker-compose.yml#L2-L18)) |
| **Vector DB Engine** | ChromaDB `PersistentClient` | Embedded SQLite + DuckDB index with thread-safe singleton lock. ([vector_store.py:L30-L39](file:///backend/app/core/rag/vector_store.py#L30-L39)) |
| **Vector Collection Name** | `my_documents` | Configurable via `COLLECTION_NAME` env var. ([config.py:L24](file:///backend/app/utils/config.py#L24)) |
| **Vector Store Location** | Persistent volume: `/data/chroma` | Bound to Docker volume `chroma_data:/data/chroma`. ([docker-compose.yml:L33-L41](file:///docker-compose.yml#L33-L41), [config.py:L23](file:///backend/app/utils/config.py#L23)) |

---

## 5. Retrieval

| Decision Point | v0.1 Implementation Choice | Details / Code Reference |
|---|---|---|
| **Search Paradigm** | Pure Dense Similarity Search | Cosine distance search via `store.similarity_search_with_score()`. ([vector_store.py:L145](file:///backend/app/core/rag/vector_store.py#L145)) |
| **Retrieved Chunks ($K$)** | `5` | Configurable via `RETRIEVAL_K` env var (default: `5`) or API payload `k`. ([config.py:L27](file:///backend/app/utils/config.py#L27), [retriever.py:L47](file:///backend/app/core/rag/retriever.py#L47)) |
| **Score Filtering** | Distance threshold check (internal) | `VectorRetriever.retrieve()` drops chunks where `score > score_threshold`. (Not exposed in active API route). ([retriever.py:L57-L59](file:///backend/app/core/rag/retriever.py#L57-L59)) |
| **Metadata Filtering** | None | No pre- or post-filtering by author, tag, or version exposed in active query endpoints. |

---

## 6. Context Assembly

| Decision Point | v0.1 Implementation Choice | Details / Code Reference |
|---|---|---|
| **Budget Limit & Enforcement** | `12,000` characters with naive slice | Cap of 12,000 characters (~3,000 tokens). Enforced via substring slicing: `context[:max_chars] + "\n\n[Context truncated due to size limits...]"` if limit exceeded. ([generator.py:L19-L45](file:///backend/app/core/rag/generator.py#L19-L45)) |
| **System Prompt** | Factual defensive template with citation rules | `GROUNDED_DEFENSIVE_PROMPT_TEMPLATE`: instructs LLM to rely strictly on context, answer with: *"I cannot find sufficient information in the provided documents to answer this question."* if missing, and format citations as `[Source: manual.pdf \| Page: 2]`. Retrieved chunks delimited by `\n\n---\n\n`. ([generator.py:L21-L32](file:///backend/app/core/rag/generator.py#L21-L32)) |

---

## 7. Generation

| Decision Point | v0.1 Implementation Choice | Details / Code Reference |
|---|---|---|
| **Inference Provider** | Groq Cloud API | `langchain_groq.ChatGroq` (`request_timeout=30.0s`, `max_retries=2`). ([generator.py:L54-L63](file:///backend/app/core/rag/generator.py#L54-L63)) |
| **Model** | `openai/gpt-oss-120b` | Configurable via `CHAT_MODEL` env var (fallback: `llama-3.3-70b-versatile`). ([config.py:L31](file:///backend/app/utils/config.py#L31)) |
| **Temperature** | `0.0` | Deterministic, non-creative generation for strictly factual answers. ([generator.py:L54](file:///backend/app/core/rag/generator.py#L54)) |
| **Output Structure** | Plain text string $\rightarrow$ JSON response | Chain outputs plain text (`StrOutputParser`); API route wraps it into structured JSON: `GenerateResponse(query, answer, sources=[SourceCitation(...)])`. ([generator.py:L92](file:///backend/app/core/rag/generator.py#L92), [routes/rag.py:L66-L70](file:///backend/app/api/routes/rag.py#L66-L70)) |
| **Citation Mechanism** | Dual-layer citation | 1. Prompt-instructed inline citations (`[Source: ... \| Page: ...]`) inside answer text.<br>2. API response payload includes distinct `sources` array with `source` filename and `page` number. ([routes/rag.py:L69](file:///backend/app/api/routes/rag.py#L69)) |

---

## 8. API

| Decision Point | v0.1 Implementation Choice | Details / Code Reference |
|---|---|---|
| **Web Framework** | FastAPI (ASGI on Uvicorn) | High-performance async Python framework with automatic OpenAPI docs. ([main.py:L1-L30](file:///backend/app/main.py#L1-L30)) |
| **Routes** | RESTful endpoints + legacy compatibility aliases | • `POST /documents`: Upload file & enqueue indexing<br>• `GET /documents`: List stored documents<br>• `DELETE /documents`: Delete file & purge vectors<br>• `GET /status`: Poll task status via `task_id`<br>• `POST /search`: Pure vector retrieval (no LLM)<br>• `POST /generate`: Full RAG query & generation<br>• `GET /health`: Health probe for MinIO and Chroma<br>• Legacy aliases: `POST /upload`, `GET /metadata/{filename}`, `POST /query`. ([routes/documents.py](file:///backend/app/api/routes/documents.py), [routes/rag.py](file:///backend/app/api/routes/rag.py), [routes/health.py](file:///backend/app/api/routes/health.py)) |
| **Async Indexing Mechanism** | FastAPI `BackgroundTasks` | File saved to MinIO immediately; chunking and vector indexing delegated to in-process background worker task `background_index_task`. ([routes/documents.py:L70](file:///backend/app/api/routes/documents.py#L70)) |
| **Task State Store** | In-memory `TaskManager` | In-memory Python `dict` tracking `TaskInfo(task_id, filename, state, chunks_indexed, error, created_at, updated_at)`. States: `PENDING`, `PROCESSING`, `FINISHED`, `FAILED`. ([tasks.py:L1-L60](file:///backend/app/utils/tasks.py#L1-L60)) |

---

## 9. Infrastructure

| Decision Point | v0.1 Implementation Choice | Details / Code Reference |
|---|---|---|
| **Containers & Images** | 3 Docker services | • `minio_dev` (`minio/minio:latest`)<br>• `backend_dev` (Python FastAPI Dockerfile, Uvicorn on port `8000`)<br>• `frontend_dev` (Next.js Node Dockerfile on port `3000`). ([docker-compose.yml:L1-L65](file:///docker-compose.yml#L1-L65)) |
| **Port Mapping** | External $\rightarrow$ Internal | • Backend API: `8000:8000`<br>• Frontend Web UI: `3000:3000`<br>• MinIO API: `9000:9000`<br>• MinIO Web Console: `9001:9001`. ([docker-compose.yml](file:///docker-compose.yml)) |
| **Networking** | Docker Compose default bridge | Frontend connects to backend via `http://backend-dev:8000` (internal SSR) and `http://localhost:8000` (browser client). Backend connects to MinIO via `minio-dev:9000`. ([docker-compose.yml:L29](file:///docker-compose.yml#L29), [L53](file:///docker-compose.yml#L53)) |
| **Volumes & Persistence** | Named Docker volumes | • `minio_data` mounted at `/data` in MinIO container<br>• `chroma_data` mounted at `/data/chroma` in backend container<br>• Local directory bind mounts for development (`./backend:/code`, `./frontend:/app`). ([docker-compose.yml:L12-L13](file:///docker-compose.yml#L12-L13), [L40-L41](file:///docker-compose.yml#L40-L41)) |
