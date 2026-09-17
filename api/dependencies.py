from config import settings
from core import (
    Chunker,
    Embeddings,
    Generator,
    Parser,
    Retriever,
    Uploader,
)

# Global shared singletons
uploader = Uploader()
parser = Parser()
chunker = Chunker(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
embeddings = Embeddings()
retriever = Retriever(embeddings=embeddings)
generator = Generator(
    ollama_host=settings.ollama_host,
    ollama_port=settings.ollama_port,
    model=settings.ollama_model,
)

