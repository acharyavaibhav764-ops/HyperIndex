import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Central application configuration with environment variable fallbacks."""

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

    # Ollama
    ollama_host: str = os.getenv("OLLAMA_HOST", "ollama")
    ollama_port: str = os.getenv("OLLAMA_PORT", "11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

    # RAG & Ingestion Parameters
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "1000"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "200"))
    retrieval_k: int = int(os.getenv("RETRIEVAL_K", "5"))

    # Parsing Architecture — HybridChunker tokenizer
    chunker_tokenizer: str = os.getenv(
        "CHUNKER_TOKENIZER", "sentence-transformers/all-MiniLM-L6-v2"
    )

    # Parsing Architecture v2 — local lightweight picture description (DOCX/PPTX)
    # Primary preset: smolvlm (HuggingFaceTB/SmolVLM-256M-Instruct, ~256MB VRAM, runs in-process).
    # Escalation preset: granite_vision (Granite-Vision-3.3-2B via Ollama).
    # DeepSeek-OCR2 is NOT used here — it requires ≥8GB VRAM (GTX 1650 = 4GB).
    # DeepSeek-OCR2 integration is planned for v5 (PDF branch) on production hardware.
    # See parsing_architecture_plan.md for the v6 vLLM migration note.
    picture_description_preset: str = os.getenv("PICTURE_DESCRIPTION_PRESET", "smolvlm")
    picture_description_prompt: str = os.getenv(
        "PICTURE_DESCRIPTION_PROMPT",
        "Describe this image in 2-3 sentences. Be concise and accurate.",
    )
    enable_picture_description: bool = (
        os.getenv("ENABLE_PICTURE_DESCRIPTION", "true").lower() == "true"
    )

    # Parsing Architecture v3 — LibreOffice headless converter (.doc / .ppt)
    libreoffice_binary: str = os.getenv("LIBREOFFICE_BINARY", "")
    libreoffice_timeout_seconds: int = int(os.getenv("LIBREOFFICE_TIMEOUT_SECONDS", "60"))

    # Parsing Architecture v5 — PDF per-page triage (PdfPageRouter)
    # Set ENABLE_PDF_PAGE_ROUTER=true to activate per-page routing.
    # When false, PdfPageRouter falls back to full-document Docling conversion (stub-compatible).
    enable_pdf_page_router: bool = (
        os.getenv("ENABLE_PDF_PAGE_ROUTER", "true").lower() == "true"
    )
    # v5.1: absolute character count below which a page with an image is classified
    # as image-heavy and routed to SmolVLM.  Replaces the old pdf_text_ratio_threshold
    # (ratio vs page area), which required ~25,000 chars on A4 to clear the bar —
    # far beyond realistic page density.  Tune against real Honeywell manual pages.
    pdf_min_text_chars_for_text_route: int = int(os.getenv("PDF_MIN_TEXT_CHARS_FOR_TEXT_ROUTE", "800"))
    # Max new tokens for SmolVLM inference on image-heavy PDF pages.
    pdf_smolvlm_max_new_tokens: int = int(os.getenv("PDF_SMOLVLM_MAX_NEW_TOKENS", "200"))
    # v5.2: minimum number of distinct pages a text string must appear on to be
    # classified as boilerplate (running header/footer) and demoted from
    # SECTION_HEADER/TITLE to PARAGRAPH by _repair_pdf_headings().
    pdf_boilerplate_min_page_repeats: int = int(os.getenv("PDF_BOILERPLATE_MIN_PAGE_REPEATS", "3"))
    # v5.4: diagnostic flag — when set to 1, _merge_pages() logs heading levels
    # and orphan-check indices so the heading-freeze and tail-ordering bugs can be
    # traced.  Off by default; set PDF_DEBUG_HEADING_DUMP=1 when running test_parse.py
    # to collect the diagnostic output.  Never enable in production.
    pdf_debug_heading_dump: bool = bool(int(os.getenv("PDF_DEBUG_HEADING_DUMP", "0")))




settings = Settings()
