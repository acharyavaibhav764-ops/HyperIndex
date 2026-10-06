import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import settings


class GenerationError(Exception):
    """Represent an expected local model service failure."""

    pass


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
    "step must reference its source document and page number in the format: [Doc: <filename>, Page: <page>]."
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


class Generator:
    """
    Coordinate local LLM generation and prompt construction with Ollama.
    
    Attributes:
        ollama_url
        model
        system_prompt
        prompt_template

    Methods:
        build_prompt()
        generate()
    """

    def __init__(
        self,
        ollama_host: str | None = None,
        ollama_port: str | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        prompt_template: str | None = None,
    ) -> None:
        host = ollama_host or settings.ollama_host
        port = ollama_port or settings.ollama_port
        self.ollama_url = f"http://{host}:{port}/api/generate"
        self.model = model or settings.ollama_model
        self.system_prompt = system_prompt or settings.system_prompt or DEFAULT_SYSTEM_PROMPT
        self.prompt_template = prompt_template or settings.prompt_template or DEFAULT_PROMPT_TEMPLATE

    def build_prompt(
        self,
        question: str,
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> str:
        """Format retrieved context and question into a grounded prompt."""

        context_blocks = []
        for i, (document, metadata) in enumerate(zip(documents, metadatas), start=1):
            filename = metadata.get("filename") or metadata.get("source") or "Unknown Document"
            page = metadata.get("page", "Unknown")
            context_blocks.append(
                f"[Document {i}: {filename} | Page {page}]\n"
                f"--------------------------------------------------------------------------------\n"
                f"{document}\n"
                f"--------------------------------------------------------------------------------"
            )

        context = "\n\n".join(context_blocks)

        return (
            self.prompt_template
            .replace("{context}", context)
            .replace("{question}", question)
        )

    def generate(self, prompt: str) -> str:
        """Call Ollama while keeping the loaded model resident in memory."""

        # Model config to be sent with request
        payload = json.dumps(
            {
                "model": self.model,
                "system": self.system_prompt,
                "prompt": prompt,
                "stream": False,
                "keep_alive": -1, # Keep model in memory infinitely
                "options": {"temperature": 0.0},
            }
        ).encode("utf-8")

        # Assemble request and send to ollama endpoint
        request = Request(
            self.ollama_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=180) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise GenerationError(
                "Unable to reach Ollama. Start the service and pull the configured model."
            ) from error

        # Return response
        answer = result.get("response", "").strip()
        if not answer:
            raise GenerationError("Ollama returned an empty response")
        return answer
