from typing import Any, Union

from docling.chunking import HybridChunker
from docling_core.transforms.chunker.hierarchical_chunker import (
    ChunkingDocSerializer,
    ChunkingSerializerProvider,
)
from docling_core.transforms.serializer.base import BaseTableSerializer
from docling_core.transforms.serializer.markdown import MarkdownTableSerializer
from docling_core.types.doc import DocItemLabel, DoclingDocument
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import settings
from core import pipeline_config
from core.chunk_cleanup import (
    extract_doc_meta,
    is_micro_label,
    postprocess_chunks,
    section_id,
)

# Module alias
pipeline_settings = pipeline_config.pipeline_settings


# =========================================================================
# Metadata Helpers & Chroma Scalar Normalization
# =========================================================================

def _flatten_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """Convert list/None metadata to Chroma-safe scalars (str/int/float/bool)."""
    out: dict[str, Any] = {}
    for k, v in meta.items():
        if k == "page" and v is None:
            continue  # omit — Chroma rejects None
        elif k == "page_numbers" and isinstance(v, (list, tuple)):
            out[k] = ",".join(str(p) for p in v)
        elif k == "heading_path" and isinstance(v, (list, tuple)):
            out[k] = " > ".join(str(h) for h in v if str(h).strip())
        else:
            out[k] = v
    return out


def _doc_meta(doc: DoclingDocument) -> dict[str, str]:
    """Extract doc_number / doc_version / doc_date from the first three pages of the document."""
    empty = {"doc_number": "", "doc_version": "", "doc_date": ""}
    try:
        pages: dict[int, list[str]] = {}
        for it in doc.texts:
            prov = getattr(it, "prov", None)
            if prov:
                pages.setdefault(prov[0].page_no, []).append(it.text or "")
        return extract_doc_meta(["\n".join(pages[p]) for p in sorted(pages)[:3]])
    except Exception:
        return empty


class _MarkdownTableChunkSerializer(ChunkingDocSerializer):
    """
    Serialize tables as markdown (header + rows) instead of 'row, col = value'.
    The default triplet form keys every cell on column 1, which invents false pairs for
    side-by-side or multi-block tables and cannot be split on a row boundary. A markdown
    table keeps each row intact and lets HybridChunker repeat the header row in every
    chunk of a long table (repeat_table_header=True).
    """

    table_serializer: BaseTableSerializer = MarkdownTableSerializer()


class _MarkdownTableSerializerProvider(ChunkingSerializerProvider):
    def get_serializer(self, doc: DoclingDocument) -> ChunkingDocSerializer:
        return _MarkdownTableChunkSerializer(doc=doc)


class Chunker:
    """
    Split extracted page text into overlapping chunks with metadata and unique IDs.

    The ``split`` method is backward-compatible: it accepts either the
    legacy ``list[tuple[int, str]]`` page format or a
    :class:`~docling_core.types.doc.DoclingDocument` produced by the parsing
    architecture. Both paths return the same ``(chunks, metadatas, chunk_ids)``
    triple so callers need no changes.

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

        self.chunk_size = chunk_size or getattr(settings, "chunk_size", pipeline_settings.chunk_size)
        self.chunk_overlap = chunk_overlap or getattr(settings, "chunk_overlap", pipeline_settings.chunk_overlap)
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
        """Split pages into chunks, returning (chunks, metadatas, chunk_ids)."""

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
        """Legacy recursive character text splitting path."""

        chunks: list[str] = []
        metadatas: list[dict[str, Any]] = []

        for page_number, page_text in pages:
            for chunk in self.splitter.split_text(page_text):
                if len(chunk) < 5:  # Skip micro chunks
                    continue

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

        tokenizer = getattr(settings, "chunker_tokenizer", pipeline_settings.chunker_tokenizer)
        chunker = HybridChunker(
            tokenizer=tokenizer,
            serializer_provider=_MarkdownTableSerializerProvider(),
            repeat_table_header=getattr(settings, "pdf_table_repeat_header", True),
        )
        raw_chunks = list(chunker.chunk(doc))
        doc_meta = _doc_meta(doc)

        chunks: list[str] = []
        metadatas: list[dict[str, Any]] = []

        covered_headings: set[str] = set()
        for chunk in raw_chunks:
            try:
                for h in chunk.meta.headings:
                    covered_headings.add(h)
            except (AttributeError, TypeError):
                pass

        for chunk in raw_chunks:
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

            heading_list: list[str] = []
            try:
                heading_list = list(chunk.meta.headings or [])
            except (AttributeError, TypeError):
                pass

            content_type = "text"
            if "[TOC]" in text:
                content_type = "toc"
            elif "[Recovered text]" in text:
                content_type = "recovered_text"
            elif text.startswith("Figure:") or is_picture_chunk:
                content_type = "figure"
            else:
                try:
                    labels = [
                        getattr(item, "label", None)
                        for item in getattr(chunk.meta, "doc_items", [])
                    ]
                    from docling_core.types.doc import DocItemLabel as _DIL

                    if any(l == _DIL.TABLE for l in labels):
                        content_type = "table"
                    elif any(l == _DIL.PICTURE for l in labels):
                        content_type = "figure"
                except Exception:
                    pass

            meta: dict[str, Any] = {
                "document_id": file_id,
                "file_id": file_id,
                "filename": filename,
                "page": page,
                "page_numbers": pages,
                "chunk_index": len(metadatas),
                "heading_path": heading_list,
                "content_type": content_type,
                "section_id": section_id(page, heading_list),
                **doc_meta,
            }
            if is_picture_chunk:
                meta["source"] = "image_description"

            metadatas.append(meta)
            chunks.append(text)

        # Chunk post-processing: strip leaked markup, carry headers, drop junk, merge ToC
        do_postprocess = getattr(settings, "chunk_postprocess", pipeline_settings.chunk_postprocess)
        if do_postprocess:
            chunks, metadatas = postprocess_chunks(
                chunks, metadatas, drop_micro=filename.lower().endswith(".pdf")
            )

        # Gap B: walk doc.texts for orphaned TITLE / SECTION_HEADER items
        for item in doc.texts:
            if item.label not in (DocItemLabel.TITLE, DocItemLabel.SECTION_HEADER):
                continue
            heading_text = (item.text or "").strip()
            if heading_text and heading_text not in covered_headings:
                if do_postprocess and filename.lower().endswith(".pdf") and is_micro_label(heading_text):
                    continue
                page: int | None = None
                try:
                    if item.prov:
                        page = item.prov[0].page_no
                except (AttributeError, IndexError, TypeError):
                    pass

                synthetic_meta = {
                    "document_id": file_id,
                    "file_id": file_id,
                    "filename": filename,
                    "page": page,
                    "page_numbers": [page] if page is not None else [],
                    "chunk_index": len(metadatas),
                    "heading_path": [heading_text],
                    "content_type": "text",
                    "section_id": section_id(page, [heading_text]),
                    **doc_meta,
                }
                # Insert at the end of the heading's own page instead of appending at tail
                insert_at = len(chunks)
                if page is not None:
                    for idx, m in enumerate(metadatas):
                        mp = m.get("page")
                        if mp is not None and mp > page:
                            insert_at = idx
                            break
                metadatas.insert(insert_at, synthetic_meta)
                chunks.insert(insert_at, heading_text)

        for idx, m in enumerate(metadatas):
            m["chunk_index"] = idx

        # Flatten list/None values to Chroma-safe scalars
        metadatas = [_flatten_meta(m) for m in metadatas]

        if not chunks:
            raise ValueError(f"File {filename} does not contain extractable text")

        chunk_ids = [f"{file_id}_c{index}" for index in range(len(chunks))]
        return chunks, metadatas, chunk_ids
