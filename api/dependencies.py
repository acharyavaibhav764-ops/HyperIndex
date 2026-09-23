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

# Global shared singletons (backward-compatibility shims for legacy callers)
uploader = get_uploader()
parser = get_parser()
chunker = get_chunker()
embeddings = get_embeddings()
retriever = get_retriever()
generator = get_generator()

__all__ = [
    "uploader",
    "parser",
    "chunker",
    "embeddings",
    "retriever",
    "generator",
    "get_uploader",
    "get_parser",
    "get_chunker",
    "get_embeddings",
    "get_retriever",
    "get_generator",
    "get_ingestion_service",
    "get_rag_service",
]
