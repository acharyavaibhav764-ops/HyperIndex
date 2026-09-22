# v2.1 Bug Fixes Integration Plan (`v2fix.md`)

This document outlines the **code-only changes** from `parser_v1` (commit `b64c11c`) that need to be ported into `parser_docs`. All comments and docstrings written in `parser_docs` are preserved, and only the functional logic fixes are detailed below.

---

## 1. Summary of Issues Fixed in `parser_v1`

| Issue | Root Cause | Fix Summary |
|---|---|---|
| **Bug A: PPTX Slide Titles Orphaned from Body** | Docling's PPTX backend (`MsPowerpointDocumentBackend`) often misclassifies text box slide titles as `DocItemLabel.PARAGRAPH` instead of `SECTION_HEADER`. Under high token loads, `HybridChunker` splits right after the paragraph title, separating it from its body bullets. | Added `_promote_pptx_pseudo_headings()` in `core/parsers/docling_parser.py` to identify slide start paragraphs (<100 chars, no trailing period) and promote them to `DocItemLabel.SECTION_HEADER` (`SectionHeaderItem`). |
| **Bug B: Multi-page Metadata Silently Drops Trailing Pages** | When `HybridChunker` merges small consecutive slides (e.g., slides 13 and 14) into one chunk, the chunker only recorded the page number of the first doc item (`page: 13`), hiding subsequent slides from metadata. | Updated `core/chunker.py` to extract all unique page numbers into a `page_numbers` list (`[13, 14]`), keeping `page: pages[0]` for backward compatibility. |
| **CLI & Testing Utilities** | `test_parse.py` didn't indicate PPTX/DOCX support in usage, had small preview truncation (300 chars), and lacked regression tests for Bug A and Bug B. | Updated preview size to 800 chars and added two test classes to `test_serialize_fix.py`. |

---

## 2. Exact Changes by File in `parser_docs`

### File 1: `core/parsers/docling_parser.py`

#### Change 1.1: Import `SectionHeaderItem`
**Location**: Line 9
```python
# Before
from docling_core.types.doc import DocItemLabel, DoclingDocument

# After
from docling_core.types.doc import DocItemLabel, DoclingDocument, SectionHeaderItem
```

#### Change 1.2: Add `_promote_pptx_pseudo_headings()` helper function
**Location**: Right after `_inject_picture_descriptions()` (around Line 113), before `class DoclingParser`
```python
def _promote_pptx_pseudo_headings(doc: DoclingDocument) -> None:
    """Identify and promote plain text pseudo-headings on PPTX slides.
    
    Docling's MsPowerpointDocumentBackend often misclassifies text box titles as
    PARAGRAPH. If a PARAGRAPH is short (<100 chars), does not end in a period,
    and is the first textual item on its page, we safely replace the TextItem
    node with a SectionHeaderItem so HybridChunker respects it as a hard boundary.
    """
    page_first_items = {}
    for item in doc.texts:
        if getattr(item, "prov", None):
            p_no = item.prov[0].page_no
            if p_no not in page_first_items:
                page_first_items[p_no] = item
                
    for i, item in enumerate(doc.texts):
        p_no = item.prov[0].page_no if getattr(item, "prov", None) else None
        if p_no and page_first_items.get(p_no) is item:
            if item.label == DocItemLabel.PARAGRAPH:
                text = getattr(item, "text", "").strip()
                if text and len(text) < 100 and not text.endswith("."):
                    dump = item.model_dump()
                    dump["label"] = DocItemLabel.SECTION_HEADER
                    new_item = SectionHeaderItem(**dump)
                    doc.texts[i] = new_item
```

#### Change 1.3: Call `_promote_pptx_pseudo_headings()` in `DoclingParser.parse()`
**Location**: Inside `parse()` (around Line 156), before returning `doc`
```python
    def parse(self, file_bytes: bytes, filename: str, **kwargs) -> DoclingDocument:
        """Convert raw Office file bytes to a DoclingDocument."""

        stream = DocumentStream(name=filename, stream=io.BytesIO(file_bytes))

        # Convert with VLM only if picture description enabled
        if settings.enable_picture_description:
            doc = self._convert_with_vlm(stream, filename)
        else:
            result = self._converter.convert(stream)
            doc = result.document

        # Promote plain text pseudo-headings for PPTX slides
        if filename.lower().endswith(".pptx"):
            _promote_pptx_pseudo_headings(doc)

        return doc
```

---

### File 2: `core/chunker.py`

#### Change 2.1: Multi-page provenance extraction & metadata update in `_split_docling()`
**Location**: Lines 132–157

```python
# Before
            # Attempt to extract page number
            page: int | None = None
            try:
                prov = chunk.meta.doc_items[0].prov
                if prov:
                    page = prov[0].page_no
            except (AttributeError, IndexError, TypeError):
                pass

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
                "page": page,
                "chunk_index": len(metadatas),
            }
```

```python
# After
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
                "page": page,
                "page_numbers": pages,
                "chunk_index": len(metadatas),
            }
```

#### Change 2.2: Add `page_numbers` in heading-only second pass in `_split_docling()`
**Location**: Lines 185–193

```python
# Before
                metadatas.append(
                    {
                        "document_id": file_id,
                        "file_id": file_id,
                        "filename": filename,
                        "page": page,
                        "chunk_index": len(metadatas),
                    }
                )
```

```python
# After
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
```

---

### File 3: `tests/parsers/test_serialize_fix.py`

#### Change 3.1: Add Regression Tests for Bug A & Bug B
**Location**: Append to the end of `tests/parsers/test_serialize_fix.py` (after Line 169)

```python
# ---------------------------------------------------------------------------
# Bug A & B Fixes — Pseudo-heading Boundary & Multi-page metadata
# ---------------------------------------------------------------------------

class TestBugAFix_PseudoHeadingBoundary:
    """Pseudo-headings in PPTX must act as hard boundaries for HybridChunker."""
    
    def test_pseudo_heading_hard_boundary(self):
        """High token load before a slide title should not cause the title to be orphaned."""
        prs = Presentation()
        layouts = prs.slide_layouts
        
        # Slide 1: High token load
        slide1 = prs.slides.add_slide(layouts[0])
        slide1.shapes.title.text = "Slide 1 Title"
        # Large text block pushing chunker close to its limit
        large_text = "word " * 300
        slide1.placeholders[1].text = large_text
        
        # Slide 2: Pseudo-heading (no trailing period, short)
        slide2 = prs.slides.add_slide(layouts[0])
        slide2.shapes.title.text = "Proposed Outcomes"
        slide2.placeholders[1].text = "Bullet 1\nBullet 2\nBullet 3"
        
        buf = io.BytesIO()
        prs.save(buf)
        file_bytes = buf.getvalue()
        
        from core.parsers.docling_parser import DoclingParser
        from core.chunker import Chunker
        
        doc = DoclingParser().parse(file_bytes, "high_token.pptx")
        chunks, _, _ = Chunker().split(doc, "file-buga", "high_token.pptx")
        
        # Find the chunk containing the bullets from slide 2
        slide2_chunks = [c for c in chunks if "Bullet 1" in c]
        assert slide2_chunks, "Expected to find slide 2 body in chunks"
        
        # Pseudo-heading should be prepended to the chunk via contextualize()
        assert "Proposed Outcomes" in slide2_chunks[0], (
            "Slide title 'Proposed Outcomes' was orphaned from its body bullets!"
        )


class TestBugBFix_MultiPageMetadata:
    """Chunk metadata must accurately reflect multi-page spans."""
    
    def test_multi_page_metadata(self):
        """Consecutive small slides merged into a single chunk must expose all page numbers."""
        prs = Presentation()
        layouts = prs.slide_layouts
        
        # Two very short slides that fit well within token limits
        s1 = prs.slides.add_slide(layouts[0])
        s1.shapes.title.text = "Small Slide A"
        
        s2 = prs.slides.add_slide(layouts[0])
        s2.shapes.title.text = "Small Slide B"
        s2.placeholders[1].text = "Some body text here"
        
        buf = io.BytesIO()
        prs.save(buf)
        file_bytes = buf.getvalue()
        
        from core.parsers.docling_parser import DoclingParser
        from core.chunker import Chunker
        
        doc = DoclingParser().parse(file_bytes, "merged.pptx")
        chunks, metadatas, _ = Chunker().split(doc, "file-bugb", "merged.pptx")
        
        for meta in metadatas:
            assert "page" in meta
            assert "page_numbers" in meta
            assert isinstance(meta["page_numbers"], list)
            assert meta["page"] == meta["page_numbers"][0] if meta["page_numbers"] else None
```

---

### File 4: `tests/unit/test_parse.py`

#### Change 4.1: Update CLI usage and preview formatting
**Location**: Lines 21–23 and Lines 55–63

```python
# Before (Usage)
    if len(sys.argv) < 2:
        print("Usage: python test_parse.py <path-to-file.txt or .md>")
        sys.exit(1)

# After (Usage)
    if len(sys.argv) < 2:
        print("Usage: python test_parse.py <path-to-file>")
        print("Supported: .txt  .md  .docx  .pptx")
        sys.exit(1)
```

```python
# Before (Chunk output formatting)
    print(f"\n[Result] Successfully produced {len(chunks)} chunk(s):\n")
    for i, (chunk, meta, cid) in enumerate(zip(chunks, metadatas, chunk_ids)):
        print(f"{'='*70}")
        print(f"Chunk #{i + 1} | ID: {cid} | Length: {len(chunk)} chars")
        print(f"Metadata: {meta}")
        print(f"{'-'*70}")
        preview = chunk if len(chunk) <= 300 else chunk[:300] + "... [truncated]"
        print(preview)
        print(f"{'='*70}\n")

# After (Chunk output formatting)
    total = len(chunks)
    print(f"\n[Result] Successfully produced {total} chunk(s):\n")
    for i, (chunk, meta, cid) in enumerate(zip(chunks, metadatas, chunk_ids)):
        print(f"{'='*70}")
        print(f"Chunk #{i + 1}/{total} | ID: {cid} | Length: {len(chunk)} chars")
        print(f"Metadata: {meta}")
        print(f"{'-'*70}")
        preview = chunk if len(chunk) <= 800 else chunk[:800] + f"\n... [truncated — full length: {len(chunk)} chars]"
        print(preview)
        print(f"{'='*70}\n")
```

---

### File 5: `docs/parser/v2.1.md` *(New Document)*

Create `docs/parser/v2.1.md` containing the v2.1 architectural documentation from `parser_v1`:

```markdown
# v2.1 Implementation Plan & Fixes

**Branch**: `parser_docs`
**Goal**: Fix two critical data-level regressions involving PowerPoint slide title classification (Bug A) and multi-slide chunk metadata extraction (Bug B).

---

## Root Cause Analysis

### Bug A ("Proposed Outcomes" separated from its body)
Docling's PowerPoint backend (`MsPowerpointDocumentBackend`) often misclassifies plain-text slide titles (like "Proposed Outcomes") as `DocItemLabel.PARAGRAPH` instead of `TITLE` or `SECTION_HEADER`. 
Because it's just a `PARAGRAPH`, `HybridChunker` does not treat it as a heading context. It just merges it like normal text. When the token count overflows, `HybridChunker` can break the chunk *right after* the title, separating it completely from its bullets on the slide.

### Bug B (Page 14 hidden in metadata)
`HybridChunker` legitimately merges small consecutive slides (like Page 13's bullets and Page 14's text) into a single chunk if they fit within the token limit. However, our legacy chunk metadata generation in `core/chunker.py` only extracted the page number of the *very first* item in the chunk. Thus, a chunk spanning pages 13 and 14 only got labeled `page: 13`, silently burying subsequent slides.

---

## Fixes Implemented

### 1. `core/parsers/docling_parser.py` (Bug A Fix)
We added a pre-processing step for PPTX files immediately after `DocumentConverter.convert()` and before returning the document to the chunker.

We scan `doc.texts` to identify "pseudo-headings" (short paragraphs at the very beginning of a slide's text sequence). For these items, we upgrade them to `SectionHeaderItem` with label `DocItemLabel.SECTION_HEADER` in the doc's internal structures.
* **Effect**: `HybridChunker` now recognizes these as headings, properly prepending them to the chunk body via `contextualize()`, and strongly preferring to break chunks *before* them rather than after them.

### 2. `core/chunker.py` (Bug B Fix)
We updated `_split_docling()` to extract *all* unique page numbers from `chunk.meta.doc_items`.
- If a chunk is confined to one page: `{"page": 13, "page_numbers": [13]}`
- If a chunk spans multiple pages: `{"page": 13, "page_numbers": [13, 14]}` (Keeping `page` ensures backward compatibility).

### 3. `tests/parsers/test_serialize_fix.py` (Regression Tests)
- Appended `TestBugAFix_PseudoHeadingBoundary` to ensure pseudo-headings act as hard boundaries for the chunker under high token load.
- Appended `TestBugBFix_MultiPageMetadata` to verify the new `page_numbers` array emits properly spanning chunks.

### 4. `tests/unit/test_parse.py` (Display Improvements)
- Updated usage string to reflect `.pptx` and `.docx` support.
- Increased the chunk preview limit from 300 to 800 characters to make debugging chunk contents easier.
```

---

## 3. Verification Checklist

After applying the changes above to `parser_docs`, run the following commands to verify:

```bash
pytest tests/parsers/test_serialize_fix.py -v
pytest tests/parsers/ -v
pytest tests/unit/ -v
```

