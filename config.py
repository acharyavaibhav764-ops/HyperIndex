import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Central application configuration with environment variable fallbacks."""

    # Database
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./honeywell.db")

    # MinIO
    minio_endpoint: str = os.getenv("MINIO_ENDPOINT", "minio:9000")
    minio_bucket: str = os.getenv("MINIO_BUCKET", "honeywell-documents")
    minio_access_key: str = os.getenv("MINIO_ACCESS_KEY", os.getenv("MINIO_ROOT_USER", ""))
    minio_secret_key: str = os.getenv("MINIO_SECRET_KEY", os.getenv("MINIO_ROOT_PASSWORD", ""))

    # ChromaDB
    chroma_host: str | None = os.getenv("CHROMA_HOST")
    chroma_port: int = int(os.getenv("CHROMA_PORT", "8000"))
    chroma_path: str = os.getenv("CHROMA_PATH", "./chroma_data")
    chroma_collection: str = os.getenv("CHROMA_COLLECTION", "my_documents")

    # Qdrant Vector Store
    qdrant_host: str | None = os.getenv("QDRANT_HOST")
    qdrant_port: int = int(os.getenv("QDRANT_PORT", "6333"))
    qdrant_path: str | None = os.getenv("QDRANT_PATH")
    qdrant_collection: str = os.getenv("QDRANT_COLLECTION", "honeywell_documents")

    # Ollama Service Endpoint
    ollama_host: str = os.getenv("OLLAMA_HOST", "ollama")
    ollama_port: str = os.getenv("OLLAMA_PORT", "11434")


settings = Settings()
