"""Extract, chunk, embed, and persist uploaded documents in ChromaDB."""

import os
from typing import Any

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
from langchain_text_splitters import RecursiveCharacterTextSplitter

from document import DocumentService
from parser import Parser


class RagService:
    """Coordinate document extraction, embedding, and vector persistence."""

    def __init__(self, document_service: DocumentService) -> None:
        """Configure the persistent Chroma collection and chunking policy."""
        self.document_service = document_service
        self.parser = Parser()
        self.chunker = RecursiveCharacterTextSplitter(
            chunk_size=int(os.getenv("CHUNK_SIZE", "1000")),
            chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "200")),
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        chroma_host = os.getenv("CHROMA_HOST")
        if chroma_host:
            self.chroma_client = chromadb.HttpClient(
                host=chroma_host,
                port=int(os.getenv("CHROMA_PORT", "8000")),
            )
        else:
            self.chroma_client = chromadb.PersistentClient(
                path=os.getenv("CHROMA_PATH", "./chroma_data")
            )
        self.embedding_function = DefaultEmbeddingFunction()
        self.collection = self.chroma_client.get_or_create_collection(
            name=os.getenv("CHROMA_COLLECTION", "my_documents"),
            metadata={"hnsw:space": "cosine"},
            embedding_function=self.embedding_function,
        )

    def process_document(self, document_id: str) -> dict[str, Any]:
        """Process one uploaded MinIO object and return its persisted vectors."""
        content, filename = self.document_service.download_document(document_id)
        pages = self.parser.parse(content, filename)
        chunks: list[str] = []
        metadatas: list[dict[str, Any]] = []
        for page_number, page_text in pages:
            for chunk in self.chunker.split_text(page_text):
                if len(chunk) < 5:
                    continue
                chunks.append(chunk)
                metadatas.append(
                    {
                        "document_id": document_id,
                        "filename": filename,
                        "page": page_number,
                        "chunk_index": len(chunks) - 1,
                    }
                )
        if not chunks:
            raise ValueError(f"Document {filename} does not contain extractable text")

        chunk_ids = [f"{document_id}_c{index}" for index in range(len(chunks))]
        embeddings = self.embedding_function(chunks)
        self.collection.upsert(
            ids=chunk_ids,
            documents=chunks,
            metadatas=metadatas,
            embeddings=embeddings,
        )
        response_chunks = [
            {
                "id": chunk_ids[index],
                "text": chunks[index],
                "metadata": metadatas[index],
            }
            for index in range(0, len(chunks), 10)
        ]
        return {
            "collection": self.collection.name,
            "chroma_location": (
                f"http://{os.getenv('CHROMA_HOST')}:{os.getenv('CHROMA_PORT', '8000')}"
                if os.getenv("CHROMA_HOST")
                else os.getenv("CHROMA_PATH", "./chroma_data")
            ),
            "document_id": document_id,
            "filename": filename,
            "chunk_count": len(chunks),
            "returned_chunk_count": len(response_chunks),
            "chunks": response_chunks,
        }

