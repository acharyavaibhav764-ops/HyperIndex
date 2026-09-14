from core import (
    Chunker,
    Embeddings,
    Generator,
    Parser,
    Retriever,
    Uploader,
)

uploader = Uploader()
parser = Parser()
chunker = Chunker()
embeddings = Embeddings()
retriever = Retriever(embeddings=embeddings)
generator = Generator()

