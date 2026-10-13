# Formal Implementation Plan: Configuration Unification & Consolidation

## 1. Executive Summary & Objective

Currently, configuration settings in the repository are fragmented across two distinct files with overlapping responsibilities:
1. **Root `config.py`**: Combines infrastructure endpoints (Database, MinIO, ChromaDB, Ollama) with pipeline-level hyperparameters (`chunk_size`, `chunk_overlap`, `retrieval_k`, prompt templates).
2. **Parser Config `core/parsers/config.py`**: Holds parser- and chunker-specific settings (`libreoffice_binary`, `libreoffice_timeout_seconds`, `picture_description_*`, `chunker_tokenizer`).

This causes modules like `core/chunker.py` to import from both configs simultaneously.

### The Objective
- Keep **Root `config.py`** exclusively for **global infrastructure & external service connections** (DB, MinIO, ChromaDB host/storage, Ollama network endpoint).
- Establish **`core/pipeline_config.py`** as the single source of truth for the entire **RAG ingestion & generation pipeline** (parsing, chunking, retrieval parameters, prompt templates, and models).
- Migrate all parsers, core modules, and test suites directly to `core/pipeline_config.py`.
- **Completely remove `core/parsers/config.py` in the final phase**, leaving exactly two configuration files in the entire repository:
  1. Root `config.py` (Infrastructure)
  2. `core/pipeline_config.py` (RAG Pipeline)

---

## 2. Target Configuration Architecture

```
honeywell-project/
│
├── config.py                     <-- INFRASTRUCTURE ONLY (DB, MinIO, ChromaDB host/port, Ollama host/port)
│
└── core/
    ├── pipeline_config.py        <-- CENTRAL RAG PIPELINE CONFIG (Parsers, Chunking, Retrieval, Generation)
    ├── chunker.py                <-- Reads only core.pipeline_config
    ├── generator.py              <-- Infrastructure from config.py, prompts & model from pipeline_config
    ├── retriever.py              <-- Client from config.py, retrieval_k default from pipeline_config
    └── parsers/
        ├── docling_parser.py     <-- Reads core.pipeline_config
        ├── libreoffice_converter.py <-- Reads core.pipeline_config
        └── (config.py DELETED)   <-- Permanently removed in final phase
```

### Parameter Re-distribution Matrix

| Parameter | Current Location | Target Location | Category |
| :--- | :--- | :--- | :--- |
| `database_url` | Root `config.py` | Root `config.py` | Infrastructure (Database) |
| `minio_endpoint`, `minio_bucket`, `minio_*_key` | Root `config.py` | Root `config.py` | Infrastructure (Object Store) |
| `chroma_host`, `chroma_port`, `chroma_path`, `chroma_collection` | Root `config.py` | Root `config.py` | Infrastructure (Vector Store) |
| `ollama_host`, `ollama_port` | Root `config.py` | Root `config.py` | Infrastructure (LLM Host) |
| `ollama_model` | Root `config.py` | `core/pipeline_config.py` | RAG Pipeline (Model Selection) |
| `chunk_size`, `chunk_overlap` | Root `config.py` | `core/pipeline_config.py` | RAG Pipeline (Chunking) |
| `chunker_tokenizer` | `core/parsers/config.py` | `core/pipeline_config.py` | RAG Pipeline (Chunking) |
| `retrieval_k` | Root `config.py` | `core/pipeline_config.py` | RAG Pipeline (Retrieval) |
| `system_prompt`, `prompt_template` | Root `config.py` | `core/pipeline_config.py` | RAG Pipeline (Generation) |
| `libreoffice_binary`, `libreoffice_timeout_seconds` | `core/parsers/config.py` | `core/pipeline_config.py` | RAG Pipeline (Ingestion / Conversion) |
| `picture_description_*`, `enable_picture_description` | `core/parsers/config.py` | `core/pipeline_config.py` | RAG Pipeline (Ingestion / VLM) |

---

## 3. Detailed Specification of Files

### 3.1. `core/pipeline_config.py` (New File)
```python
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineSettings:
    """Unified configuration for RAG ingestion, parsing, chunking, retrieval, and generation."""

    # Uploader
    # (Object store connection endpoints live in root config.py; ingestion/upload controls belong here)
    upload_max_file_size_mb: int = int(os.getenv("UPLOAD_MAX_FILE_SIZE_MB", "50"))

    # Parser
    # LibreOffice Headless Bridge (.doc / .ppt)
    libreoffice_binary: str = os.getenv("LIBREOFFICE_BINARY", "")
    libreoffice_timeout_seconds: int = int(os.getenv("LIBREOFFICE_TIMEOUT_SECONDS", "60"))

    # Docling & Vision-Language Model (VLM) Picture Description
    picture_description_preset: str = os.getenv("PICTURE_DESCRIPTION_PRESET", "smolvlm")
    picture_description_prompt: str = os.getenv(
        "PICTURE_DESCRIPTION_PROMPT",
        "Describe this image in 2-3 sentences. Be concise and accurate.",
    )
    enable_picture_description: bool = (
        os.getenv("ENABLE_PICTURE_DESCRIPTION", "false").lower() == "true"
    )

    # Chunker
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "1000"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "200"))
    chunker_tokenizer: str = os.getenv(
        "CHUNKER_TOKENIZER", "sentence-transformers/all-MiniLM-L6-v2"
    )

    # Embedder
    embedding_model: str = os.getenv(
        "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
    )

    # Retriever
    retrieval_k: int = int(os.getenv("RETRIEVAL_K", "5"))

    # Generator
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    system_prompt: str | None = os.getenv("SYSTEM_PROMPT")
    prompt_template: str | None = os.getenv("PROMPT_TEMPLATE")


pipeline_settings = PipelineSettings()
```

### 3.2. Root `config.py` (Cleaned Infrastructure Config)
```python
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Application infrastructure configuration with environment variable fallbacks."""

    # Database
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./honeywell.db")

    # MinIO Object Storage
    minio_endpoint: str = os.getenv("MINIO_ENDPOINT", "minio:9000")
    minio_bucket: str = os.getenv("MINIO_BUCKET", "honeywell-documents")
    minio_access_key: str = os.getenv("MINIO_ACCESS_KEY", os.getenv("MINIO_ROOT_USER", ""))
    minio_secret_key: str = os.getenv("MINIO_SECRET_KEY", os.getenv("MINIO_ROOT_PASSWORD", ""))

    # ChromaDB Vector Store
    chroma_host: str | None = os.getenv("CHROMA_HOST")
    chroma_port: int = int(os.getenv("CHROMA_PORT", "8000"))
    chroma_path: str = os.getenv("CHROMA_PATH", "./chroma_data")
    chroma_collection: str = os.getenv("CHROMA_COLLECTION", "my_documents")

    # Ollama Service Endpoint
    ollama_host: str = os.getenv("OLLAMA_HOST", "ollama")
    ollama_port: str = os.getenv("OLLAMA_PORT", "11434")


settings = Settings()
```

### 3.3. `core/parsers/config.py` (Deletion in Final Phase)
- In intermediate migration steps, all usages of `core.parsers.config` in production code and test suites will be redirected directly to `core.pipeline_config`.
- In the final phase, `core/parsers/config.py` will be deleted completely from the repository.

---

## 4. Impact Analysis & Component Refactoring

| File | Necessary Edits |
| :--- | :--- |
| `core/__init__.py` | Export `PipelineSettings` and `pipeline_settings`. |
| `core/chunker.py` | Remove dual imports (`config.settings` and `core.parsers.config.parser_settings`). Replace with `from core.pipeline_config import pipeline_settings`. Use `pipeline_settings.chunk_size`, `pipeline_settings.chunk_overlap`, `pipeline_settings.chunker_tokenizer`. |
| `core/generator.py` | Import `settings` from `config` for `ollama_host`, `ollama_port`. Import `pipeline_settings` from `core.pipeline_config` for `ollama_model`, `system_prompt`, `prompt_template`. |
| `core/retriever.py` | Keep `settings` for Chroma connection. Optional: default `k` in `retrieve(k=pipeline_settings.retrieval_k)`. |
| `core/parsers/docling_parser.py` | Replace `from .config import parser_settings` with `from core.pipeline_config import pipeline_settings`. |
| `core/parsers/libreoffice_converter.py` | Replace `from .config import parser_settings` with `from core.pipeline_config import pipeline_settings`. |
| `api/deps.py` | Import `pipeline_settings` from `core.pipeline_config`. Update `get_chunker` (`pipeline_settings.chunk_size`), `get_generator` (`pipeline_settings.ollama_model`, prompts), and `get_rag_service` (`pipeline_settings.retrieval_k`). |
| `tests/parsers/test_picture_description.py` | Update monkeypatch reload tests to target `core.pipeline_config` instead of `core.parsers.config`. |
| `tests/parsers/test_libreoffice_converter.py` | Update patch targets to `core.parsers.libreoffice_converter.settings` / `pipeline_settings`. |

---

## 5. Phased Implementation Sequence

### Phase 1: Create Central Pipeline Configuration
- Create `core/pipeline_config.py` implementing `PipelineSettings` and `pipeline_settings`.
- Export `PipelineSettings` and `pipeline_settings` from `core/__init__.py`.

### Phase 2: Refactor Core Consumers
- Refactor `core/chunker.py` to consume all chunking settings from `core.pipeline_config`.
- Refactor `core/generator.py` to consume prompt and model settings from `core.pipeline_config`.
- Refactor `core/parsers/docling_parser.py` to import `pipeline_settings` from `core.pipeline_config`.
- Refactor `core/parsers/libreoffice_converter.py` to import `pipeline_settings` from `core.pipeline_config`.

### Phase 3: Clean Root Configuration & Update Dependency Injection
- Remove pipeline-specific fields (`chunk_size`, `chunk_overlap`, `retrieval_k`, `system_prompt`, `prompt_template`, `ollama_model`) from `Settings` in root `config.py`.
- Update `api/deps.py` to wire `pipeline_settings` into chunker, generator, and RAG service providers.

### Phase 4: Migrate Test Suites
- Update all test imports and reload patches in `tests/parsers/test_picture_description.py` from `core.parsers.config` to `core.pipeline_config`.
- Verify and update `tests/parsers/test_libreoffice_converter.py` and `tests/test_generator_prompts.py`.

### Phase 5: Final Cleanup — Remove `core/parsers/config.py`
- Verify with a comprehensive repository search that zero references or imports of `core.parsers.config` remain anywhere in the codebase.
- **Permanently delete `core/parsers/config.py`**.
- Clean up any compiled `.pyc` caches in `core/parsers/__pycache__/`.

---

## 6. Verification Plan

- **Zero Residual References Check**: Run codebase-wide grep confirming zero imports of `core.parsers.config`.
- **Static Analysis & Import Sanity**: Ensure all modules cleanly import their configuration objects without circular dependencies.
- **Unit Test Execution**:
  - `tests/parsers/test_picture_description.py` (VLM options & toggles)
  - `tests/parsers/test_libreoffice_converter.py` (LibreOffice binary path resolution)
  - `tests/unit/test_chunker.py` and `tests/test_generator_prompts.py`
  - `tests/v0.5/v0.5.1/test_deps_and_compat.py` (FastAPI dependency injection tests)
