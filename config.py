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

    # Ollama Service Endpoint
    ollama_host: str = os.getenv("OLLAMA_HOST", "ollama")
    ollama_port: str = os.getenv("OLLAMA_PORT", "11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

    # RAG & Ingestion Parameters
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "1000"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "200"))
    retrieval_k: int = int(os.getenv("RETRIEVAL_K", "5"))
    chunker_tokenizer: str = os.getenv(
        "CHUNKER_TOKENIZER", "sentence-transformers/all-MiniLM-L6-v2"
    )

    # PDF Per-Page Triage & Routing
    enable_pdf_page_router: bool = (
        os.getenv("ENABLE_PDF_PAGE_ROUTER", "true").lower() == "true"
    )
    pdf_min_text_chars_for_text_route: int = int(os.getenv("PDF_MIN_TEXT_CHARS_FOR_TEXT_ROUTE", "800"))
    pdf_text_layer_min_chars: int = int(os.getenv("PDF_TEXT_LAYER_MIN_CHARS", "40"))
    pdf_ocr_on_text_pages: bool = os.getenv("PDF_ALLOW_OCR_ON_TEXT_PAGES", "false").lower() == "true"
    pdf_v57_cleanup: bool = os.getenv("PDF_V57_CLEANUP", "true").lower() == "true"
    pdf_smolvlm_max_new_tokens: int = int(os.getenv("PDF_SMOLVLM_MAX_NEW_TOKENS", "200"))
    pdf_boilerplate_min_page_repeats: int = int(os.getenv("PDF_BOILERPLATE_MIN_PAGE_REPEATS", "3"))
    pdf_debug_heading_dump: bool = bool(int(os.getenv("PDF_DEBUG_HEADING_DUMP", "0")))

    # Visual Domain & Coverage Transforms (v5.9 switches)
    pdf_v59_cellmarks: bool = os.getenv("PDF_V59_CELLMARKS", "true").lower() == "true"
    pdf_mark_repeat_min: int = int(os.getenv("PDF_MARK_REPEAT_MIN", "3"))
    pdf_v59_coverage: bool = os.getenv("PDF_V59_COVERAGE", "true").lower() == "true"
    pdf_coverage_recall_min: float = float(os.getenv("PDF_COVERAGE_RECALL_MIN", "0.9"))
    pdf_coverage_near_match: float = float(os.getenv("PDF_COVERAGE_NEAR_MATCH", "0.75"))
    pdf_figure_mode: str = os.getenv("PDF_FIGURE_MODE", "labels_only")  # off / labels_only / vlm_fallback
    pdf_v59_table_crosscheck: bool = os.getenv("PDF_V59_TABLE_CROSSCHECK", "true").lower() == "true"

    # Chunking & Post-processing
    chunk_postprocess: bool = os.getenv("CHUNK_POSTPROCESS", "true").lower() == "true"
    chunk_v59_tables: bool = os.getenv("CHUNK_V59_TABLES", "true").lower() == "true"
    pdf_v59_toc: bool = os.getenv("PDF_V59_TOC", "true").lower() == "true"
    pdf_table_repeat_header: bool = os.getenv("PDF_TABLE_REPEAT_HEADER", "true").lower() == "true"
    chunk_header_cap_tokens: int = int(os.getenv("CHUNK_HEADER_CAP_TOKENS", "64"))


settings = Settings()
