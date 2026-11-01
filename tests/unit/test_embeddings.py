import importlib
import unittest
from unittest.mock import MagicMock, patch

import core.pipeline_config as pipeline_cfg
from core.embeddings import (
    DEFAULT_FALLBACK_MODEL,
    Embeddings,
    SentenceTransformerCallable,
)


class TestEmbeddingsConfiguration(unittest.TestCase):
    """Test dynamic model configuration and resolution in decoupled Embeddings."""

    @patch("core.embeddings.SentenceTransformer")
    def test_minilm_model_resolution(self, mock_st_cls):
        """MiniLM model name should load via SentenceTransformer."""
        emb = Embeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        self.assertEqual(emb.model_name, "sentence-transformers/all-MiniLM-L6-v2")
        self.assertIsInstance(emb.function, SentenceTransformerCallable)
        self.assertEqual(emb.function.model_name, "sentence-transformers/all-MiniLM-L6-v2")
        mock_st_cls.assert_called_with("sentence-transformers/all-MiniLM-L6-v2", device="cpu")

    def test_codebase_default_model_fallback(self):
        """When EMBEDDING_MODEL is unset and no local .env overrides it, defaults to BAAI/bge-base-en-v1.5."""
        with patch("dotenv.load_dotenv"):
            with patch.dict("os.environ", {}, clear=True):
                importlib.reload(pipeline_cfg)
                try:
                    self.assertEqual(
                        pipeline_cfg.pipeline_settings.embedding_model,
                        "BAAI/bge-base-en-v1.5",
                    )
                finally:
                    importlib.reload(pipeline_cfg)

    @patch("core.embeddings.SentenceTransformer")
    def test_custom_model_resolution(self, mock_st_cls):
        """Custom model name should be passed directly to SentenceTransformer."""
        emb = Embeddings(model_name="BAAI/bge-base-en-v1.5", device="cpu")
        self.assertEqual(emb.model_name, "BAAI/bge-base-en-v1.5")
        self.assertIsInstance(emb.function, SentenceTransformerCallable)
        self.assertEqual(emb.function.model_name, "BAAI/bge-base-en-v1.5")
        mock_st_cls.assert_called_with("BAAI/bge-base-en-v1.5", device="cpu")

    @patch("core.embeddings.SentenceTransformer")
    def test_device_selection_forwarding(self, mock_st_cls):
        """Device selection (e.g. cuda) should be forwarded to SentenceTransformer."""
        emb = Embeddings(model_name="BAAI/bge-small-en-v1.5", device="cuda")
        self.assertEqual(emb.device, "cuda")
        mock_st_cls.assert_called_with("BAAI/bge-small-en-v1.5", device="cuda")

    @patch("core.embeddings.SentenceTransformer")
    def test_explicit_embedding_function_override(self, mock_st_cls):
        """Assigning an explicit function attribute should override vector generation (mocking support)."""
        emb = Embeddings()
        mock_fn = MagicMock(return_value=[[0.1, 0.2, 0.3]])
        emb.function = mock_fn

        res = emb.embed(["sample query"])
        mock_fn.assert_called_once_with(["sample query"])
        self.assertEqual(res, [[0.1, 0.2, 0.3]])

    @patch("core.embeddings.SentenceTransformer")
    def test_environment_variable_override(self, mock_st_cls):
        """Setting EMBEDDING_MODEL environment variable should be reflected in Embeddings."""
        with patch.dict("os.environ", {"EMBEDDING_MODEL": "custom-org/custom-embedder"}):
            importlib.reload(pipeline_cfg)
            try:
                emb = Embeddings()
                self.assertEqual(emb.model_name, "custom-org/custom-embedder")
                mock_st_cls.assert_called_with("custom-org/custom-embedder", device="cpu")
            finally:
                importlib.reload(pipeline_cfg)

    @patch("core.embeddings.SentenceTransformer")
    def test_fallback_when_model_load_fails(self, mock_st_cls):
        """If a specified model fails to load, it should log a warning and fall back to MiniLM."""
        # Fail on first call (custom model), succeed on second call (fallback model)
        mock_st_cls.side_effect = [
            ValueError("Model not found on HuggingFace Hub"),
            MagicMock(),
        ]
        emb = Embeddings(model_name="nonexistent/invalid-model")
        self.assertIsInstance(emb.function, SentenceTransformerCallable)
        self.assertEqual(emb.function.model_name, DEFAULT_FALLBACK_MODEL)
        self.assertEqual(mock_st_cls.call_count, 2)

    @patch("core.embeddings.SentenceTransformer")
    def test_empty_input_handling(self, mock_st_cls):
        """Calling embed([]) should return an empty list without error."""
        emb = Embeddings()
        self.assertEqual(emb.embed([]), [])

    @patch("core.embeddings.SentenceTransformer")
    def test_embedding_output_structure(self, mock_st_cls):
        """Valid text input should produce normalized float lists with expected dimension."""
        mock_instance = MagicMock()
        mock_instance.encode.return_value = [[0.05] * 384]
        mock_st_cls.return_value = mock_instance

        emb = Embeddings(model_name="all-minilm-l6-v2")
        result = emb.embed(["Honeywell nurse call system"])

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], list)
        self.assertEqual(len(result[0]), 384)
        self.assertTrue(all(isinstance(val, float) for val in result[0]))

    @patch("core.embeddings.SentenceTransformer")
    def test_callable_protocol_compatibility(self, mock_st_cls):
        """The embedding function must be directly callable matching ChromaDB's required protocol."""
        mock_instance = MagicMock()
        mock_instance.encode.return_value = [[0.1, 0.2, 0.3]]
        mock_st_cls.return_value = mock_instance

        emb = Embeddings(model_name="all-minilm-l6-v2")
        # Direct call simulating ChromaDB's query_texts callback
        callback_res = emb.function(["test query"])

        self.assertEqual(callback_res, [[0.1, 0.2, 0.3]])


class TestEmbeddingsDependencyInjection(unittest.TestCase):
    """Test FastAPI dependency provider integration."""

    @patch("core.embeddings.SentenceTransformer")
    def test_get_embeddings_singleton(self, mock_st_cls):
        from api.deps import get_embeddings
        get_embeddings.cache_clear()

        e1 = get_embeddings()
        e2 = get_embeddings()
        self.assertIs(e1, e2)
        self.assertIsInstance(e1, Embeddings)


if __name__ == "__main__":
    unittest.main()
