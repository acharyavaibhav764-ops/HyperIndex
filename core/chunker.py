from typing import Any, Union

from docling.chunking import HybridChunker
from docling_core.types.doc import DoclingDocument
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import settings


class Chunker:
    """
    Split extracted page text into overlapping chunks with metadata and unique IDs.

    In v1 the ``split`` method is backward-compatible: it accepts either the
    legacy ``list[tuple[int, str]]`` page format **or** a
    :class:`~docling_core.types.doc.DoclingDocument` produced by the new
    parsing architecture.  Both paths return the same
    ``(chunks, metadatas, chunk_ids)`` triple so callers need no changes.

    Attributes:
        chunk_size:    Maximum character length of a legacy text chunk.
        chunk_overlap: Character overlap between consecutive legacy chunks.
        separators:    Separator hierarchy for the legacy text splitter.
        splitter:      :class:`RecursiveCharacterTextSplitter` for legacy path.
    
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def split(
        self,
        pages_or_doc: Union[list[tuple[int, str]], DoclingDocument],
        file_id: str,
        filename: str,
    ) -> tuple[list[str], list[dict[str, Any]], list[str]]:
        """Split pages into chunks, returning (chunks, metadatas, chunk_ids).

        Dispatches to the Docling HybridChunker when *pages_or_doc* is a
        :class:`DoclingDocument`, otherwise falls back to the legacy recursive
        character text splitter.

        Args:
            pages_or_doc: Either a ``list[tuple[int, str]]`` of
                          ``(page_number, page_text)`` pairs (legacy) or a
                          :class:`DoclingDocument` (new parsing architecture).
            file_id:      Unique identifier for the source file.
            filename:     Original filename for metadata.

        Returns:
            tuple: A 3-tuple of ``(chunks, metadatas, chunk_ids)`` where:
                   - *chunks*    – ``list[str]`` of chunk texts.
                   - *metadatas* – ``list[dict]`` with ``document_id``,
                                   ``file_id``, ``filename``, ``page``, and
                                   ``chunk_index``.
                   - *chunk_ids* – ``list[str]`` of ``"{file_id}_c{index}"`` IDs.

        Raises:
            ValueError: If the input contains no extractable text.
        """
        if isinstance(pages_or_doc, DoclingDocument):
            return self._split_docling(pages_or_doc, file_id, filename)
        return self._split_legacy(pages_or_doc, file_id, filename)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _split_legacy(
        self,
        pages: list[tuple[int, str]],
        file_id: str,
        filename: str,
    ) -> tuple[list[str], list[dict[str, Any]], list[str]]:
        """Legacy recursive character text splitting path.

        Args:
            pages:    List of ``(page_number, page_text)`` pairs.
            file_id:  Unique identifier for the source file.
            filename: Original filename for metadata.

        Returns:
            tuple: ``(chunks, metadatas, chunk_ids)`` — same shape as
                   :meth:`split`.

        Raises:
            ValueError: If no extractable text is found.
        """
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
        """Token-aware HybridChunker path for DoclingDocument inputs.

        Uses Docling's :class:`HybridChunker` with the tokenizer from
        ``settings.chunker_tokenizer``.  Each chunk inherits page provenance
        from the Docling document model when available.

        **v2 fix (Gap A)**: Uses ``chunker.contextualize(chunk)`` instead of
        the deprecated ``chunk.text``.  ``chunk.text`` contains only body text;
        ``contextualize()`` prepends the heading path from
        ``chunk.meta.headings``, ensuring section/slide titles are embedded.

        **v2 fix (Gap B)**: After collecting HybridChunker's output, any
        ``TITLE`` or ``SECTION_HEADER`` text item in the document that did not
        appear in any chunk's heading context (i.e., heading-only slides with no
        body text) is added as a synthetic chunk so it is not silently dropped.

        Args:
            doc:      A :class:`DoclingDocument` produced by a
                      :class:`~parsers.base.BaseParser` implementation.
            file_id:  Unique identifier for the source file.
            filename: Original filename for metadata.

        Returns:
            tuple: ``(chunks, metadatas, chunk_ids)`` — same shape as
                   :meth:`split`.

        Raises:
            ValueError: If the document produces no chunks.
        """
        from docling_core.types.doc import DocItemLabel

        chunker = HybridChunker(tokenizer=settings.chunker_tokenizer)
        raw_chunks = list(chunker.chunk(doc))

        chunks: list[str] = []
        metadatas: list[dict[str, Any]] = []

        # v2 fix (Gap B): collect all headings that appear in at least one
        # HybridChunker-produced chunk, so we can detect heading-only slides.
        covered_headings: set[str] = set()
        for chunk in raw_chunks:
            try:
                for h in chunk.meta.headings:
                    covered_headings.add(h)
            except (AttributeError, TypeError):
                pass

        for chunk in raw_chunks:
            # v2 fix (Gap A): contextualize() prepends chunk.meta.headings to
            # body text.  serialize() is its deprecated alias — use contextualize().
            text = chunker.contextualize(chunk).strip()
            if len(text) < 5:  # Skip micro chunks
                continue

            # Extract all unique page numbers from Docling provenance
            pages = sorted(
                list(
                    set(
                        item.prov[0].page_no
                        for item in getattr(chunk.meta, "doc_items", [])
                        if getattr(item, "prov", None)
                    )
                )
            )
            page: int | None = pages[0] if pages else None

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
                "page": page,
                "page_numbers": pages,
                "chunk_index": len(metadatas),
            }
            if is_picture_chunk:
                meta["source"] = "image_description"

            metadatas.append(meta)
            chunks.append(text)

        # v2 fix (Gap B): heading-only slides produce no DocChunk at all.
        # Walk doc.texts for TITLE/SECTION_HEADER items not covered by any chunk
        # and inject them as synthetic text chunks so they are retrievable.
        for item in doc.texts:
            if item.label not in (DocItemLabel.TITLE, DocItemLabel.SECTION_HEADER):
                continue
            heading_text = (item.text or "").strip()
            if heading_text and heading_text not in covered_headings:
                # Page provenance for synthetic heading chunks
                page: int | None = None
                try:
                    if item.prov:
                        page = item.prov[0].page_no
                except (AttributeError, IndexError, TypeError):
                    pass
                metadatas.append(
                    {
                        "document_id": file_id,
                        "file_id": file_id,
                        "filename": filename,
                        "page": page,
                        "page_numbers": [page] if page is not None else [],
                        "chunk_index": len(metadatas),
                    }
                )
                chunks.append(heading_text)

        if not chunks:
            raise ValueError(f"File {filename} does not contain extractable text")

        chunk_ids = [f"{file_id}_c{index}" for index in range(len(chunks))]
        return chunks, metadatas, chunk_ids
