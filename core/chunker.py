import re
from typing import Any, Union

from docling.chunking import HybridChunker
from docling_core.transforms.chunker.hierarchical_chunker import (
    ChunkingDocSerializer,
    ChunkingSerializerProvider,
)
from docling_core.transforms.serializer.base import BaseTableSerializer
from docling_core.transforms.serializer.markdown import MarkdownTableSerializer
from docling_core.types.doc import DoclingDocument
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import settings
from core.chunk_cleanup import (  # v5.8 / v5.9.1
    extract_doc_meta,
    is_micro_label,
    postprocess_chunks,
    section_id,
)


# =========================================================================
# v5.9 WP0b — metadata helpers
# =========================================================================

# v6: Figure cards written by parsers/pdf_v6/cards.py.
_FIGURE_CARD_RE = re.compile(r"(?m)^Figure: .*? \| (?:Type|Section|Labels):")
_PROCEDURE_RE = re.compile(r"(?m)^Procedure \(\d+ illustrated steps\)")  # v6 phase 3
# v6 phase 5: trailing " | Page: n | BBox: ... | Image: s3://..." that cards.format_tail appends.
_FIG_TAIL_RE = re.compile(r" \| Page: (\d+)(?: \| BBox: ([\d.,-]+))?(?: \| Image: (\S+))?\s*$")


def _split_figure_tail(text: str) -> tuple[str, dict[str, Any]]:
    """Move a card's Page/BBox/Image tail out of the embedded text into metadata."""
    meta: dict[str, Any] = {}
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if not (line.startswith("Figure: ") or line.startswith("Procedure (")):
            continue
        m = _FIG_TAIL_RE.search(line)
        if not m:
            continue
        lines[i] = line[:m.start()]
        meta["figure_page"] = int(m.group(1))
        if m.group(2):
            meta["figure_bbox"] = m.group(2)
        if m.group(3):
            meta["figure_image"] = m.group(3)
        break
    return "\n".join(lines), meta


def _flatten_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """Convert list/None metadata to Chroma-safe scalars (str/int/float/bool)."""
    out: dict[str, Any] = {}
    for k, v in meta.items():
        if k == "page" and v is None:
            continue                         # omit — Chroma rejects None
        elif k == "page_numbers" and isinstance(v, (list, tuple)):
            out[k] = ",".join(str(p) for p in v)
        elif k == "heading_path" and isinstance(v, (list, tuple)):
            out[k] = " > ".join(str(h) for h in v if str(h).strip())
        else:
            out[k] = v
    return out


def _doc_meta(doc: DoclingDocument) -> dict[str, str]:
    """v5.9.1 WP6: doc_number / doc_version / doc_date from the first three pages of the document."""
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
    """v5.7: serialise tables as markdown (header + rows) instead of 'row, col = value'.

    The default triplet form keys every cell on column 1, which invents false pairs for
    side-by-side or multi-block tables and cannot be split on a row boundary.  A markdown
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

        chunker = HybridChunker(
            tokenizer=settings.chunker_tokenizer,
            max_tokens=getattr(settings, "chunker_max_tokens", 1024),  # v6: figure cards can exceed 512
            serializer_provider=_MarkdownTableSerializerProvider(),  # v5.7
            repeat_table_header=True,
        )
        raw_chunks = list(chunker.chunk(doc))
        doc_meta = _doc_meta(doc)  # v5.9.1 WP6

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

            # v5.9: surface heading_path from chunk.meta.headings.
            heading_list: list[str] = []
            try:
                heading_list = list(chunk.meta.headings or [])
            except (AttributeError, TypeError):
                pass

            # v5.9: derive content_type tag.
            content_type = "text"
            if "[TOC]" in text:
                content_type = "toc"
            elif "[Recovered text]" in text:
                content_type = "recovered_text"
            elif _PROCEDURE_RE.search(text):
                content_type = "procedure"
            elif text.startswith("Figure:") or _FIGURE_CARD_RE.search(text) or is_picture_chunk:
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

            fig_meta: dict[str, Any] = {}
            if content_type in ("figure", "procedure"):
                text, fig_meta = _split_figure_tail(text)
            meta: dict[str, Any] = {
                "document_id": file_id,
                "file_id": file_id,
                "filename": filename,
                "page": page,
                "page_numbers": pages,
                "chunk_index": len(metadatas),
                # v5.9 WP0b
                "heading_path": heading_list,
                "content_type": content_type,
                "section_id": section_id(page, heading_list),
                **doc_meta,
            }
            meta.update(fig_meta)
            if is_picture_chunk:
                meta["source"] = "image_description"

            metadatas.append(meta)
            chunks.append(text)

        # v5.8: strip leaked '###' / '**', drop echoed next-heading tails and micro chunks.
        # Runs BEFORE the Gap-B injection below so intentional heading-only chunks survive.
        if settings.chunk_postprocess:
            chunks, metadatas = postprocess_chunks(
                chunks, metadatas, drop_micro=filename.lower().endswith(".pdf")
            )

        # v2 fix (Gap B): heading-only slides produce no DocChunk at all.
        # Walk doc.texts for TITLE/SECTION_HEADER items not covered by any chunk
        # and inject them as synthetic text chunks so they are retrievable.
        for item in doc.texts:
            if item.label not in (DocItemLabel.TITLE, DocItemLabel.SECTION_HEADER):
                continue
            heading_text = (item.text or "").strip()
            if heading_text and heading_text not in covered_headings:
                # v5.8.1: a PDF heading item with no body and no place in any heading path is a
                # running logo/label (e.g. 'Calisthenics Family' on the last page), not a section.
                if settings.chunk_postprocess and filename.lower().endswith(".pdf") \
                        and is_micro_label(heading_text):
                    continue
                # Page provenance for synthetic heading chunks
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
                    # v5.9 WP0b
                    "heading_path": [heading_text],
                    "content_type": "text",
                    "section_id": section_id(page, [heading_text]),
                    **doc_meta,
                }
                # v5.5 Fix B: insert at the end of the heading's own page instead
                # of appending at the tail (the "orphan chunks at end" bug).
                insert_at = len(chunks)
                if page is not None:
                    for idx, m in enumerate(metadatas):
                        mp = m.get("page")
                        if mp is not None and mp > page:
                            insert_at = idx
                            break
                metadatas.insert(insert_at, synthetic_meta)
                chunks.insert(insert_at, heading_text)

        for idx, m in enumerate(metadatas):  # keep chunk_index == list position
            m["chunk_index"] = idx

        # v5.9 WP0b: flatten list/None values to Chroma-safe scalars.
        metadatas = [_flatten_meta(m) for m in metadatas]

        if not chunks:
            raise ValueError(f"File {filename} does not contain extractable text")

        chunk_ids = [f"{file_id}_c{index}" for index in range(len(chunks))]
        return chunks, metadatas, chunk_ids
