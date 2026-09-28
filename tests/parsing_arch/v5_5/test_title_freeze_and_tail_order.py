"""
tests/parsing_arch/v5_5/test_title_freeze_and_tail_order.py

v5.5 regression tests, built from the v5.4 diagnostic evidence.

Root causes (confirmed by Diagnostic A/B):
  A. Heading freeze: pymupdf4llm runs per page, so a sub-section heading that is the
     largest font on its page comes out as '# ' -> TitleItem.  HierarchicalChunker
     keys its heading stack by level and treats TitleItem as level 0, which no
     SectionHeader (level >= 1) can ever clear.  Diagnostic A missed it because it
     only printed label == SECTION_HEADER.
  B. Tail orphans: core/chunker.py's "Gap B" loop appended heading-only synthetic
     chunks at the END of the chunk list.  The flat doc.texts order was always fine
     (Diagnostic B confirmed orphans at correct flat-list indices).
"""
import pytest
from docling_core.types.doc import (
    BoundingBox, DocItemLabel, DoclingDocument, ProvenanceItem,
)
from docling_core.transforms.chunker.hierarchical_chunker import HierarchicalChunker

from parsers.pdf_router import _repair_pdf_headings, _heading_level, _as_section_header


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _prov(n):
    return [ProvenanceItem(page_no=n, bbox=BoundingBox(l=0, t=0, r=0, b=0), charspan=(0, 0))]


def _page(n, spec):
    """Build a single-page DoclingDocument from a list of (kind, text) tuples."""
    d = DoclingDocument(name=f"p{n}")
    for kind, txt in spec:
        if kind == "title":
            it = d.add_title(text=txt)
        elif kind.startswith("h"):
            it = d.add_heading(text=txt, level=int(kind[1]))
        else:
            it = d.add_text(label=DocItemLabel.TEXT, text=txt)
        it.prov = _prov(n)
    return d


def _merged(pages):
    """Merge a list of (page_spec) into a single DoclingDocument via add_document()."""
    combined = DoclingDocument(name="x")
    for n, spec in enumerate(pages, 1):
        combined.add_document(_page(n, spec))
    return combined


# Realistic scenario mirroring the Calisthenics PDF:
# - "5.5 Mobility" was the largest font on its page -> TitleItem (level 0)
# - "5.6 Structure" was on a different page, correctly a h1
# - "7.3 Train Systematically" was labelled TEXT (not even a heading), needs promotion
# - "7.10 Supercompensation" was TitleItem again (largest on its page)
PAGES = [
    [("title", "5.5 Mobility"), ("p", "mobility body")],
    [("h1", "5.6 Structure"), ("p", "structure body")],
    [("p", "7.3 Train Systematically"), ("p", "train body")],
    [("h2", "7.4 Track Progress"), ("p", "track body")],
    [("title", "7.10 Supercompensation"), ("p", "super body")],
]


def _headings_by_body(doc):
    """Return {body_text: headings_list} dict from HierarchicalChunker output."""
    return {c.text: c.meta.headings for c in HierarchicalChunker().chunk(doc)}


# ---------------------------------------------------------------------------
# Fix A — Heading freeze / TitleItem normalisation
# ---------------------------------------------------------------------------

class TestHeadingFreezeFix:
    def test_bug_reproduced_without_repair(self):
        """Sanity: raw merged doc really exhibits the freeze (TitleItem level 0 sticks)."""
        hb = _headings_by_body(_merged(PAGES))
        # Without repair, '5.5 Mobility' (TitleItem, level 0) freezes across all pages
        assert "5.5 Mobility" in hb.get("track body", [])

    def test_title_items_no_longer_freeze_heading_path(self):
        """After _repair_pdf_headings, each body text sees only its own section heading."""
        doc = _merged(PAGES)
        _repair_pdf_headings(doc)
        hb = _headings_by_body(doc)
        assert hb["mobility body"] == ["5.5 Mobility"]
        assert hb["structure body"] == ["5.6 Structure"]
        assert hb["train body"] == ["7.3 Train Systematically"]
        assert hb["track body"] == ["7.4 Track Progress"]
        assert hb["super body"] == ["7.10 Supercompensation"]

    def test_no_title_labels_remain_after_repair(self):
        """_repair_pdf_headings must convert every TitleItem to SectionHeaderItem."""
        doc = _merged(PAGES)
        _repair_pdf_headings(doc)
        remaining_titles = [t for t in doc.texts if t.label == DocItemLabel.TITLE]
        assert remaining_titles == [], (
            f"TitleItems still present after repair: {[t.text for t in remaining_titles]}"
        )

    def test_levels_follow_numbering_depth(self):
        """Numbering depth -> level: N -> 1, N.N -> 2, N.N.N -> 3."""
        doc = _merged(PAGES)
        _repair_pdf_headings(doc)
        levels = {t.text: t.level for t in doc.texts if t.label == DocItemLabel.SECTION_HEADER}
        # "5.5 Mobility", "5.6 Structure", "7.3 Train..", "7.4 Track.." are all N.N -> level 2
        assert levels["5.5 Mobility"] == 2
        assert levels["5.6 Structure"] == 2
        assert levels["7.3 Train Systematically"] == 2
        # "7.10 Supercompensation" is N.NN -> still one dot -> level 2
        assert levels["7.10 Supercompensation"] == 2

    def test_deeper_numbering_gives_higher_level(self):
        """N -> 1, N.N -> 2, N.N.N -> 3."""
        doc = _merged([
            [("title", "7 Training"), ("p", "x")],
            [("p", "7.1.2 Deep dive"), ("p", "y")],
        ])
        _repair_pdf_headings(doc)
        lv = {t.text: t.level for t in doc.texts if t.label == DocItemLabel.SECTION_HEADER}
        assert lv["7 Training"] == 1
        assert lv["7.1.2 Deep dive"] == 3

    def test_unnumbered_title_becomes_level_1_not_0(self):
        """An unnumbered TitleItem (e.g. 'CONTENTS') must become level 1, not 0."""
        doc = _merged([[("title", "CONTENTS"), ("p", "body")]])
        _repair_pdf_headings(doc)
        h = [t for t in doc.texts if t.text == "CONTENTS"][0]
        assert h.label == DocItemLabel.SECTION_HEADER
        assert h.level == 1, f"Expected level=1, got level={h.level}"


# ---------------------------------------------------------------------------
# Fix A — _heading_level / _as_section_header helpers
# ---------------------------------------------------------------------------

class TestHeadingLevelHelper:
    def test_numbered_level_from_dot_count(self):
        assert _heading_level("7 Training", None) == 1
        assert _heading_level("7.3 Systematic", None) == 2
        assert _heading_level("7.3.1 Detail", None) == 3
        assert _heading_level("9.4.2.1 Deep", None) == 4

    def test_unnumbered_keeps_current_level_min_1(self):
        assert _heading_level("CONTENTS", None) == 1
        assert _heading_level("CONTENTS", 0) == 1   # level 0 is clamped to 1
        assert _heading_level("CONTENTS", 3) == 3   # existing level is preserved

    def test_as_section_header_sets_label_and_level(self):
        d = DoclingDocument(name="t")
        item = d.add_title(text="5.5 Mobility")
        result = _as_section_header(item, 2)
        assert result.label == DocItemLabel.SECTION_HEADER
        assert result.level == 2
        assert result.text == "5.5 Mobility"


# ---------------------------------------------------------------------------
# Fix A — TEXT-labelled numbered lines are now promoted
# ---------------------------------------------------------------------------

class TestTextLabelPromotion:
    def test_text_labelled_numbered_line_promoted(self):
        """MD backend labels paragraphs TEXT; v5.2 promotion only matched PARAGRAPH (dead code)."""
        doc = _merged([[("p", "7.3 Train Systematically"), ("p", "body")]])
        _repair_pdf_headings(doc)
        heads = [t.text for t in doc.texts if t.label == DocItemLabel.SECTION_HEADER]
        assert "7.3 Train Systematically" in heads

    def test_reps_line_not_promoted(self):
        """'3 sets of 10 reps' must never become a heading."""
        doc = _merged([[("p", "3 sets of 10 reps"), ("p", "body")]])
        _repair_pdf_headings(doc)
        heads = [t.text for t in doc.texts if t.label == DocItemLabel.SECTION_HEADER]
        assert "3 sets of 10 reps" not in heads

    def test_decimal_weight_not_promoted(self):
        """'2.5 kg is the minimum load you should add.' must not be promoted."""
        doc = _merged([[("p", "2.5 kg is the minimum load you should add."), ("p", "body")]])
        _repair_pdf_headings(doc)
        heads = [t.text for t in doc.texts if t.label == DocItemLabel.SECTION_HEADER]
        assert not heads


# ---------------------------------------------------------------------------
# Fix B — Tail orphans / chunk insert order
# ---------------------------------------------------------------------------

class _FakeHybrid:
    """HybridChunker stand-in (real one needs a HF tokenizer download)."""
    def __init__(self, **kw):
        self._c = HierarchicalChunker()

    def chunk(self, doc):
        return self._c.chunk(doc)

    def contextualize(self, chunk):
        return "\n".join((chunk.meta.headings or []) + [chunk.text])


class TestTailOrphanFix:
    def test_heading_only_chunks_land_in_page_order_not_at_tail(self, monkeypatch):
        """Heading-only items that produce standalone synthetic chunks must appear
        at their page position, not appended after the last real page's chunks."""
        import core.chunker as ck
        monkeypatch.setattr(ck, "HybridChunker", _FakeHybrid)

        doc = _merged([
            [("h1", "Intro"), ("p", "p1 body")],
            [("h1", "Advanced Circuit"), ("h1", "Next Section")],  # heading-only page
            [("p", "p3 body")],
            [("p", "p4 body")],
        ])
        chunks, metas, ids = ck.Chunker().split(doc, "f", "f.pdf")
        pages = [m["page"] for m in metas]
        assert pages == sorted(pages), f"Chunks out of page order: {pages}"
        assert "Advanced Circuit" in chunks
        # chunk_index must be contiguous
        assert [m["chunk_index"] for m in metas] == list(range(len(metas)))
        # IDs must match chunk_index
        assert ids == [f"f_c{i}" for i in range(len(ids))]

    def test_chunk_index_renumbered_after_insert(self, monkeypatch):
        """After inserting a synthetic chunk mid-list, chunk_index must equal list position."""
        import core.chunker as ck
        monkeypatch.setattr(ck, "HybridChunker", _FakeHybrid)

        doc = _merged([
            [("p", "page1 body")],
            [("h1", "Orphan Heading")],   # heading-only page 2
            [("p", "page3 body")],
        ])
        chunks, metas, ids = ck.Chunker().split(doc, "g", "g.pdf")
        for i, m in enumerate(metas):
            assert m["chunk_index"] == i, (
                f"chunk_index mismatch at position {i}: meta={m}"
            )
