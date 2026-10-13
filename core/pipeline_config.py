import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class PipelineSettings:
    """Unified configuration for RAG ingestion, parsing, chunking, retrieval, and generation."""


    # UPLOADER

    upload_max_file_size_mb: int = int(os.getenv("UPLOAD_MAX_FILE_SIZE_MB", "50"))


    # PARSER

    # Docling & Vision-Language Model (VLM) Picture Description
    picture_description_preset: str = os.getenv("PICTURE_DESCRIPTION_PRESET", "smolvlm")
    picture_description_prompt: str = os.getenv(
        "PICTURE_DESCRIPTION_PROMPT",
        "Describe this image in 2-3 sentences. Be concise and accurate.",
    )
    enable_picture_description: bool = (
        os.getenv("ENABLE_PICTURE_DESCRIPTION", "false").lower() == "true"
    )

    # LibreOffice Headless Bridge (.doc / .ppt)
    libreoffice_binary: str = os.getenv("LIBREOFFICE_BINARY", "")
    libreoffice_timeout_seconds: int = int(os.getenv("LIBREOFFICE_TIMEOUT_SECONDS", "60"))


    # CHUNKER

    chunk_size: int = int(os.getenv("CHUNK_SIZE", "1000"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "200"))
    chunker_tokenizer: str = os.getenv(
        "CHUNKER_TOKENIZER", "sentence-transformers/all-MiniLM-L6-v2"
    )


    # EMBEDDER

    embedding_model: str = os.getenv(
        "EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5"
    )
    embedding_device: str = os.getenv("EMBEDDING_DEVICE", "cpu")


    # RETRIEVER

    retrieval_k: int = int(os.getenv("RETRIEVAL_K", "5"))


    # GENERATOR

    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    system_prompt: str | None = os.getenv("SYSTEM_PROMPT")
    prompt_template: str | None = os.getenv("PROMPT_TEMPLATE")


pipeline_settings = PipelineSettings()

