# Honeywell Virtual Assistant

<p align="center">
	<img src="https://img.shields.io/badge/HONEYWELL-Document%20Intelligence-EA1B0C?style=for-the-badge&labelColor=111827" alt="Honeywell Document Intelligence" />
</p>

<p align="center"><strong>Turn operational documents into grounded, searchable answers.</strong><br />Upload files, index their contents, and query a local language model with page-level source metadata.</p>

<p>
	<img src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white" alt="Python 3.11" />
	<img src="https://img.shields.io/badge/FastAPI-0.115.0-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
	<img src="https://img.shields.io/badge/MinIO-object%20storage-C72E29?logo=minio&logoColor=white" alt="MinIO" />
	<img src="https://img.shields.io/badge/ChromaDB-vector%20database-FF6F00" alt="ChromaDB" />
	<img src="https://img.shields.io/badge/Ollama-local%20LLM-111827" alt="Ollama" />
	<img src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white" alt="Docker Compose" />
</p>



## 🚀 Features

- 📚 Upload multiple documents in one request.
- 🧩 Parse `.pdf`, `.txt`, `.md`, `.docx`, and legacy `.doc` files.
- ✂️ Split extracted text into overlapping chunks and embed it with ChromaDB.
- 🔎 Retrieve the five closest chunks for each question.
- 💬 Generate grounded answers with a local Ollama model.
- 🧾 Return source filenames, page numbers, and vector distances with answers.
- 💾 Persist documents, vectors, and model data in Docker volumes.

> **Current scope:** this repository exposes the backend API and local service stack. Frontend, versioning, OCR, cancellation, and document deletion are described in [PRD.md](PRD.md) but are not yet implemented here.









| Layer | Technology | Responsibility |
| --- | --- | --- |
| API | FastAPI | Upload, indexing, and generation endpoints |
| Storage | MinIO | S3-compatible document storage |
| Retrieval | ChromaDB | Persistent vector collection and similarity search |
| Generation | Ollama | Local `llama3.2:3b` answer generation |
| Parsing | `pypdf`, `python-docx`, `antiword` | Text extraction across supported formats |

## 📦 Installation

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Git
- `curl` or another HTTP client

Clone the repository and enter its root:

```powershell
git clone https://github.com/hruthikeshb/honeywell-virtual-assistant.git
Set-Location honeywell-virtual-assistant
```

Create `.env` locally. Do not commit credentials:

```dotenv
MINIO_ROOT_USER=
MINIO_ROOT_PASSWORD=
CHROMA_PATH=
CHROMA_COLLECTION=
```

Validate and start the stack:

```powershell
docker compose config
docker compose up --build -d
```

| Service | Local address |
| --- | --- |
| FastAPI | `http://localhost:8000` |
| Swagger UI | `http://localhost:8000/docs` |
| ReDoc | `http://localhost:8000/redoc` |
| MinIO API | `http://localhost:9000` |
| MinIO Console | `http://localhost:9001` |
| Ollama | `http://localhost:11434` |

## ▶️ Usage

### 1. Upload documents

The `files` field is repeatable. The response returns a UUID for each uploaded object.

```powershell
curl.exe -X POST http://localhost:8000/upload `
	-F "files=@C:\path\to\sample.pdf" `
	-F "files=@C:\path\to\sample.docx"
```

### 2. Index a document

Pass an upload UUID to extract, chunk, embed, and persist its text:

```powershell
curl.exe -X POST http://localhost:8000/chunk-and-embed/<document-uuid>
```

### 3. Ask a question

The response includes the local model answer and the retrieved source metadata.

```powershell
curl.exe -X POST http://localhost:8000/generate `
	-H "Content-Type: application/json" `
	-d '{"question":"What is this document about?"}'
```

### 4. Stop the stack

```powershell
docker compose down
```

Use `docker compose down --volumes` when you also want to remove local MinIO, ChromaDB, and Ollama data.

## 🔌 API Reference

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/upload` | Upload one or more documents |
| `POST` | `/chunk-and-embed/{document_id}` | Parse and index one document |
| `POST` | `/generate` | Retrieve context and generate an answer |

Open [`/docs`](http://localhost:8000/docs) for the executable OpenAPI reference.

## 🧭 Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `MINIO_ENDPOINT` | `minio:9000` | Object storage endpoint inside Compose |
| `MINIO_BUCKET` | `honeywell-documents` | Document bucket |
| `CHROMA_HOST` | `chroma` | ChromaDB host inside Compose |
| `CHROMA_PORT` | `8000` | ChromaDB container port |
| `CHROMA_COLLECTION` | `my_documents` | Vector collection name |
| `OLLAMA_MODEL` | `llama3.2:3b` | Local generation model |
| `RETRIEVAL_K` | `5` | Number of chunks retrieved per question |

View live logs with:

```powershell
docker compose logs -f
docker compose logs -f api
```

## 🤝 Contributing

1. Create a focused branch from `main`.
2. Keep changes small and document behavior changes.
3. Run `docker compose config` and exercise the affected API flow.
4. Open an issue for bugs or a pull request with a concise problem statement and test notes.

## 📄 License

No `LICENSE` file is currently included in this repository. Licensing terms should be added before distributing or reusing the project.

