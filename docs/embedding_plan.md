# Implementation Plan: Dynamic Embedding Model Integration

## 1. Problem Statement & Context

Currently, `core/pipeline_config.py` defines:
```python
# Embedder
embedding_model: str = os.getenv(
    "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
```

However, `core/embeddings.py` implements:
```python
class Embeddings:
    def __init__(self, embedding_function: Any = None) -> None:
        self.function = embedding_function or DefaultEmbeddingFunction()
```

### The Issue
- `Embeddings.__init__` does not accept a `model_name` argument.
- `Embeddings` does not import or inspect `pipeline_settings.embedding_model`.
- It unconditionally defaults to ChromaDB's hardcoded `DefaultEmbeddingFunction()` (an ONNX-wrapped `all-MiniLM-L6-v2`).
- As a consequence, altering `EMBEDDING_MODEL` in `.env` or changing `pipeline_settings.embedding_model` has **zero effect**, giving a false impression of model configurability.

---

## 2. Target Design & Architecture

```
pipeline_settings.embedding_model (or constructor override)
                │
                ▼
        Embeddings.__init__()
                │
                ▼
    Embedding Function Resolver
    ┌───────────────────────────────────────────────┐
    │ 1. Explicit `embedding_function` provided?    │ ──► Use directly (Mock/Custom)
    │ 2. Default MiniLM alias requested?            │ ──► DefaultEmbeddingFunction() (Fast ONNX)
    │ 3. Custom model requested?                    │ ──► SentenceTransformerEmbeddingFunction(model_name)
    │ 4. Fallback on missing dependencies?          │ ──► DefaultEmbeddingFunction() (Safe Fallback)
    └───────────────────────────────────────────────┘
                │
                ▼
      ChromaDB Collection & Ingestion Service
```

### Key Requirements
1. **Dynamic Model Resolution**: When `model_name` (or `pipeline_settings.embedding_model`) changes, `Embeddings` must instantiate the corresponding model.
2. **Preserve ChromaDB Compatibility**: The underlying callable must satisfy ChromaDB's `EmbeddingFunction` protocol:
   - Callable signature: `__call__(self, input: Documents) -> Embeddings`
   - Compatible with `collection.query(query_texts=[...])` and `collection.upsert(...)`.
3. **Graceful Fallbacks & Local Execution**:
   - When using default `all-MiniLM-L6-v2` / `sentence-transformers/all-MiniLM-L6-v2`, retain ChromaDB's fast ONNX runtime `DefaultEmbeddingFunction()` to avoid network downloads or extra dependency overhead.
   - For arbitrary Hugging Face models, attempt loading via `SentenceTransformerEmbeddingFunction` and gracefully fall back with informative logging if dependencies are unavailable.
4. **Testability & Mockability**: Retain `embedding_function: Any = None` in `__init__` so test suites can inject lightweight mock callables.

---

## 3. Implementation Phases

### Phase 1: Configuration Expansion (`core/pipeline_config.py`)
Add hardware/device configuration to the `# Embedder` section of `PipelineSettings`:
```python
    # Embedder
    embedding_model: str = os.getenv(
        "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
    )
    embedding_device: str = os.getenv("EMBEDDING_DEVICE", "cpu")
```

### Phase 2: Embeddings Resolver Implementation (`core/embeddings.py`)
Refactor `Embeddings` to accept `model_name` and `device`, sourcing defaults from `pipeline_settings`:
```python
from __future__ import annotations

import logging
from typing import Any
from chromadb.utils.embedding_functions import (
    DefaultEmbeddingFunction,
    SentenceTransformerEmbeddingFunction,
)

from core.pipeline_config import pipeline_settings

logger = logging.getLogger(__name__)


class Embeddings:
    """
    Generate vector embeddings for text chunks using configurable models.

    Attributes:
        model_name: Identifier of the embedding model.
        device: Target execution device ('cpu', 'cuda', etc.).
        function: Callable implementing ChromaDB's embedding protocol.

    Methods:
        embed(texts): Generate vector embeddings for a list of strings.
    """

    def __init__(
        self,
        model_name: str | None = None,
        embedding_function: Any = None,
        device: str | None = None,
    ) -> None:
        self.model_name = model_name or pipeline_settings.embedding_model
        self.device = device or pipeline_settings.embedding_device

        if embedding_function is not None:
            self.function = embedding_function
        else:
            self.function = self._resolve_embedding_function(self.model_name, self.device)

    def _resolve_embedding_function(self, model_name: str, device: str) -> Any:
        """Resolve model name to a ChromaDB-compatible embedding function."""
        default_aliases = {
            "all-minilm-l6-v2",
            "sentence-transformers/all-minilm-l6-v2",
            "default",
        }
        if model_name.strip().lower() in default_aliases:
            logger.info("Using built-in ONNX DefaultEmbeddingFunction for %s", model_name)
            return DefaultEmbeddingFunction()

        try:
            logger.info("Resolving SentenceTransformer model %r on device %r", model_name, device)
            return SentenceTransformerEmbeddingFunction(
                model_name=model_name,
                device=device,
            )
        except (ImportError, ValueError) as err:
            logger.warning(
                "Could not load SentenceTransformer for %r (%s). Falling back to DefaultEmbeddingFunction.",
                model_name,
                err,
            )
            return DefaultEmbeddingFunction()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate vector embeddings for a list of text strings."""
        if not texts:
            return []
        return self.function(texts)
```

### Phase 3: Dependency Injection Wiring (`api/deps.py`)
Ensure the singleton provider passes configured pipeline parameters:
```python
@lru_cache
def get_embeddings() -> Embeddings:
    return Embeddings(
        model_name=pipeline_settings.embedding_model,
        device=pipeline_settings.embedding_device,
    )
```

### Phase 4: Unit & Integration Test Suite (`tests/unit/test_embeddings.py`)
Author a dedicated test suite with comprehensive assertions covering configuration overrides, mock injection, and edge cases.

---

## 4. Test Suite Specification (`tests/unit/test_embeddings.py`)

```python
import importlib
import pytest
from unittest.mock import MagicMock, patch
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

import core.pipeline_config as pipeline_cfg
from core.embeddings import Embeddings


class TestEmbeddingsConfiguration:
    """Test dynamic model configuration and resolution in Embeddings."""

    def test_default_model_uses_onnx_function(self):
        """Default model name should resolve to DefaultEmbeddingFunction."""
        emb = Embeddings()
        assert emb.model_name == "sentence-transformers/all-MiniLM-L6-v2"
        assert isinstance(emb.function, DefaultEmbeddingFunction)

    def test_explicit_embedding_function_injection(self):
        """Passing an explicit embedding_function should bypass resolution (mocking support)."""
        mock_fn = MagicMock(return_value=[[0.1, 0.2, 0.3]])
        emb = Embeddings(embedding_function=mock_fn)
        assert emb.function is mock_fn

        res = emb.embed(["sample query"])
        mock_fn.assert_called_once_with(["sample query"])
        assert res == [[0.1, 0.2, 0.3]]

    def test_constructor_model_name_override(self):
        """Constructor model_name argument should override pipeline defaults."""
        emb = Embeddings(model_name="all-MiniLM-L6-v2")
        assert emb.model_name == "all-MiniLM-L6-v2"
        assert isinstance(emb.function, DefaultEmbeddingFunction)

    def test_environment_variable_override(self, monkeypatch):
        """Setting EMBEDDING_MODEL environment variable should be reflected in Embeddings."""
        monkeypatch.setenv("EMBEDDING_MODEL", "custom-org/custom-embedder")
        importlib.reload(pipeline_cfg)

        with patch("core.embeddings.SentenceTransformerEmbeddingFunction") as mock_st:
            mock_instance = MagicMock()
            mock_st.return_value = mock_instance

            emb = Embeddings()
            assert emb.model_name == "custom-org/custom-embedder"
            assert emb.function is mock_instance

    def test_fallback_when_sentence_transformer_unavailable(self):
        """If a custom model cannot be loaded (missing package), it should safely fall back."""
        with patch(
            "core.embeddings.SentenceTransformerEmbeddingFunction",
            side_effect=ImportError("No module named 'sentence_transformers'"),
        ):
            emb = Embeddings(model_name="BAAI/bge-small-en-v1.5")
            assert isinstance(emb.function, DefaultEmbeddingFunction)

    def test_empty_input_handling(self):
        """Calling embed([]) should return an empty list without error."""
        emb = Embeddings()
        assert emb.embed([]) == []

    def test_embedding_output_structure(self):
        """Valid text input should produce a list of float vectors."""
        emb = Embeddings()
        result = emb.embed(["Honeywell nurse call system"])
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], list)
        assert len(result[0]) == 384  # MiniLM-L6-v2 dimension
        assert all(isinstance(val, float) for val in result[0])


class TestEmbeddingsDependencyInjection:
    """Test FastAPI dependency provider integration."""

    def test_get_embeddings_singleton(self):
        from api.deps import get_embeddings
        get_embeddings.cache_clear()

        e1 = get_embeddings()
        e2 = get_embeddings()
        assert e1 is e2
        assert isinstance(e1, Embeddings)
```

---

## 5. Verification & Validation Steps

1. **Unit Testing**:
   - Run `pytest tests/unit/test_embeddings.py -v`.
   - Verify all 8 test cases pass.
2. **Provider & Service Regression Testing**:
   - Run `pytest tests/v0.5/v0.5.2/test_pure_deps.py -v` to ensure dependency injection in FastAPI routers and services is intact.
3. **Pipeline Ingestion & Retrieval Verification**:
   - Run `pytest tests/v0.5/v0.5.1/test_services.py -v` to confirm end-to-end compatibility with `IngestionService` and `RAGService`.
