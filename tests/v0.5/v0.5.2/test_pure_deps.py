import importlib
import unittest

from api.deps import (
    get_chunker,
    get_embeddings,
    get_generator,
    get_ingestion_service,
    get_parser,
    get_rag_service,
    get_retriever,
    get_uploader,
)
from services.ingestion_service import IngestionService
from services.rag_service import RAGService


class TestPureDeps(unittest.TestCase):
    def test_legacy_dependencies_module_deleted(self):
        """Assert that api.dependencies module is deleted and fails on import."""
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("api.dependencies")

    def test_pure_deps_caching(self):
        """Verify @lru_cache behavior on all pure component providers."""
        self.assertIs(get_uploader(), get_uploader())
        self.assertIs(get_parser(), get_parser())
        self.assertIs(get_chunker(), get_chunker())
        self.assertIs(get_embeddings(), get_embeddings())
        self.assertIs(get_retriever(), get_retriever())
        self.assertIs(get_generator(), get_generator())

    def test_service_wiring(self):
        """Verify constructor injection and wiring for IngestionService and RAGService."""
        ingestion_svc = get_ingestion_service()
        self.assertIsInstance(ingestion_svc, IngestionService)
        self.assertIs(ingestion_svc.uploader, get_uploader())
        self.assertIs(ingestion_svc.parser, get_parser())
        self.assertIs(ingestion_svc.chunker, get_chunker())
        self.assertIs(ingestion_svc.embeddings, get_embeddings())
        self.assertIs(ingestion_svc.retriever, get_retriever())

        rag_svc = get_rag_service()
        self.assertIsInstance(rag_svc, RAGService)
        self.assertIs(rag_svc.retriever, get_retriever())
        self.assertIs(rag_svc.generator, get_generator())


if __name__ == "__main__":
    unittest.main()

