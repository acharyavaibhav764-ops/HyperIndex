# Implementation Plan: Unified Environment Configuration & Docker Compose Integration

## 1. Executive Summary & Objective

Currently, environment configuration across the project is fragmented:
1. **[`.env.example`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/.env.example)** only lists 5 variables, omitting dozens of pipeline and infrastructure parameters defined in [`config.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/config.py) and [`core/pipeline_config.py`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/core/pipeline_config.py).
2. **[`docker-compose.yml`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/docker-compose.yml)** hardcodes a partial subset of pipeline variables under `environment:` (e.g., `OLLAMA_MODEL: llama3.2:3b`, `RETRIEVAL_K: "5"`) while missing others (`EMBEDDING_MODEL`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, VLM toggles).
3. **Docker Compose does not load `.env` into the `api` container**: Because `env_file: - .env` is absent, any custom configuration written to `.env` is silently dropped by Docker Compose unless manually re-declared in `docker-compose.yml`.

### Objective
- Establish [`.env.example`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/.env.example) as the **exhaustive master catalog** of all configurable environment variables across the application.
- Configure [`docker-compose.yml`](file:///c:/Users/ADMIN/OneDrive/Desktop/Honeywell%20Project/honeywell-project/docker-compose.yml) to automatically ingest `.env` via `env_file: - .env`.
- Ensure clean separation between **developer-tunable variables** (models, chunking, prompts, credentials in `.env`) and **container networking invariants** (internal service hostnames in `docker-compose.yml`).

---

## 2. Configuration Hierarchy & Precedence

Docker Compose has a built-in precedence rule:
> **Variables in `environment:` override variables in `env_file:`, which override code defaults.**

This creates the ideal structure:
```
                      ┌──────────────────────────────────────────┐
                      │  Code Dataclass Defaults                 │
                      │  (config.py & core/pipeline_config.py)   │
                      └────────────────────┬─────────────────────┘
                                           │ (overridden by)
                                           ▼
                      ┌──────────────────────────────────────────┐
                      │  Local .env File                         │
                      │  (Ingested via env_file in Compose)      │
                      │  Controls: models, chunk sizes, secrets  │
                      └────────────────────┬─────────────────────┘
                                           │ (overridden by)
                                           ▼
                      ┌──────────────────────────────────────────┐
                      │  docker-compose.yml `environment:`       │
                      │  Controls ONLY Docker networking routes: │
                      │  CHROMA_HOST=chroma, MINIO=minio:9000    │
                      └──────────────────────────────────────────┘
```

---

## 3. Detailed Specifications

### 3.1. Complete Master Template: `.env.example`
Organize all parameters into clean sections matching `config.py` and `core/pipeline_config.py`:

```env
# ==============================================================================
# INFRASTRUCTURE & EXTERNAL SERVICES (config.py)
# ==============================================================================

# Database
DATABASE_URL=sqlite:///./honeywell.db

# MinIO Object Storage
MINIO_ENDPOINT=minio:9000
MINIO_BUCKET=honeywell-documents
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=change-me-too
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=change-me-too

# ChromaDB Vector Store
CHROMA_HOST=
CHROMA_PORT=8000
CHROMA_PATH=./chroma_data
CHROMA_COLLECTION=my_documents

# Ollama LLM Service Endpoint
OLLAMA_HOST=ollama
OLLAMA_PORT=11434


# ==============================================================================
# RAG PIPELINE CONFIGURATION (core/pipeline_config.py)
# ==============================================================================

# Uploader
UPLOAD_MAX_FILE_SIZE_MB=50

# Document Conversion & Parsing
LIBREOFFICE_BINARY=
LIBREOFFICE_TIMEOUT_SECONDS=60

# Vision-Language Model (VLM) Picture Description
PICTURE_DESCRIPTION_PRESET=smolvlm
PICTURE_DESCRIPTION_PROMPT="Describe this image in 2-3 sentences. Be concise and accurate."
ENABLE_PICTURE_DESCRIPTION=false

# Chunking Parameters
CHUNK_SIZE=1000
CHUNK_OVERLAP=200
CHUNKER_TOKENIZER=sentence-transformers/all-MiniLM-L6-v2

# Embedding Model
EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
EMBEDDING_DEVICE=cpu

# Retrieval Parameters
RETRIEVAL_K=5

# Generation & LLM Model
OLLAMA_MODEL=llama3.2:3b
SYSTEM_PROMPT=
PROMPT_TEMPLATE=
```

---

### 3.2. Docker Compose Refactoring: `docker-compose.yml`

In `docker-compose.yml`, update the `api` service:
1. Add `env_file: - .env`.
2. Strip out pipeline hyperparameters (`RETRIEVAL_K`, `OLLAMA_MODEL`) from the `environment:` block so they are governed by `.env`.
3. Keep only container-internal DNS network routing and essential container runtime flags in `environment:`.

#### Target `docker-compose.yml` (`api` service):
```yaml
  api:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: honeywell_api
    depends_on:
      minio:
        condition: service_healthy
      chroma:
        condition: service_healthy
      ollama:
        condition: service_healthy
    env_file:
      - .env
    environment:
      # Container-internal network bridges (must override host localhost settings)
      MINIO_ENDPOINT: minio:9000
      MINIO_ACCESS_KEY: ${MINIO_ROOT_USER}
      MINIO_SECRET_KEY: ${MINIO_ROOT_PASSWORD}
      MINIO_BUCKET: ${MINIO_BUCKET:-honeywell-files}
      CHROMA_HOST: chroma
      CHROMA_PORT: "8000"
      OLLAMA_HOST: ollama
      OLLAMA_PORT: "11434"
      PYTHONUNBUFFERED: "1"
    ports:
      - "8000:8000"
    volumes:
      - .:/code
    command: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 4. Phased Implementation Sequence

### Phase 1: Update `.env.example`
- Populate `.env.example` with the full catalog of variables across both `config.py` and `core/pipeline_config.py`.
- Include comments and documentation for each section.

### Phase 2: Update `docker-compose.yml`
- Add `env_file: - .env` to the `api` service.
- Clean up duplicate hyperparameters in `environment:`, retaining only internal network addresses.

### Phase 3: Reconcile Local `.env`
- Ensure local `.env` has local development preferences (e.g., `EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2` so local runs don't download unneeded models).

### Phase 4: Non-Executing Verification
- Run `docker compose config` (dry-run syntax and interpolation validation, without building or starting containers).
- Verify that variable interpolation functions as expected.

---

## 5. Summary of Benefits

- **Zero Duplication**: Variables are set once in `.env` and automatically ingested everywhere.
- **Consistent Developer Experience**: Changing a setting in `.env` behaves identically whether running locally with Python or inside Docker Compose.
- **Self-Documenting**: New teammates can clone the repository, run `cp .env.example .env`, and instantly see all available configuration options.

