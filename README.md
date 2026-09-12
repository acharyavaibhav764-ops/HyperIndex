# Honeywell Project

## Environment Setup

Follow these steps to run the current development environment locally.

### 1. Install prerequisites

Install the following tools:

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Git
- `curl` or another HTTP client for testing the API

After installing Docker Desktop, open it and confirm that the Docker engine is running.

### 2. Open the project

Clone the repository and move into the project directory:

```powershell
git clone <repository-url>
Set-Location HONEYWELL
```

If the repository is already available locally, open a terminal in its root directory, beside `docker-compose.yml`.

### 3. Create the environment file

Create a file named `.env` in the project root. Use local development credentials such as:

```dotenv
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=change-me-too
```

Replace the example values with your own local credentials. Never commit `.env` or production credentials to source control.

### 4. Validate the configuration

From the project root, run:

```powershell
docker compose config
```

This confirms that Docker Compose can read the environment variables and render the service configuration successfully.

### 5. Build and start the services

Start MinIO and the FastAPI backend:

```powershell
docker compose up --build
```

Keep this terminal open to view live logs. To start the services in the background, use:

```powershell
docker compose up --build -d
```

The services are available at:

| Service | Address |
| --- | --- |
| FastAPI backend | `http://localhost:8000` |
| FastAPI Swagger UI | `http://localhost:8000/docs` |
| FastAPI ReDoc | `http://localhost:8000/redoc` |
| MinIO API | `http://localhost:9000` |
| MinIO Console | `http://localhost:9001` |

### 6. Verify the backend

Check that the API is responding:

```powershell
curl http://localhost:8000/docs
```

Upload a file. Replace the path with a real local file:

```powershell
curl.exe -X POST http://localhost:8000/upload `
	-F "files=@C:\path\to\sample.pdf" `
	-F "files=@C:\path\to\sample.docx"
```

The `files` field is repeatable. In Swagger, select one file, click **Add string item**, select the next file, and then click **Execute**.

The response contains the UUID, original filename, and size for every uploaded file. Each file is stored directly in the bucket using its UUID as the object name:

```text
<bucket-name>/<file-uuid>
```

The backend creates the `honeywell-files` bucket in MinIO when it starts.

### 8. Chunk and embed uploaded files

Call the processing endpoint with the UUIDs returned by `/upload`:

```powershell
curl.exe -X POST http://localhost:8000/chunk-and-embed/<file-uuid>
```

All chunks and embeddings are stored in ChromaDB. The response returns only chunk text and metadata at indexes `0, 10, 20, ...`; embeddings are not returned to the frontend. In Docker, the API connects to the Chroma service at `http://chroma:8000`; Chroma is exposed locally at `http://localhost:8001`.

To inspect ChromaDB, use `http://localhost:8001/api/v1/heartbeat` to verify that it is running. The Chroma service has no built-in visual dashboard; use the Chroma client or API endpoints against `http://localhost:8001` to inspect collections and records.

### 9. Generate answers locally

Ollama runs in Docker, so you do not need to install Ollama separately on your laptop. Start the stack and download the model once into the persistent `ollama_data` volume:

```powershell
docker compose up -d --build
docker compose exec ollama ollama pull llama3.2:3b
```

Ask a question after indexing at least one document:

```powershell
curl.exe -X POST http://localhost:8000/generate `
	-H "Content-Type: application/json" `
	-d '{"question":"What is this document about?"}'
```

The endpoint retrieves the five closest chunks from ChromaDB and returns the local model answer with source metadata. The model remains loaded between requests through `keep_alive` and the model files survive container restarts in `ollama_data`.

For GPU acceleration, install the appropriate Docker GPU runtime on the host and configure the Ollama service for it. A CPU-only laptop can use `llama3.2:3b`, but generation will be slower.

### 10. View service logs

View logs for all services:

```powershell
docker compose logs -f
```

View only backend logs:

```powershell
docker compose logs -f api
```

### 11. Stop the environment

Stop the running containers while preserving local database and object-storage data:

```powershell
docker compose down
```

To stop the containers and delete the persisted local volumes:

```powershell
docker compose down --volumes
```

## Current Services

The development stack contains:

- **MinIO:** S3-compatible object storage for uploaded files
- **ChromaDB:** Persistent vector database for chunks and embeddings
- **Ollama:** Local generation model server
- **FastAPI backend:** multi-file upload API

Document parsing, chunking, embeddings, retrieval, and local generation are included for PDF, text, Markdown, DOCX, and legacy DOC documents.

