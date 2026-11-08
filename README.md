# Honeywell Virtual Assistant

<p align="center">
	<img src="https://img.shields.io/badge/HONEYWELL-Document%20Intelligence-EA1B0C?style=for-the-badge&labelColor=111827" alt="Honeywell Document Intelligence" />
</p>

<p align="center"><strong>Turn operational documents into grounded, searchable answers.</strong><br />Upload files, parse them into chunks, retrieve the most relevant context, and generate answers from a local LLM with source-aware metadata.</p>

<p>
	<img src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white" alt="Python 3.11" />
	<img src="https://img.shields.io/badge/FastAPI-0.115.0-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
	<img src="https://img.shields.io/badge/MinIO-object%20storage-C72E29?logo=minio&logoColor=white" alt="MinIO" />
	<img src="https://img.shields.io/badge/Qdrant-vector%20database-DC2626" alt="Qdrant" />
	<img src="https://img.shields.io/badge/Ollama-local%20LLM-111827" alt="Ollama" />
	<img src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white" alt="Docker Compose" />
</p>

## 🚀 Overview

Honeywell Virtual Assistant is a local document intelligence service built on FastAPI. It stores uploaded files, extracts text from supported document formats, embeds the text into Qdrant, searches for relevant chunks, and then calls Ollama to generate grounded answers with traceable source metadata.

This project is designed for internal document retrieval and Q&A over technical and operational documents, especially where a local-first workflow is preferred over cloud-only ingestion.

## ✨ Current status

**Last reviewed:** November 9, 2026. This README describes the current checkout; design documents under `docs/` also contain historical implementations and future proposals.

- 📚 Upload multiple files in a single request.
- 🧩 Support for `.txt`, `.text`, `.md`, `.markdown`, `.docx`, `.pptx`, `.doc`, and `.ppt` inputs.
- 🗂️ Store original files in MinIO object storage.
- 🧠 Parse supported inputs into Docling documents and create structure-aware, token-based chunks with heading context and page metadata where available.
- 🔍 Query Qdrant with cosine similarity over embedded document chunks.
- 🤖 Generate answers with a local Ollama model using retrieved document context.
- 📎 Return source filenames, chunk metadata, and vector distances with each answer.
- 🧾 Persist document metadata in SQLite for deduplication and tracking.
- 🛠️ List documents, inspect indexed chunks, update product tags, and delete documents across all three stores.
- 🖼️ Optionally describe embedded Office-document images with a local vision-language model; disabled by default, with plain conversion as a fallback.
- 🐳 Run the entire stack locally with Docker Compose.

### Supported inputs

| Formats | Active parsing path |
| --- | --- |
| `.txt`, `.text`, `.md`, `.markdown` | Decode text and convert through Docling's Markdown backend |
| `.docx`, `.pptx` | Docling; PowerPoint pseudo-heading promotion preserves slide context |
| `.doc`, `.ppt` | Headless LibreOffice conversion to DOCX/PPTX, then Docling |
| `.pdf`, standalone images | Not registered in the current parser router |

PDF samples in `documents/` and PDF/OCR plans in `docs/` do not indicate active PDF support. The application currently has no frontend, chat history, document versioning, background ingestion jobs, or streaming answer endpoint.

## 🏗️ Architecture

| Layer | Technology | Responsibility |
| --- | --- | --- |
| API | FastAPI | Exposes upload and query endpoints |
| Object Storage | MinIO | Persists uploaded document bytes |
| Metadata DB | SQLite | Stores document metadata and deduplication hashes |
| Vector Search | Qdrant | Stores embedded text chunks and retrieves nearest matches |
| Generation | Ollama | Produces grounded answers from retrieved context |
| Parsing | Docling + LibreOffice | Preserves document structure and converts legacy Office formats |
| Embeddings | SentenceTransformer | Generates normalized vectors independently of the vector store |

Routes delegate to services through `api/deps.py`. Core components are cached lazy singletons; service objects and SQL sessions are resolved per request. Startup creates missing SQL tables and ensures the MinIO bucket exists. `/health` is a liveness check, not a check of downstream service readiness.

## 🔄 Upload pipeline

```text
POST /api/v1/documents
  |
  +-- validate request: at least one file is required
  +-- read raw bytes from multipart upload
  +-- compute SHA-256 fingerprint for deduplication
  +-- upload original file to MinIO
  +-- download file from MinIO and parse into a DoclingDocument
  +-- create contextualized HybridChunker chunks and attach metadata
  +-- generate embeddings for each chunk
  +-- upsert vectors and product metadata into Qdrant
  +-- create SQLite metadata record for the document
  +-- return indexed status and chunk counts
```

Deduplication uses the raw file's SHA-256 plus `product_id`. A duplicate returns the existing document ID, `status: "duplicate"`, and `total_chunks: 0` without reindexing. Identical bytes under another product tag are ingested separately. SQL metadata is committed after vector indexing, one file at a time.

Chunk IDs follow `<document_id>_c<index>`; Qdrant point IDs are deterministic UUID5 values derived from those IDs. Payloads contain chunk text, document ID, filename, product tag, chunk index, and available page metadata. Heading-only content is recovered in a second chunking pass. A legacy character-based splitter remains available for page/text tuple inputs, but registered parsers use the Docling path.

## 🔎 Retrieval and generation pipeline

```text
POST /api/v1/query
  |
  +-- validate supplied question (must not be empty)
  +-- embed the question and search Qdrant for nearest chunks
  +-- collect top-k candidate chunks and their metadata/distances
  +-- build a grounded prompt from matching chunk text
  +-- call Ollama with the configured local model
  +-- return the answer plus source metadata and similarity distances
```

Queries currently search the whole configured collection: the request accepts only `question`, with no product/document filter, reranker, or similarity cutoff. Returned distances are `max(0, 1 - cosine_similarity)`; smaller is better. Source entries describe retrieved chunks, while inline citations are generated by the model and are not validated by the application.

## 📦 Installation

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) or Docker Engine
- Git
- `curl` or another HTTP client

### Clone and configure

```powershell
git clone https://github.com/hruthikeshb/honeywell-virtual-assistant.git
Set-Location honeywell-virtual-assistant
Copy-Item .env.example .env
```

### Local `.env` values

Configure the MinIO credentials in `.env` before starting Compose. Keep the supplied `SYSTEM_PROMPT` and `PROMPT_TEMPLATE` entries: the code has no built-in fallback prompt text. Compose sets container service hostnames automatically and uses `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` for the API's MinIO credentials.

```dotenv
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin
```

### Start services and prepare generation

```powershell
docker compose up --build -d
docker compose exec ollama ollama pull llama3.2:3b
curl.exe http://localhost:8000/health
```

Pull the model named by `OLLAMA_MODEL` if you change it. The first ingestion may also download the embedding model and chunker tokenizer. The Docker image installs CPU-only PyTorch and LibreOffice. Compose bind-mounts the repository and runs Uvicorn with reload enabled for development.

On Linux/macOS, use `cp .env.example .env` and `curl` in place of the PowerShell equivalents above.

## 🌐 Service URLs

| Service | URL |
| --- | --- |
| FastAPI API | `http://localhost:8000` |
| Swagger UI | `http://localhost:8000/docs` |
| ReDoc | `http://localhost:8000/redoc` |
| MinIO API | `http://localhost:9000` |
| MinIO Console | `http://localhost:9001` |
| Ollama | `http://localhost:11434` |
| Qdrant REST API | `http://localhost:6333` |
| Qdrant gRPC | `localhost:6334` |
| Qdrant Dashboard | `http://localhost:6333/dashboard` |

## 🩺 Health and documentation

- Health endpoint: `GET /health`
- Swagger: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`
- The root route `/` is not defined; open `/docs` directly.

## ▶️ Usage

### 1. Upload documents

The `files` field is repeatable, and `product_id` is optional and used to group related uploads.

```powershell
curl.exe -X POST "http://localhost:8000/api/v1/documents" `
  -F "product_id=demo-product" `
  -F "files=@C:\path\to\sample.pptx" `
  -F "files=@C:\path\to\sample.docx"
```

Example successful response:

```json
{
  "message": "Documents processed successfully",
  "count": 2,
  "documents": [
    {
      "document_id": "<uuid>",
      "product_id": "demo-product",
      "filename": "sample.pptx",
      "size_bytes": 245921,
      "collection": "honeywell_documents",
      "total_chunks": 42,
      "status": "indexed"
    },
    {
      "document_id": "<another-uuid>",
      "product_id": "demo-product",
      "filename": "sample.docx",
      "size_bytes": 12800,
      "collection": "honeywell_documents",
      "total_chunks": 8,
      "status": "indexed"
    }
  ]
}
```

### 2. Ask a question

```powershell
curl.exe -X POST "http://localhost:8000/api/v1/query" `
  -H "Content-Type: application/json" `
  -d '{"question":"What are the key risks described in these documents?"}'
```

Example response:

```json
{
  "question": "What are the key risks described in these documents?",
  "answer": "The documents describe a combination of ...",
  "model": "llama3.2:3b",
  "sources": [
    {
      "metadata": {
        "document_id": "<uuid>",
        "filename": "sample.pptx",
        "page": 3,
        "chunk_index": 2
      },
      "distance": 0.42
    }
  ]
}
```

### 3. List documents

```powershell
curl.exe -X GET "http://localhost:8000/api/v1/documents?limit=10&product_id=demo-product"
```

### 4. Inspect document chunks

```powershell
curl.exe -X GET "http://localhost:8000/api/v1/documents/<uuid>/chunks?limit=5"
```

Document listing supports `product_id`, `name_search`, `uploaded_after`, `uploaded_before`, `limit` (1–100), and `skip`. Results are newest first. The exposed `status` parameter currently has no filtering effect; returned documents are labeled `indexed` even when their live vector count is zero. Chunk inspection uses `limit` (1–100) and numeric `offset`, traversing Qdrant point-ID order rather than chunk-index order.

### 5. Update document metadata

```powershell
curl.exe -X PATCH "http://localhost:8000/api/v1/documents/<uuid>" `
  -H "Content-Type: application/json" `
  -d '{"product_id":"updated-product-tag"}'
```

### 6. Delete document (Cascade across Vector, SQL, and Object storage)

```powershell
curl.exe -X DELETE "http://localhost:8000/api/v1/documents/<uuid>"
```

## 🔌 API reference

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness check for the API |
| `GET` | `/docs` | Swagger UI documentation |
| `POST` | `/api/v1/documents` | Upload one or more documents and index them |
| `GET` | `/api/v1/documents` | List indexed documents with filtering and pagination |
| `GET` | `/api/v1/documents/{id}` | Retrieve metadata and live chunk count for a document |
| `GET` | `/api/v1/documents/{id}/chunks` | Inspect raw text chunks and vector metadata |
| `PATCH` | `/api/v1/documents/{id}` | Update document metadata (`product_id`) across SQLite and Qdrant |
| `DELETE` | `/api/v1/documents/{id}` | Cascade delete document from Qdrant, SQLite, and MinIO |
| `POST` | `/api/v1/query` | Ask a question against the indexed document corpus |

The OpenAPI schema is generated automatically and served at `/docs`.

## ⚙️ Configuration

Infrastructure settings are defined in `config.py`; parsing, chunking, model, retrieval, and prompt settings are in `core/pipeline_config.py`. Compose injects `.env` and overrides service hostnames. Settings are evaluated at import time, and components are cached; restart the API after changing configuration.

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./honeywell.db` | SQLite database for document metadata |
| `MINIO_ENDPOINT` | `minio:9000` | MinIO host inside Docker |
| `MINIO_BUCKET` | `honeywell-files` in Compose | Bucket name for uploaded files |
| `MINIO_ACCESS_KEY` | from `MINIO_ROOT_USER` | MinIO access key |
| `MINIO_SECRET_KEY` | from `MINIO_ROOT_PASSWORD` | MinIO secret key |
| `QDRANT_HOST` | unset; `qdrant` in Compose | Server hostname; `.env.example` uses `localhost` for local development |
| `QDRANT_PORT` | `6333` | REST API port |
| `QDRANT_PATH` | unset; `./qdrant_data` in `.env.example` | Local persistence directory when no host is configured |
| `QDRANT_COLLECTION` | `honeywell_documents` | Default collection name |
| `EMBEDDING_MODEL` | `BAAI/bge-base-en-v1.5` | SentenceTransformer model used for indexing and retrieval |
| `EMBEDDING_DEVICE` | `cpu` | Embedding execution device |
| `OLLAMA_HOST` | `ollama` | Ollama service address inside Docker |
| `OLLAMA_PORT` | `11434` | Ollama API port |
| `OLLAMA_MODEL` | `llama3.2:3b` | Model used for generation |
| `RETRIEVAL_K` | `5` | Number of relevant chunks to retrieve for each query |
| `CHUNKER_TOKENIZER` | `sentence-transformers/all-MiniLM-L6-v2` | Tokenizer used by Docling's HybridChunker; independent of the embedding model |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `1000` / `200` | Character limits for the legacy tuple-input splitter, not the active Docling path |
| `ENABLE_PICTURE_DESCRIPTION` | `false` | Enable optional Office-image descriptions |
| `PICTURE_DESCRIPTION_PRESET` | `smolvlm` | Docling vision-language model preset |
| `PICTURE_DESCRIPTION_PROMPT` | Concise image description prompt | Prompt for image descriptions |
| `LIBREOFFICE_BINARY` | Auto-discovery; `soffice` in `.env.example` | Executable name or path for legacy Office conversion |
| `LIBREOFFICE_TIMEOUT_SECONDS` | `60` | Timeout for each LibreOffice conversion |
| `UPLOAD_MAX_FILE_SIZE_MB` | `50` | Defined in configuration but not currently enforced by the uploader |
| `SYSTEM_PROMPT` | No code default | Generation instructions; supplied in `.env.example` |
| `PROMPT_TEMPLATE` | No code default | Prompt text containing `{context}` and `{question}` placeholders |

The generator formats context with filename and page labels. The example system prompt currently asks for chunk-index citations, so its citation instructions do not fully match those context labels. Responses should not be treated as having mechanically verified citations.

## 🐍 Local development

If you prefer running the API without Docker, install the Python dependencies and launch Uvicorn directly:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn main:app --env-file .env --reload --host 0.0.0.0 --port 8000
```

Use Python 3.11 to match the Docker image. On Linux/macOS, activate the virtual environment with `source .venv/bin/activate`. Install LibreOffice Writer/Impress locally if you need `.doc`/`.ppt` conversion.

Before starting the API in local mode, ensure that MinIO, Qdrant, and Ollama are running and reachable. You can start just these dependencies with `docker compose up -d minio qdrant ollama`. Set `MINIO_ENDPOINT=localhost:9000`, `QDRANT_HOST=localhost`, and `OLLAMA_HOST=localhost` in `.env`, and make sure `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` match the server credentials.

Use `--env-file .env` so infrastructure variables are loaded before application imports. Although `core/pipeline_config.py` calls `load_dotenv()`, `config.py` can be imported first and does not load the file itself.

Qdrant client and server are pinned to v1.12.0. The retriever selects an explicit client first, then `QDRANT_HOST`, then `QDRANT_PATH`; with neither host nor path it uses ephemeral in-memory storage. Collection dimensions are inferred from the loaded embedding model and validated on reuse.

The first ingestion can download the embedding model and chunker tokenizer. Pull the configured generation model before querying:

```bash
docker compose exec ollama ollama pull llama3.2:3b
```

## 🗂️ Repository guide

| Path | Responsibility |
| --- | --- |
| `main.py` | App lifecycle, router registration, and global exception handlers |
| `api/deps.py` | Cached core providers and service dependency injection |
| `api/v1/endpoints/` | Document, query, and health routes |
| `services/` | Ingestion, retrieval/generation, and document lifecycle orchestration |
| `core/parsers/` | Parser interface, format router, Docling, text, and LibreOffice adapters |
| `core/` | Chunking, embeddings, Qdrant retrieval, MinIO upload, and Ollama generation |
| `schemas/` | Pydantic request/response models |
| `db/`, `alembic/` | SQLAlchemy document model, sessions, and initial schema migration |
| `tests/` | Unit, parser, integration, and historical API-contract tests |
| `scripts/debug_parse.py` | CLI to inspect parsing and chunk output |
| `documents/` | Sample PDF corpus for parsing research |
| `docs/` | Architecture proposals, implementation plans, and archived handoffs |

## 🧪 Development checks

Test tools are not listed in `requirements.txt`; install them separately:

```bash
python -m pip install pytest httpx
python -m pytest tests/unit/test_embeddings.py tests/unit/test_retriever.py tests/unit/test_document_service.py tests/unit/test_documents_read_api.py tests/unit/test_documents_mutation_api.py tests/integration/test_qdrant_pipeline.py
```

These targeted suites use mocks and/or in-memory stores. The Qdrant pipeline integration tests use real parsing, a local bag-of-words embedding model, and a local tokenizer, with mocked MinIO and Ollama calls. They do not validate live model answer quality.

```bash
# Parser tests; some require a cached tokenizer or network access
python -m pytest tests/parsers

# Opt in to heavyweight image-description tests
python -m pytest tests/parsers/test_picture_description.py -m slow

# Inspect parsing and chunking without uploading or indexing
python scripts/debug_parse.py path/to/manual.docx
```

`pytest.ini` excludes `slow` tests by default. The full suite includes historical tests that reference removed routes, schema imports, prompt constants, and metadata keys; it is not a uniformly current regression suite. The [Qdrant migration verification notes](docs/qdrant/qdrant_v5.md#implementation-notes--verification-results) record earlier targeted passes and full-suite failures. Those are historical results, not a fresh verification of your environment.

## 🧩 Design notes

- Documents are deduplicated by SHA-256 on a per-product basis via `product_id`.
- Duplicate uploads return a stored document ID instead of reindexing the same content again.
- The ingestion flow is synchronous: upload, parse, chunk, embed, persist, and index in the same request.
- The service is intentionally focused on the backend retrieval stack rather than any user-facing web frontend.
- Deletion removes Qdrant points, then the SQLite record, then the MinIO object. `storage_removed=false` indicates an object-storage deletion failure.
- Chunk pagination uses a numeric skip count over Qdrant point-ID order; it is not sorted by `chunk_index`.
- PDF parsing and a dedicated OCR pipeline are not currently registered in `ParserRouter`.
- Existing data from a previous vector backend is not automatically copied. SQLite duplicate detection does not check whether corresponding vectors exist in Qdrant; backfill existing documents before relying on them for retrieval.
- Cross-store operations are not atomic. A failed ingestion can leave an uploaded object or indexed vectors without a SQL row; earlier files in a batch can already be committed. Product-tag updates commit SQLite before updating Qdrant.
- Deduplication is an application-level lookup, not a database uniqueness constraint on `(product_id, sha256)`.
- The database contains one `documents` table. Alembic defines the initial schema; application startup uses `create_all`, which does not migrate existing table definitions.

## 🔧 Troubleshooting

| Symptom | Check |
| --- | --- |
| PDF upload reports an unsupported extension | PDF is not registered; use a supported format. Upload happens before parsing, so a failed parse may leave an object in MinIO. |
| Generation cannot reach Ollama or returns an empty answer | Check the Ollama hostname/port, service logs, and whether the configured model has been pulled. |
| Prompt construction fails | Ensure `PROMPT_TEMPLATE` and `SYSTEM_PROMPT` are supplied; copy the complete multiline values from `.env.example`. |
| Qdrant collection configuration mismatch | Existing collections must match the loaded embedding dimension and use cosine distance. Model fallback can change dimensions. Changing embedding models requires a deliberate reindex, even if dimensions match. |
| First ingestion is slow or model loading fails | Check embedding/tokenizer downloads and cache availability; enabling picture descriptions adds model-loading and inference work. |
| Legacy Office conversion fails | Check LibreOffice installation, `LIBREOFFICE_BINARY`, and the conversion timeout. |
| Upload is marked duplicate but queries find no chunks | SQL deduplication records may remain after vector storage was cleared. Restore/reindex the corpus or deliberately delete the affected document record through the API before re-uploading. |

## 📚 Design history

- [Parsing roadmap](docs/parser/parsing_architecture_plan.md): staged parser proposals; PDF and vLLM stages are not implemented in this checkout.
- [PDF/OCR architecture recommendation](docs/parser/RAG_PARSING_ARCHITECTURE_FINAL.md): research and proposed routing, not the active parser contract.
- [Qdrant migration](docs/qdrant/qdrant_version_plan.md) and [completion notes](docs/qdrant/qdrant_v5.md): migration history and recorded verification.
- [Earlier API/service plans](docs/v0/plan.md) and [lean document model rationale](docs/archive/plan.md): background on the current structure.

Use the active source and generated OpenAPI schema as the implementation reference. Archived handoffs can describe other branches, removed components, or unfinished work.

## 🛑 Stopping the stack

```powershell
docker compose down
```

To intentionally remove local volumes and reset MinIO, Qdrant, and Ollama data as well (including downloaded Ollama models):

```powershell
docker compose down --volumes
```

The SQLite file is stored separately in the bind-mounted repository and is not removed by this command. A vector reset alone leaves document records that can still trigger duplicate-upload detection.

## 📄 License

No `LICENSE` file is currently included in this repository. Add a license before broader distribution or reuse beyond internal evaluation.
