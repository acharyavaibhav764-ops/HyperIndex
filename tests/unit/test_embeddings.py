import importlib
import unittest
from unittest.mock import MagicMock, patch

from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

import core.pipeline_config as pipeline_cfg
from core.embeddings import Embeddings


class TestEmbeddingsConfiguration(unittest.TestCase):
    """Test dynamic model configuration and resolution in Embeddings."""

    def test_minilm_model_uses_onnx_function(self):
        """MiniLM model name should resolve to DefaultEmbeddingFunction."""
        emb = Embeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        self.assertEqual(emb.model_name, "sentence-transformers/all-MiniLM-L6-v2")
        self.assertIsInstance(emb.function, DefaultEmbeddingFunction)

    def test_codebase_default_model_fallback(self):
        """When EMBEDDING_MODEL is unset and no local .env overrides it, defaults to BAAI/bge-base-en-v1.5."""
        with patch("dotenv.load_dotenv"):
            with patch.dict("os.environ", {}, clear=True):
                importlib.reload(pipeline_cfg)
                try:
                    self.assertEqual(pipeline_cfg.pipeline_settings.embedding_model, "BAAI/bge-base-en-v1.5")
                finally:
                    importlib.reload(pipeline_cfg)

    def test_local_default_model_uses_onnx_function(self):
        """Locally configured model resolves without re-downloading."""
        emb = Embeddings()
        self.assertIsInstance(emb.function, DefaultEmbeddingFunction)

    def test_explicit_embedding_function_injection(self):
        """Passing an explicit embedding_function should bypass resolution (mocking support)."""
        mock_fn = MagicMock(return_value=[[0.1, 0.2, 0.3]])
        emb = Embeddings(embedding_function=mock_fn)
        self.assertIs(emb.function, mock_fn)

        res = emb.embed(["sample query"])
        mock_fn.assert_called_once_with(["sample query"])
        self.assertEqual(res, [[0.1, 0.2, 0.3]])

    def test_constructor_model_name_override(self):
        """Constructor model_name argument should override pipeline defaults."""
        emb = Embeddings(model_name="all-MiniLM-L6-v2")
        self.assertEqual(emb.model_name, "all-MiniLM-L6-v2")
        self.assertIsInstance(emb.function, DefaultEmbeddingFunction)

    def test_environment_variable_override(self):
        """Setting EMBEDDING_MODEL environment variable should be reflected in Embeddings."""
        with patch.dict("os.environ", {"EMBEDDING_MODEL": "custom-org/custom-embedder"}):
            importlib.reload(pipeline_cfg)
            try:
                with patch("core.embeddings.SentenceTransformerEmbeddingFunction") as mock_st:
                    mock_instance = MagicMock()
                    mock_st.return_value = mock_instance

                    emb = Embeddings()
                    self.assertEqual(emb.model_name, "custom-org/custom-embedder")
                    self.assertIs(emb.function, mock_instance)
            finally:
                importlib.reload(pipeline_cfg)

    def test_fallback_when_sentence_transformer_unavailable(self):
        """If a custom model cannot be loaded (missing package), it should safely fall back."""
        with patch(
            "core.embeddings.SentenceTransformerEmbeddingFunction",
            side_effect=ImportError("No module named 'sentence_transformers'"),
        ):
            emb = Embeddings(model_name="BAAI/bge-small-en-v1.5")
            self.assertIsInstance(emb.function, DefaultEmbeddingFunction)

    def test_empty_input_handling(self):
        """Calling embed([]) should return an empty list without error."""
        emb = Embeddings()
        self.assertEqual(emb.embed([]), [])

    def test_embedding_output_structure(self):
        """Valid text input should produce a list of float vectors with expected dimensions."""
        emb = Embeddings()
        result = emb.embed(["Honeywell nurse call system"])
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], list)
        self.assertEqual(len(result[0]), 384)  # MiniLM-L6-v2 dimension
        self.assertTrue(all(isinstance(val, float) for val in result[0]))


class TestEmbeddingsDependencyInjection(unittest.TestCase):
    """Test FastAPI dependency provider integration."""

    def test_get_embeddings_singleton(self):
        from api.deps import get_embeddings
        get_embeddings.cache_clear()

        e1 = get_embeddings()
        e2 = get_embeddings()
        self.assertIs(e1, e2)
        self.assertIsInstance(e1, Embeddings)


if __name__ == "__main__":
    unittest.main()

