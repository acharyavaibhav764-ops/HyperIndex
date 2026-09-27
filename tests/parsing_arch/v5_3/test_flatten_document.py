"""
tests/parsing_arch/v5_3/test_flatten_document.py

v5.3 regression tests for Fix 2: _flatten_document() rebuilds the merged
document as a flat structure where every text item is a direct child of body.

This fixes both the heading freeze (items' stale parent refs caused
HybridChunker to walk into stale cross-page sub-trees) and the tail-ordering
orphan bug (add_document() moved parentless items to the doc tail).

Test inventory:
  3. test_flatten_removes_nesting
  4. test_flatten_preserves_order_and_provenance
  5. test_heading_path_advances_across_pages_end_to_end
  6. test_chunk_order_matches_page_order  (Issue 4 final answer)
"""
import pytest
from io import BytesIO
from unittest.mock import patch

from docling_core.types.doc import (
    DoclingDocument,
    DocItemLabel,
    ProvenanceItem,
    BoundingBox,
)

from parsers.pdf_router import _flatten_document, PdfPageRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_prov(page_no: int) -> list[ProvenanceItem]:
    return [ProvenanceItem(
        page_no=page_no,
        bbox=BoundingBox(l=0, t=0, r=0, b=0),
        charspan=(0, 10),
    )]


def _add(doc: DoclingDocument, text: str, label: DocItemLabel, page_no: int,
         parent=None):
    """Add a text item with provenance; default parent is doc.body."""
    item = doc.add_text(label=label, text=text, parent=parent or doc.body)
    item.prov = _make_prov(page_no)
    return item


# ---------------------------------------------------------------------------
# Test 3 — flatten removes nesting
# ---------------------------------------------------------------------------

class TestFlattenRemovesNesting:
    def test_flatten_removes_nesting(self):
        """All items in the flattened document must be direct children of body.

        Simulates the stale-nesting bug: a SECTION_HEADER on page 1 has a
        PARAGRAPH as a child, and a SECTION_HEADER from page 2 is (incorrectly)
        nested under the page-1 heading — exactly the structure add_document()
        produces when per-page sub-trees get stitched together.
        """
        doc = DoclingDocument(name="test")

        # Page 1: heading with a child paragraph (legitimate nesting within a page)
        h1 = _add(doc, "5.5 Mobility", DocItemLabel.SECTION_HEADER, page_no=1)
        p1 = doc.add_text(label=DocItemLabel.PARAGRAPH, text="Body text.", parent=h1)
        p1.prov = _make_prov(1)

        # Page 2: heading incorrectly nested under page-1 heading (the bug)
        h2 = doc.add_text(
            label=DocItemLabel.SECTION_HEADER,
            text="7.1 Strength",
            parent=h1,   # WRONG: should be body, but add_document() may do this
        )
        h2.prov = _make_prov(2)

        flat = _flatten_document(doc)

        body_cref = flat.body.self_ref
        for item in flat.texts:
            assert item.parent is not None, "Every item must have a parent"
            assert item.parent.cref == body_cref, (
                f"Item '{item.text}' parent must be body ({body_cref}), "
                f"got {item.parent.cref}"
            )

    def test_flatten_makes_section_headers_siblings(self):
        """After flattening, all SECTION_HEADERs must be siblings under body —
        none should be an ancestor/descendant of another.
        """
        doc = DoclingDocument(name="test")
        h1 = _add(doc, "5.5 Mobility", DocItemLabel.SECTION_HEADER, page_no=1)
        # Nest second heading under first (simulating the bug)
        h2 = doc.add_text(
            label=DocItemLabel.SECTION_HEADER,
            text="7.1 Strength",
            parent=h1,
        )
        h2.prov = _make_prov(2)

        flat = _flatten_document(doc)

        section_headers = [i for i in flat.texts if i.label == DocItemLabel.SECTION_HEADER]
        assert len(section_headers) == 2

        body_cref = flat.body.self_ref
        for sh in section_headers:
            assert sh.parent.cref == body_cref, (
                f"SECTION_HEADER '{sh.text}' must be a direct child of body"
            )


# ---------------------------------------------------------------------------
# Test 4 — order and provenance preserved
# ---------------------------------------------------------------------------

class TestFlattenPreservesOrderAndProvenance:
    def test_flatten_preserves_order(self):
        """flat.texts must appear in the same order as doc.texts."""
        doc = DoclingDocument(name="test")
        texts = ["Alpha", "Beta", "Gamma", "Delta"]
        for i, t in enumerate(texts, start=1):
            _add(doc, t, DocItemLabel.PARAGRAPH, page_no=i)

        flat = _flatten_document(doc)

        assert [item.text for item in flat.texts] == texts

    def test_flatten_preserves_provenance(self):
        """Every item in flat.texts must have the same page_no as the
        corresponding source item."""
        doc = DoclingDocument(name="test")
        for pg in range(1, 6):
            _add(doc, f"Page {pg} content", DocItemLabel.PARAGRAPH, page_no=pg)

        flat = _flatten_document(doc)

        for i, item in enumerate(flat.texts, start=1):
            assert item.prov, f"Item {i} has no prov"
            assert item.prov[0].page_no == i, (
                f"Item {i}: expected page_no={i}, got {item.prov[0].page_no}"
            )

    def test_flatten_preserves_labels(self):
        """Text item labels (SECTION_HEADER, PARAGRAPH, TITLE) survive the rebuild."""
        doc = DoclingDocument(name="test")
        _add(doc, "5.5 Mobility", DocItemLabel.SECTION_HEADER, page_no=1)
        _add(doc, "Body text.", DocItemLabel.PARAGRAPH, page_no=1)
        _add(doc, "7.1 Strength", DocItemLabel.SECTION_HEADER, page_no=2)

        flat = _flatten_document(doc)

        labels = [item.label for item in flat.texts]
        assert labels == [
            DocItemLabel.SECTION_HEADER,
            DocItemLabel.PARAGRAPH,
            DocItemLabel.SECTION_HEADER,
        ]


# ---------------------------------------------------------------------------
# Test 5 — heading path advances across pages end-to-end
# ---------------------------------------------------------------------------

class TestHeadingPathAdvancesEndToEnd:
    def test_heading_path_advances_across_pages_end_to_end(self):
        """After _flatten_document(), section headers from later pages must be
        siblings of earlier ones — not nested under them.

        This is the test the v5.2 _repair_pdf_headings()-only approach failed:
        even after label correction, items still had stale parent refs pointing
        to the page-1 heading sub-tree, causing the freeze.
        """
        from parsers.pdf_router import _repair_pdf_headings

        doc = DoclingDocument(name="test")

        # Simulate merged multi-page doc with cross-page nesting
        h1 = _add(doc, "5.5 Mobility", DocItemLabel.SECTION_HEADER, page_no=1)

        # Pages 2-5: headings incorrectly nested under page-1 heading
        for pg, text in enumerate(
            ["6.1 Coordination", "7.3 Core Strength", "8.1 Endurance"],
            start=2,
        ):
            item = doc.add_text(
                label=DocItemLabel.SECTION_HEADER,
                text=text,
                parent=h1,   # stale: nested under page-1 heading
            )
            item.prov = _make_prov(pg)

        _repair_pdf_headings(doc, min_page_repeats=10)  # no boilerplate in fixture
        flat = _flatten_document(doc)

        body_cref = flat.body.self_ref
        for item in flat.texts:
            assert item.parent.cref == body_cref, (
                f"After flatten, '{item.text}' must be parented to body, "
                f"not to a stale page-1 ancestor"
            )

        # All section headers must be siblings — none nested under another
        section_headers = [i for i in flat.texts if i.label == DocItemLabel.SECTION_HEADER]
        assert len(section_headers) == 4  # one per page (h1 + 3 more)


# ---------------------------------------------------------------------------
# Test 6 — chunk order matches page order (Issue 4 resolution)
# ---------------------------------------------------------------------------

class TestChunkOrderMatchesPageOrder:
    def test_chunk_order_matches_page_order(self):
        """After _flatten_document(), text items must appear in non-decreasing
        page_no order — orphaned tail-items (the Issue 4 symptom) must not exist.

        This is run against _merge_pages() output so it covers the full pipeline:
        per-page markdown conversion → add_document() → _repair_pdf_headings()
        → _flatten_document().
        """
        router = PdfPageRouter()

        # Page 2 and 4 have bare/floating content (the kind that caused orphans)
        page_markdowns = [
            "# Section 1\n\nNormal paragraph on page 1.",
            "Table 2.1 caption\n",           # bare line — potential floating node
            "# Section 3\n\nNormal paragraph on page 3.",
            "    code_line = True\n",          # isolated code — another floating node
            "# Section 5\n\nNormal paragraph on page 5.",
        ]

        combined = router._merge_pages(page_markdowns, "test.pdf")

        page_nos = [
            item.prov[0].page_no
            for item in combined.texts
            if getattr(item, "prov", None)
        ]

        assert page_nos == sorted(page_nos), (
            f"Text items are out of page order after _flatten_document(): {page_nos}\n"
            "If this fails, Issue 4 is NOT resolved by flattening — needs separate fix."
        )

    def test_all_items_parented_to_body_after_merge(self):
        """Every text item in the merged document must be a direct child of body
        (not nested under a stale per-page sub-tree root).
        """
        router = PdfPageRouter()

        page_markdowns = [
            "# Section 1\n\nContent on page 1.",
            "## Subsection 2.1\n\nContent on page 2.",
            "# Section 3\n\nContent on page 3.",
        ]

        flat = router._merge_pages(page_markdowns, "test.pdf")

        body_cref = flat.body.self_ref
        for item in flat.texts:
            assert item.parent is not None
            assert item.parent.cref == body_cref, (
                f"'{item.text}' must be a direct child of body after _flatten_document()"
            )
