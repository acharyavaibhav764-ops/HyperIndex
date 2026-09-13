from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import settings


class Chunker:
    """
    Split extracted page text into overlapping chunks with metadata and unique IDs.
    
    Attributes:
        chunk_size
        chunk_overlap
        separators
        splitter

    Methods:
        split()
    """

    def __init__(
        self,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        separators: list[str] | None = None,
    ) -> None:
        """Configure chunker class"""
        
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap
        self.separators = separators or ["\n\n", "\n", ". ", " ", ""]
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=self.separators,
        )

    def split(
        self, pages: list[tuple[int, str]], file_id: str, filename: str
    ) -> tuple[list[str], list[dict[str, Any]], list[str]]:
        """Split pages into chunks, returning (chunks, metadatas, chunk_ids)."""

        chunks: list[str] = []
        metadatas: list[dict[str, Any]] = []

        for page_number, page_text in pages:
            for chunk in self.splitter.split_text(page_text):
                if len(chunk) < 5: # Skip micro chunks
                    continue

                # Metadata
                metadatas.append(
                    {
                        "file_id": file_id,
                        "filename": filename,
                        "page": page_number,
                        "chunk_index": len(metadatas),
                    }
                )
                chunks.append(chunk)

        if not chunks:
            raise ValueError(f"File {filename} does not contain extractable text")

        chunk_ids = [f"{file_id}_c{index}" for index in range(len(chunks))]
        return chunks, metadatas, chunk_ids
