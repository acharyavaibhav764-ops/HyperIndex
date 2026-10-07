from typing import Any, Union
from docling.chunking import HybridChunker
from docling_core.types.doc import DoclingDocument
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import settings
from core.parsers.config import parser_settings


class Chunker:
    """
    Split extracted page text and Docling documents into overlapping chunks with metadata and unique IDs.

    Attributes:
        chunk_size:    Maximum character length of a legacy text chunk.
        chunk_overlap: Character overlap between consecutive legacy chunks.
        separators:    Separator hierarchy for the legacy text splitter.
        splitter:      RecursiveCharacterTextSplitter for legacy path.

    Methods:
        split()
        _split_legacy()
        _split_docling()
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


    # PUBLIC API

    def split(
        self,
        pages_or_doc: Union[list[tuple[int, str]], DoclingDocument],
        file_id: str,
        filename: str,
    ) -> tuple[list[str], list[dict[str, Any]], list[str]]:
        """Split pages into chunks, returning (chunks, metadatas, chunk_ids)."""

        # Use docling only if docling document detected
        if isinstance(pages_or_doc, DoclingDocument):
            return self._split_docling(pages_or_doc, file_id, filename)
        return self._split_legacy(pages_or_doc, file_id, filename)


    # PRIVATE HELPERS

    def _split_legacy(
        self,
        pages: list[tuple[int, str]],
        file_id: str,
        filename: str,
    ) -> tuple[list[str], list[dict[str, Any]], list[str]]:
        """Legacy recursive character text splitting path."""

        chunks: list[str] = []
        metadatas: list[dict[str, Any]] = []

        for page_number, page_text in pages:
            for chunk in self.splitter.split_text(page_text):
                if len(chunk) < 5:  # Skip micro chunks
                    continue

                # Metadata
                metadatas.append(
                    {
                        "document_id": file_id,
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

    def _split_docling(
        self,
        doc: DoclingDocument,
        file_id: str,
        filename: str,
    ) -> tuple[list[str], list[dict[str, Any]], list[str]]:
        """Token-aware HybridChunker path for DoclingDocument inputs."""
        
        from docling_core.types.doc import DocItemLabel

        chunks: list[str] = []
        metadatas: list[dict[str, Any]] = []
        chunk_ids: list[str] = []

        # Initialize hybrid chunker and create list of raw chunks made in single pass
        chunker = HybridChunker(tokenizer=parser_settings.chunker_tokenizer)
        raw_chunks = list(chunker.chunk(doc))

        # Create a list of headings already covered by the chunker
        covered_headings: set[str] = set()
        for chunk in raw_chunks:
            try:
                for h in chunk.meta.headings:
                    covered_headings.add(h)
            except (AttributeError, TypeError):
                pass

        for chunk in raw_chunks:

            # Create a meaningful structure from nearby chunks
            # Ex: A heading is placed before the body chunk so both are close by
            text = chunker.contextualize(chunk).strip()
            if len(text) < 5:  # Skip micro chunks
                continue

            # Append relevant metadata

            # Attempt to extract page number
            pages = sorted(
                list(
                    set(
                        item.prov[0].page_no
                        for item in getattr(chunk.meta, "doc_items", [])
                        if getattr(item, "prov", None)
                    )
                )
            )
            page: int | None = pages[0] if pages else None # Handle data split across pages by assigning starting page to chunk

            # Identify whether its a picture
            is_picture_chunk = (
                "[Figure description]" in text
                or any(
                    getattr(item, "label", None) == DocItemLabel.PICTURE
                    for item in getattr(chunk.meta, "doc_items", [])
                )
            )

            meta: dict[str, Any] = {
                "document_id": file_id,
                "file_id": file_id,
                "filename": filename,
                "chunk_index": len(metadatas),
            }
            if page is not None:
                meta["page"] = page
            if pages:
                meta["page_numbers"] = ",".join(map(str, pages))

            if is_picture_chunk:
                meta["source"] = "image_description"
            metadatas.append(meta)

            chunks.append(text)

        # Second pass over the raw chunks from chunker to handle heading only texts
        for item in doc.texts:

            # If the title/section header label present, first chunker pass has accounted
            if item.label not in (DocItemLabel.TITLE, DocItemLabel.SECTION_HEADER):
                continue

            # Extract text from header
            heading_text = (item.text or "").strip()
            if heading_text and heading_text not in covered_headings:

                # Append relevant metadata

                # Page number
                page: int | None = None
                try:
                    if item.prov:
                        page = item.prov[0].page_no
                except (AttributeError, IndexError, TypeError):
                    pass

                meta = {
                    "document_id": file_id,
                    "file_id": file_id,
                    "filename": filename,
                    "chunk_index": len(metadatas),
                }
                if page is not None:
                    meta["page"] = page
                    meta["page_numbers"] = str(page)
                
                metadatas.append(meta)

                chunks.append(heading_text)

        if not chunks:
            raise ValueError(f"File {filename} does not contain extractable text")

        chunk_ids = [f"{file_id}_c{index}" for index in range(len(chunks))]
        return chunks, metadatas, chunk_ids
