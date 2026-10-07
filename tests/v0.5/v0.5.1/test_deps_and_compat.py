import unittest

import api.dependencies as legacy_deps
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


class TestDepsAndCompat(unittest.TestCase):
    def test_lru_cache_singleton_behavior(self):
        # Verify singletons return the same instance across invocations
        self.assertIs(get_uploader(), get_uploader())
        self.assertIs(get_parser(), get_parser())
        self.assertIs(get_chunker(), get_chunker())
        self.assertIs(get_embeddings(), get_embeddings())
        self.assertIs(get_retriever(), get_retriever())
        self.assertIs(get_generator(), get_generator())

    def test_backward_compat_dependencies(self):
        # Verify legacy module exports match get_* providers
        self.assertIs(legacy_deps.uploader, get_uploader())
        self.assertIs(legacy_deps.parser, get_parser())
        self.assertIs(legacy_deps.chunker, get_chunker())
        self.assertIs(legacy_deps.embeddings, get_embeddings())
        self.assertIs(legacy_deps.retriever, get_retriever())
        self.assertIs(legacy_deps.generator, get_generator())

        # Verify legacy module exports the get_* factory functions too
        self.assertIs(legacy_deps.get_uploader, get_uploader)
        self.assertIs(legacy_deps.get_parser, get_parser)
        self.assertIs(legacy_deps.get_chunker, get_chunker)
        self.assertIs(legacy_deps.get_embeddings, get_embeddings)
        self.assertIs(legacy_deps.get_retriever, get_retriever)
        self.assertIs(legacy_deps.get_generator, get_generator)
        self.assertIs(legacy_deps.get_ingestion_service, get_ingestion_service)
        self.assertIs(legacy_deps.get_rag_service, get_rag_service)

    def test_service_factory_creation(self):
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

