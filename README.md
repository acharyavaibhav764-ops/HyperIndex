# HyperIndex

<p align="center">
	<img src="https://img.shields.io/badge/HyperIndex-Document%20Intelligence-6366F1?style=for-the-badge&labelColor=111827" alt="HyperIndex Document Intelligence" />
</p>

<p align="center"><strong>Turn operational documents into grounded, searchable answers.</strong><br />Upload files, parse them into chunks, retrieve the most relevant context, and generate answers from a local LLM with source-aware metadata.</p>

<p>
	<img src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white" alt="Python 3.11" />
	<img src="https://img.shields.io/badge/FastAPI-0.115.0-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
	<img src="https://img.shields.io/badge/MinIO-object%20storage-C72E29?logo=minio&logoColor=white" alt="MinIO" />
	<img src="https://img.shields.io/badge/ChromaDB-vector%20database-FF6F00" alt="ChromaDB" />
	<img src="https://img.shields.io/badge/Ollama-local%20LLM-111827" alt="Ollama" />
	<img src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white" alt="Docker Compose" />
</p>

## 🚀 Overview

HyperIndex is a local document intelligence service built on FastAPI. It stores uploaded files, extracts text from common document formats, embeds the text into ChromaDB, searches for relevant chunks, and then calls Ollama to generate grounded answers with traceable source metadata.

HyperIndex is designed for document retrieval and Q&A over technical and operational documents, especially where a local-first, privacy-respecting workflow is preferred over cloud-only ingestion.

## ✨ Features

- 📚 Upload multiple files in a single request.
- 🧩 Support for `.pdf`, `.txt`, `.md`, `.docx`, `.pptx`, `.doc`, and `.ppt` inputs.
- 🗂️ Store original files in MinIO object storage.
- 🧠 Extract text, normalize pages, and create chunked embeddings for search.
- 🔍 Query ChromaDB with cosine similarity over embedded document chunks.
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
| Vector Search | ChromaDB | Stores embedded text chunks and retrieves nearest matches |
| Generation | Ollama | Produces grounded answers from retrieved context |
| Parsing | Docling + pypdf + python-docx + python-pptx + PyMuPDF | Extracts readable text from supported formats |

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
  +-- upsert vectors into ChromaDB
  +-- create SQLite metadata record for the document
  +-- return indexed status and chunk counts
```

## 🔎 Retrieval and generation pipeline

```text
POST /api/v1/query
  |
  +-- validate supplied question (must not be empty)
  +-- embed the question and search ChromaDB for nearest chunks
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
git clone https://github.com/acharyavaibhav764-ops/HyperIndex.git
Set-Location HyperIndex
docker compose up --build -d
```

### Local `.env` values

Create a `.env` file if you want to override the default MinIO credentials.

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
| ChromaDB | `http://localhost:8001` |

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
  -F "files=@C:\path\to\sample.pdf" `
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
      "filename": "sample.pdf",
      "size_bytes": 245921,
      "collection": "my_documents",
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
        "filename": "sample.pdf",
        "page": 3,
        "chunk_index": 2
      },
      "distance": 0.42
    }
  ]
}
```

## 🔌 API reference

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness check for the API |
| `GET` | `/docs` | Swagger UI documentation |
| `POST` | `/api/v1/documents` | Upload one or more documents and index them |
| `POST` | `/api/v1/query` | Ask a question against the indexed document corpus |

The OpenAPI schema is generated automatically and served at `/docs`.

## ⚙️ Configuration

The application reads configuration from environment variables, with defaults defined in `config.py` and container-level values set in `docker-compose.yml`.

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./hyperindex.db` | SQLite database for document metadata |
| `MINIO_ENDPOINT` | `minio:9000` | MinIO host inside Docker |
| `MINIO_BUCKET` | `hyperindex-files` in Compose | Bucket name for uploaded files |
| `MINIO_ACCESS_KEY` | from `MINIO_ROOT_USER` | MinIO access key |
| `MINIO_SECRET_KEY` | from `MINIO_ROOT_PASSWORD` | MinIO secret key |
| `CHROMA_HOST` | unset | ChromaDB host for non-default setups |
| `CHROMA_PORT` | `8000` | ChromaDB internal port |
| `CHROMA_PATH` | `./chroma_data` | Local persistence path |
| `CHROMA_COLLECTION` | `my_documents` | Default collection name |
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

Before starting the API in local mode, ensure that MinIO, ChromaDB, and Ollama are running and reachable.

## 🧩 Design notes

- Documents are deduplicated by SHA-256 on a per-product basis via `product_id`.
- Duplicate uploads return a stored document ID instead of reindexing the same content again.
- The ingestion flow is synchronous: upload, parse, chunk, embed, persist, and index in the same request.
- The service is intentionally focused on the backend retrieval stack rather than any user-facing web frontend.
- There is no separate document-deletion or OCR pipeline implemented in this repository at the moment.

## 🛑 Stopping the stack

```powershell
docker compose down
```

To remove local volumes and reset MinIO, ChromaDB, and Ollama data as well:

```powershell
docker compose down --volumes
```

## 📄 License

No `LICENSE` file is currently included in this repository. Add a license before broader distribution or reuse beyond internal evaluation.
