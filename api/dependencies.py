from config import settings
from core import (
    Chunker,
    Embeddings,
    Generator,
    Parser,
    Retriever,
    Uploader,
)

try:
    from parsers.router import ParserRouter
except ImportError:
    class ParserRouter:
        """Fallback for ParserRouter until v1-v3 are implemented."""
        def parse(self, file_bytes, filename, **kwargs):
            raise NotImplementedError("ParserRouter not yet fully implemented")

# Global shared singletons
uploader = Uploader()
parser = Parser()
parser_router = ParserRouter()
chunker = Chunker(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
embeddings = Embeddings()
retriever = Retriever(embeddings=embeddings)
generator = Generator(
    ollama_host=settings.ollama_host,
    ollama_port=settings.ollama_port,
    model=settings.ollama_model,
)

