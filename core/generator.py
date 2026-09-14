import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import settings


class GenerationError(Exception):
    """Represent an expected local model service failure."""

    pass


class Generator:
    """
    Coordinate local LLM generation and prompt construction with Ollama.
    
    Attributes:
        ollama_url
        model

    Methods:
        build_prompt()
        generate()
    """

    def __init__(
        self,
        ollama_host: str | None = None,
        ollama_port: str | None = None,
        model: str | None = None,
    ) -> None:
        host = ollama_host or settings.ollama_host
        port = ollama_port or settings.ollama_port
        self.ollama_url = f"http://{host}:{port}/api/generate"
        self.model = model or settings.ollama_model

    def build_prompt(
        self,
        question: str,
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> str:
        """Format retrieved context and question into a grounded prompt."""

        context = "\n\n---\n\n".join(
            f"Source: {metadata.get('filename')} | Page: {metadata.get('page')}\n{document}"
            for document, metadata in zip(documents, metadatas)
        )
        return (
            f"Context:\n{context}\n\nQuestion: {question}" # SYSTEM PROMPT
        )

    def generate(self, prompt: str) -> str:
        """Call Ollama while keeping the loaded model resident in memory."""

        # Model config to be sent with request
        payload = json.dumps(
            {
                "model": self.model,
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
