"""Retrieve document context from ChromaDB and generate answers with Ollama."""

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from rag_service import RagService


class GenerationError(Exception):
    """Represent an expected local model service failure."""


class GenerationService:
    """Coordinate retrieval-augmented generation through local Ollama."""

    def __init__(self, rag_service: RagService) -> None:
        """Configure the local Ollama endpoint and retrieval settings."""
        self.rag_service = rag_service
        self.ollama_url = (
            f"http://{os.getenv('OLLAMA_HOST', 'ollama')}"
            f":{os.getenv('OLLAMA_PORT', '11434')}/api/generate"
        )
        self.model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
        self.retrieval_k = int(os.getenv("RETRIEVAL_K", "5"))

    def answer_question(self, question: str) -> dict[str, Any]:
        """Retrieve relevant chunks and return a grounded local-model answer."""
        question = question.strip()
        if not question:
            raise ValueError("Question must not be empty")

        retrieved = self.rag_service.collection.query(
            query_texts=[question],
            n_results=self.retrieval_k,
            include=["documents", "metadatas", "distances"],
        )
        documents = retrieved.get("documents", [[]])[0]
        metadatas = retrieved.get("metadatas", [[]])[0]
        distances = retrieved.get("distances", [[]])[0]
        if not documents:
            raise ValueError("No indexed document chunks were found")

        context = "\n\n---\n\n".join(
            f"Source: {metadata.get('filename')} | Page: {metadata.get('page')}\n{document}"
            for document, metadata in zip(documents, metadatas)
        )
        prompt = (
            "Answer the question using only the provided document context. "
            "If the context does not contain the answer, say that there is "
            "insufficient information. Include concise source references.\n\n"
            f"Context:\n{context}\n\nQuestion: {question}"
        )
        return {
            "question": question,
            "answer": self._generate(prompt),
            "model": self.model,
            "sources": [
                {"metadata": metadata, "distance": distance}
                for metadata, distance in zip(metadatas, distances)
            ],
        }

    def _generate(self, prompt: str) -> str:
        """Call Ollama while keeping the loaded model resident in memory."""
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "keep_alive": -1,
                "options": {"temperature": 0.0},
            }
        ).encode("utf-8")
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

        answer = result.get("response", "").strip()
        if not answer:
            raise GenerationError("Ollama returned an empty response")
        return answer