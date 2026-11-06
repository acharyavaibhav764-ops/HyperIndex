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

## ✨ Features

- 📚 Upload multiple files in a single request.
- 🧩 Support for `.txt`, `.text`, `.md`, `.markdown`, `.docx`, `.pptx`, `.doc`, and `.ppt` inputs.
- 🗂️ Store original files in MinIO object storage.
- 🧠 Extract text, normalize pages, and create chunked embeddings for search.
- 🔍 Query Qdrant with cosine similarity over embedded document chunks.
- 🤖 Generate answers with a local Ollama model using retrieved document context.
- 📎 Return source filenames, chunk metadata, and vector distances with each answer.
- 🧾 Persist document metadata in SQLite for deduplication and tracking.
- 🐳 Run the entire stack locally with Docker Compose.

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

## 🔄 Upload pipeline

```text
POST /api/v1/documents
  |
  +-- validate request: at least one file is required
  +-- read raw bytes from multipart upload
  +-- compute SHA-256 fingerprint for deduplication
  +-- upload original file to MinIO
  +-- download file from MinIO and parse document text
  +-- chunk extracted text with metadata (document_id, filename, page, chunk_index)
  +-- generate embeddings for each chunk
  +-- upsert vectors and product metadata into Qdrant
  +-- create SQLite metadata record for the document
  +-- return indexed status and chunk counts
```

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

## 📦 Installation

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) or Docker Engine
- Git
- `curl` or another HTTP client

### Clone and start the stack

```powershell
git clone https://github.com/hruthikeshb/honeywell-virtual-assistant.git
Set-Location honeywell-virtual-assistant
docker compose up --build -d
```

### Local `.env` values

Copy `.env.example` to `.env` and configure the MinIO credentials before starting Compose. Compose sets container service hostnames automatically.

```dotenv
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin
```

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
- Root route: `http://localhost:8000/` redirects to Swagger UI

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

The application reads configuration from environment variables, with defaults defined in `config.py` and container-level values set in `docker-compose.yml`.

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

## 🐍 Local development

If you prefer running the API without Docker, install the Python dependencies and launch Uvicorn directly:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Before starting the API in local mode, ensure that MinIO, Qdrant, and Ollama are running and reachable. Set their hostnames to `localhost` when using the published Docker ports.

Qdrant client and server are pinned to v1.12.0. The retriever selects an explicit client first, then `QDRANT_HOST`, then `QDRANT_PATH`; with neither host nor path it uses ephemeral in-memory storage. Collection dimensions are inferred from the loaded embedding model and validated on reuse.

The first ingestion can download the embedding model and chunker tokenizer. Pull the configured generation model before querying:

```bash
docker compose exec ollama ollama pull llama3.2:3b
```

## 🧩 Design notes

- Documents are deduplicated by SHA-256 on a per-product basis via `product_id`.
- Duplicate uploads return a stored document ID instead of reindexing the same content again.
- The ingestion flow is synchronous: upload, parse, chunk, embed, persist, and index in the same request.
- The service is intentionally focused on the backend retrieval stack rather than any user-facing web frontend.
- Deletion removes Qdrant points, then the SQLite record, then the MinIO object. `storage_removed=false` indicates an object-storage deletion failure.
- Chunk pagination uses a numeric skip count over Qdrant point-ID order; it is not sorted by `chunk_index`.
- PDF parsing and a dedicated OCR pipeline are not currently registered in `ParserRouter`.
- Existing data from a previous vector backend is not automatically copied. SQLite duplicate detection does not check whether corresponding vectors exist in Qdrant; backfill existing documents before relying on them for retrieval.

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
