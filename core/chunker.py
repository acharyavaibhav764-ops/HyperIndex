import logging
from typing import Any, Union
from docling.chunking import HybridChunker
from docling_core.types.doc import DoclingDocument
from langchain_text_splitters import RecursiveCharacterTextSplitter

from core import pipeline_config

# Module alias
pipeline_settings = pipeline_config.pipeline_settings

logger = logging.getLogger(__name__)


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

        self.chunk_size = chunk_size or pipeline_config.pipeline_settings.chunk_size
        self.chunk_overlap = chunk_overlap or pipeline_config.pipeline_settings.chunk_overlap
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
        """Token-aware HybridChunker path for DoclingDocument inputs.

        If HybridChunker raises a validation error (e.g. inconsistent table
        hierarchy in documents with complex merged-cell tables), the method
        falls back gracefully to plain-text extraction via:
          1. ``doc.export_to_text()``  — Docling's internal text serializer
          2. Iterating ``doc.texts`` items and table cells directly
        The extracted text is then split with the legacy RecursiveCharacterTextSplitter.
        """

        from docling_core.types.doc import DocItemLabel

        chunks: list[str] = []
        metadatas: list[dict[str, Any]] = []
        chunk_ids: list[str] = []

        # ------------------------------------------------------------------ #
        # PRIMARY PATH — HybridChunker                                        #
        # ------------------------------------------------------------------ #
        try:
            # Initialize hybrid chunker and create list of raw chunks made in single pass
            chunker = HybridChunker(tokenizer=pipeline_config.pipeline_settings.chunker_tokenizer)
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
                        "filename": filename,
                        "chunk_index": len(metadatas),
                    }
                    if page is not None:
                        meta["page"] = page
                        meta["page_numbers"] = str(page)

                    metadatas.append(meta)

                    chunks.append(heading_text)

            if chunks:
                chunk_ids = [f"{file_id}_c{index}" for index in range(len(chunks))]
                return chunks, metadatas, chunk_ids

            # HybridChunker produced no usable chunks — fall through to fallback
            logger.warning(
                "HybridChunker returned 0 chunks for '%s'; falling back to text extraction.",
                filename,
            )

        except Exception as exc:
            # Docling raises pydantic ValidationError for documents with
            # inconsistent table hierarchies (e.g. complex merged-cell tables).
            # export_to_markdown() suffers the same bug, so we skip it too.
            logger.warning(
                "HybridChunker failed for '%s' (%s: %s); falling back to plain-text extraction.",
                filename,
                type(exc).__name__,
                exc,
            )

        # ------------------------------------------------------------------ #
        # FALLBACK PATH — plain-text extraction + legacy splitter             #
        # ------------------------------------------------------------------ #
        fallback_parts: list[str] = []

        # Attempt 1: Docling's own text serialiser (avoids markdown validator)
        try:
            exported = doc.export_to_text()
            if exported and exported.strip():
                fallback_parts.append(exported.strip())
                logger.info("Fallback: export_to_text() succeeded for '%s'.", filename)
        except Exception as exc:
            logger.warning(
                "Fallback export_to_text() also failed for '%s' (%s); iterating doc.texts.",
                filename,
                exc,
            )

        # Attempt 2: Iterate doc.texts items directly
        if not fallback_parts:
            for item in getattr(doc, "texts", []):
                t = (getattr(item, "text", "") or "").strip()
                if t:
                    fallback_parts.append(t)

            # Also harvest readable text from table cells
            for table in getattr(doc, "tables", []):
                try:
                    for cell in table.data.table_cells:
                        t = (getattr(cell, "text", "") or "").strip()
                        if t:
                            fallback_parts.append(t)
                except Exception:
                    pass  # Skip unreadable tables silently

        full_text = "\n".join(fallback_parts)
        if not full_text.strip():
            raise ValueError(f"File {filename} does not contain extractable text")

        logger.info(
            "Fallback: extracted %d chars from '%s'; splitting with legacy splitter.",
            len(full_text),
            filename,
        )

        # Delegate to legacy splitter; treat entire document as page 1
        return self._split_legacy([(1, full_text)], file_id, filename)
