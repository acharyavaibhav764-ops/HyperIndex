"""
tests/parsing_arch/v5_2/test_chunk_ordering.py

v5.2 Issue 4 investigation tests — page-order monotonicity after _merge_pages().

These tests are intentionally written to detect the out-of-order tail-chunk
bug observed in the real run (chunks for pages 17 and 32 appearing after page 36
content). As of v5.2 the root cause has not been confirmed — whether the bug
is in DoclingDocument.add_document(), the per-page markdown parser producing
floating/parentless nodes, or elsewhere.

Per the plan:
  Step 1 (this patch): land these tests so the failure is pinned precisely.
  Step 2 (follow-up): decide and apply the fix based on what the failure output shows.

Tests 9 and 10 are marked xfail with strict=False — they are expected to fail
on current code. When they start passing (post-fix), change to strict=True or
remove the mark entirely.
"""
import pytest
from io import BytesIO
from unittest.mock import MagicMock, patch

from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import InputFormat
from docling_core.types.doc import DoclingDocument, ProvenanceItem, BoundingBox
from docling_core.types.io import DocumentStream

from parsers.pdf_router import PdfPageRouter


# ---------------------------------------------------------------------------
# Helper: build a minimal DoclingDocument from a markdown string
# ---------------------------------------------------------------------------

def _doc_from_md(md: str, name: str = "page.md") -> DoclingDocument:
    converter = DocumentConverter(allowed_formats=[InputFormat.MD])
    stream = DocumentStream(name=name, stream=BytesIO(md.encode("utf-8")))
    return converter.convert(stream).document


# ---------------------------------------------------------------------------
# Test 9 — page-order monotonicity end-to-end
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=False,
    reason=(
        "Issue 4 not yet fixed: orphaned/floating markdown fragments may be appended "
        "out of page order by DoclingDocument.add_document(). "
        "This test pins the failure; fix in follow-up once root cause confirmed."
    ),
)
def test_chunk_order_matches_page_order():
    """All text items in the merged document must have non-decreasing page_no values.

    Simulates the real bug: a stray table-caption fragment (no enclosing block)
    and an isolated code-line — the kinds of floating nodes that appeared on
    pages 17 and 32 but were emitted after page 36 content.
    """
    router = PdfPageRouter()

    # Build page markdowns. Page 2 and 4 have "floating" content (bare lines
    # with no surrounding paragraph context) that may cause add_document() to
    # reorder items.
    page_markdowns = [
        "# Section 1\n\nNormal paragraph on page 1.",
        # Page 2: a bare line with no paragraph context — mimics a floating caption
        "Table 2.1 caption\n",
        "# Section 3\n\nNormal paragraph on page 3.",
        # Page 4: isolated code fragment — another common floating node source
        "    code_line = True\n",
        "# Section 5\n\nNormal paragraph on page 5.",
    ]

    combined = router._merge_pages(page_markdowns, "test.pdf")

    # Collect page_no values in the order items appear in combined.texts
    page_nos = []
    for item in combined.texts:
        if getattr(item, "prov", None):
            page_nos.append(item.prov[0].page_no)

    assert page_nos == sorted(page_nos), (
        f"Text items are out of page order: {page_nos}\n"
        "This is the Issue 4 ordering bug — floating nodes placed at doc tail by "
        "DoclingDocument.add_document()."
    )


# ---------------------------------------------------------------------------
# Test 10 — isolate add_document() ordering behaviour
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=False,
    reason=(
        "Issue 4 investigation: checks whether DoclingDocument.add_document() "
        "itself is the reordering source for parentless text items. "
        "Expected to fail if add_document() moves floating nodes to the tail."
    ),
)
def test_add_document_preserves_item_order():
    """Merge two tiny per-page documents — one with a normal paragraph and one
    with a parentless text item — and assert combined.texts preserves insertion order.

    Pinpoints whether the reorder originates in add_document() or upstream
    (e.g. the per-page MD converter producing the floating node).
    """
    # Page 1: regular paragraph
    page1 = _doc_from_md("Normal paragraph on page 1.", "page_1.md")
    for item in page1.texts:
        item.prov = [ProvenanceItem(
            page_no=1, bbox=BoundingBox(l=0, t=0, r=0, b=0), charspan=(0, 10)
        )]

    # Page 2: bare line (no enclosing block — produces a floating/parentless node)
    page2 = _doc_from_md("Floating caption fragment\n", "page_2.md")
    for item in page2.texts:
        item.prov = [ProvenanceItem(
            page_no=2, bbox=BoundingBox(l=0, t=0, r=0, b=0), charspan=(0, 10)
        )]

    # Page 3: another regular paragraph
    page3 = _doc_from_md("Normal paragraph on page 3.", "page_3.md")
    for item in page3.texts:
        item.prov = [ProvenanceItem(
            page_no=3, bbox=BoundingBox(l=0, t=0, r=0, b=0), charspan=(0, 10)
        )]

    combined = DoclingDocument(name="test")
    for page_doc in (page1, page2, page3):
        combined.add_document(page_doc)

    page_nos = [
        item.prov[0].page_no
        for item in combined.texts
        if getattr(item, "prov", None)
    ]

    assert page_nos == sorted(page_nos), (
        f"add_document() reordered items: {page_nos}\n"
        "This confirms add_document() is the source of Issue 4's reorder."
    )
