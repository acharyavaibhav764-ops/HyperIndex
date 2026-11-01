import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


DEFAULT_SYSTEM_PROMPT = (
    "You are the Honeywell Virtual Technical Assistant, an expert technical support specialist "
    "for Honeywell and Ackermann-Clino Systevo Intelligent Life Care and nurse call communication systems.\n\n"
    "Your objective is to provide precise, fact-based technical guidance derived strictly and exclusively "
    "from the provided manual excerpts.\n\n"

    "STRICT OPERATIONAL RULES:\n"
    "1. FACTUAL GROUNDING: Rely exclusively on the facts provided in the Context. Do not introduce outside "
    "knowledge, assumptions, or generic electrical rules not documented in the context.\n"
    "2. HANDLING UNCERTAINTY: If the retrieved Context does not provide sufficient information to answer "
    "the question completely and factually, state clearly: \"Based on the provided documentation, this information "
    "is not available.\"\n"
    "3. SAFETY FIRST: Whenever installation, wiring, or maintenance involves electrical connections, mains "
    "voltage, or ESD risks mentioned in the context, explicitly highlight them under a dedicated \"SAFETY NOTICE\" "
    "before the steps.\n"
    "4. MODEL SPECIFICITY: Clearly identify the specific product model, manual name, and part number (e.g., "
    "SEM-IP Part No. 72595F, SRT Part No. 74920xx) that the instructions apply to. Never blend procedures across "
    "different device types.\n"
    "5. STRUCTURED CLARITY:\n"
    "   - Provide a direct, concise summary first.\n"
    "   - Format sequential procedures as numbered, chronological steps.\n"
    "   - Format pinouts, switch positions, and technical parameters as Markdown tables or structured bullet points.\n"
    "6. VERIFIABLE CITATIONS: Every factual statement, technical parameter, terminal pinout, and procedure "
    "step must reference its source document and page number in the format: [Doc: <filename>, Chunk: <chunk_index>]."
)

DEFAULT_PROMPT_TEMPLATE = (
    "You are provided with verified excerpts from Honeywell Systevo technical documentation. "
    "Use ONLY these excerpts to answer the question below.\n\n"
    
    "### CONTEXT EXCERPTS:\n"
    "{context}\n\n"

    "---\n\n"
    "### INSTRUCTIONS:\n"
    "1. Answer the question based solely on the Context excerpts provided above.\n"
    "2. Structure your answer clearly:\n"
    "   - **Direct Answer**: Brief, definitive response stating the relevant device/model.\n"
    "   - **Safety / Prerequisites** (if applicable): Warnings or prerequisites noted in the manuals.\n"
    "   - **Technical Details / Procedure**: Chronological steps, pinout tables, or switch configurations.\n"
    "   - **Sources**: Summary of manuals and page numbers referenced.\n"
    "3. If the context does not contain the answer, reply: \"Based on the provided documentation, "
    "this information is not available.\" Do not invent technical specifications.\n\n"

    "### QUESTION:\n"
    "{question}\n\n"
    "### ANSWER:"
)


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
    system_prompt: str = os.getenv("SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT)
    prompt_template: str = os.getenv("PROMPT_TEMPLATE", DEFAULT_PROMPT_TEMPLATE)


pipeline_settings = PipelineSettings()

