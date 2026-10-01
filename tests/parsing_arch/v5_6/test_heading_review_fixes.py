"""
tests/parsing_arch/v5_6/test_heading_review_fixes.py

v5.6 regression tests, built from an external review of a real-PDF run made
against the v5.5 patch. Covers three distinct causes behind the same
symptom (heading-shaped text not participating correctly in the heading
path):

  A. Misplaced section number: "Greasing 6.4 the Groove" -> should read
     "6.4 Greasing the Groove" at level 2, not level 1 with the number
     stuck mid-string.
  B. Empty-text heading regression from v5.5: an empty SECTION_HEADER/TITLE
     was skipped by "if not stripped: continue" and kept its raw level
     (including level 0), silently resetting the heading stack.
  C. Duplicate heading noise: "### **7.1 Consistency**" glued onto the tail
     of the PRECEDING paragraph, duplicating a heading that already exists
     correctly elsewhere -- should be deleted, not promoted again.
  D. Never-detected heading: "10 CRUCIAL TRAINING PRINCIPLES" survives only
     as bold text with no heading item anywhere -- should be promoted.
"""
from docling_core.types.doc import (
    BoundingBox, DocItemLabel, DoclingDocument, ProvenanceItem, SectionHeaderItem,
)
from docling_core.transforms.chunker.hierarchical_chunker import HierarchicalChunker

from parsers.pdf_router import _repair_pdf_headings, _split_embedded_headings, _extract_misplaced_number


def _prov(n):
    return [ProvenanceItem(page_no=n, bbox=BoundingBox(l=0, t=0, r=0, b=0), charspan=(0, 0))]


def _full_repair(doc):
    # _repair_pdf_headings internally invokes _split_embedded_headings(doc)
    _repair_pdf_headings(doc)


# ---------------------------------------------------------------------------
# Fix A — misplaced section number
# ---------------------------------------------------------------------------

class TestMisplacedNumber:
    def test_extract_helper_relocates_single_candidate(self):
        assert _extract_misplaced_number("Greasing 6.4 the Groove") == ("6.4 Greasing the Groove", 2)
        assert _extract_misplaced_number("Strength & Skill Routine 5.7") == \
            ("5.7 Strength & Skill Routine", 2)
        assert _extract_misplaced_number("Chest Circuit 6.5.1") == ("6.5.1 Chest Circuit", 3)

    def test_leading_number_is_left_alone(self):
        assert _extract_misplaced_number("7.3 Train Systematically") is None

    def test_leading_number_with_markdown_prefix_not_relocated(self):
        assert _extract_misplaced_number("**7.3 Train Systematically**") is None
        assert _extract_misplaced_number("(7.3) Train Systematically") is None

    def test_no_dotted_number_returns_none(self):
        assert _extract_misplaced_number("Apply The 8 80/20 Rule 66") is None

    def test_ambiguous_multiple_candidates_returns_none(self):
        assert _extract_misplaced_number("6.1 versus 6.2 comparison") is None

    def test_end_to_end_level_and_text_fixed(self):
        doc = DoclingDocument(name="x")
        h = doc.add_title(text="Greasing 6.4 the Groove")
        h.prov = _prov(16)
        b = doc.add_text(label=DocItemLabel.TEXT, text="body text")
        b.prov = _prov(16)
        _full_repair(doc)
        headers = [t for t in doc.texts if t.label == DocItemLabel.SECTION_HEADER]
        assert headers[0].text == "6.4 Greasing the Groove"
        assert headers[0].level == 2


# ---------------------------------------------------------------------------
# Fix B — empty-text heading regression
# ---------------------------------------------------------------------------

class TestEmptyHeadingRegression:
    def test_empty_title_no_longer_freezes_stack_at_level_0(self):
        doc = DoclingDocument(name="x")
        h1 = doc.add_title(text="7.4 Track Your Progress")
        h1.prov = _prov(19)
        empty = doc.add_title(text="")
        empty.prov = _prov(19)
        h2 = doc.add_heading(text="7.5 Bodybuilding mind", level=1)
        h2.prov = _prov(19)
        body = doc.add_text(label=DocItemLabel.TEXT, text="mindset body")
        body.prov = _prov(19)

        _full_repair(doc)
        headings = {c.text: c.meta.headings for c in HierarchicalChunker().chunk(doc)}
        assert headings["mindset body"] == ["7.5 Bodybuilding mind"]

    def test_empty_heading_item_produces_no_chunk(self):
        doc = DoclingDocument(name="x")
        empty = doc.add_title(text="")
        empty.prov = _prov(19)
        body = doc.add_text(label=DocItemLabel.TEXT, text="some body text")
        body.prov = _prov(19)
        _full_repair(doc)
        texts_emitted = [c.text for c in HierarchicalChunker().chunk(doc) if c.text]
        assert "" not in texts_emitted
        assert texts_emitted == ["some body text"]


# ---------------------------------------------------------------------------
# Fix C — duplicate heading noise deleted, not re-promoted
# ---------------------------------------------------------------------------

class TestDuplicateHeadingNoise:
    def test_trailing_atx_duplicate_is_stripped_not_repromoted(self):
        doc = DoclingDocument(name="x")
        prior = doc.add_text(
            label=DocItemLabel.TEXT,
            text="For each principle we will show you how to apply this with calisthenics.\n"
                 "### **7.1 Consistency**",
        )
        prior.prov = _prov(18)
        real_heading = doc.add_heading(text="7.1 Consistency", level=1)
        real_heading.prov = _prov(18)
        body = doc.add_text(label=DocItemLabel.TEXT, text="You will only see results if...")
        body.prov = _prov(18)

        _full_repair(doc)

        headers = [t for t in doc.texts if t.label == DocItemLabel.SECTION_HEADER]
        assert [h.text for h in headers] == ["7.1 Consistency"]  # not duplicated
        assert prior.text == "For each principle we will show you how to apply this with calisthenics."
        chunk_texts = [c.text for c in HierarchicalChunker().chunk(doc)]
        assert not any("###" in t or "**7.1" in t for t in chunk_texts)

    def test_item_that_is_purely_duplicate_noise_becomes_empty_and_drops(self):
        doc = DoclingDocument(name="x")
        real_heading = doc.add_heading(text="8.1 Can you make muscles with calisthenics?", level=1)
        real_heading.prov = _prov(22)
        noise = doc.add_text(label=DocItemLabel.TEXT,
                              text="### **8.1 Can you make muscles with calisthenics?**")
        noise.prov = _prov(22)
        body = doc.add_text(label=DocItemLabel.TEXT, text="Yes it is possible.")
        body.prov = _prov(22)

        _full_repair(doc)
        chunk_texts = [c.text for c in HierarchicalChunker().chunk(doc) if c.text]
        assert chunk_texts == ["Yes it is possible."]

    def test_unmatched_hash_fragment_is_left_alone(self):
        """A '#' fragment that doesn't correspond to any real heading elsewhere
        is NOT deleted -- Fix C only strips confirmed duplicates."""
        doc = DoclingDocument(name="x")
        item = doc.add_text(label=DocItemLabel.TEXT, text="Room #42 was fully booked.\n### **Nonexistent**")
        item.prov = _prov(1)
        _full_repair(doc)
        assert item.text == "Room #42 was fully booked.\n### **Nonexistent**"

    def test_embedded_heading_separated_by_space_stripped(self):
        doc = DoclingDocument(name="x")
        prior = doc.add_text(
            label=DocItemLabel.TEXT,
            text="Calisthenics is great.  ### **7.1 Consistency**",
        )
        prior.prov = _prov(18)
        real_heading = doc.add_heading(text="7.1 Consistency", level=1)
        real_heading.prov = _prov(18)
        body = doc.add_text(label=DocItemLabel.TEXT, text="Body text...")
        body.prov = _prov(18)
        _full_repair(doc)
        assert prior.text == "Calisthenics is great."


# ---------------------------------------------------------------------------
# Fix D — genuinely-missing heading promoted
# ---------------------------------------------------------------------------

class TestMissingAllCapsHeadingPromoted:
    def test_bold_allcaps_prefix_promoted_to_heading(self):
        doc = DoclingDocument(name="x")
        prior_heading = doc.add_heading(text="Beginners Circuit", level=1)
        prior_heading.prov = _prov(17)
        item = doc.add_text(
            label=DocItemLabel.TEXT,
            text="**10 CRUCIAL TRAINING PRINCIPLES You should implement all these "
                 "principles to progress optimally!**",
        )
        item.prov = _prov(18)
        first_principle = doc.add_heading(text="7.1 Consistency", level=1)
        first_principle.prov = _prov(18)
        body = doc.add_text(label=DocItemLabel.TEXT, text="You will only see results...")
        body.prov = _prov(18)

        _full_repair(doc)

        heading_texts = [t.text for t in doc.texts if t.label == DocItemLabel.SECTION_HEADER]
        assert "10 CRUCIAL TRAINING PRINCIPLES" in heading_texts
        chunk_by_body = {c.text: c.meta.headings for c in HierarchicalChunker().chunk(doc)}
        # "10 CRUCIAL..." (level 1, unnumbered) and "7.1 Consistency" (level 2,
        # from its one dot) are DIFFERENT levels, so both correctly stay active
        # -- this mirrors "Beginners Circuit" (level 1) coexisting with numbered
        # subsections in the real corpus.
        assert chunk_by_body["You will only see results..."] == \
            ["10 CRUCIAL TRAINING PRINCIPLES", "7.1 Consistency"]
        remaining = [t for t in doc.texts
                     if t.label in (DocItemLabel.PARAGRAPH, DocItemLabel.TEXT)
                     and "CRUCIAL" in (t.text or "")]
        assert remaining == []  # heading text removed from the paragraph, not duplicated

    def test_bold_heading_with_closing_asterisks_promoted(self):
        doc = DoclingDocument(name="x")
        item = doc.add_text(
            label=DocItemLabel.TEXT,
            text="**10 CRUCIAL TRAINING PRINCIPLES** You should implement all these principles.",
        )
        item.prov = _prov(18)
        body = doc.add_text(label=DocItemLabel.TEXT, text="Follow-up body text")
        body.prov = _prov(18)
        _full_repair(doc)
        heading_texts = [t.text for t in doc.texts if t.label == DocItemLabel.SECTION_HEADER]
        assert "10 CRUCIAL TRAINING PRINCIPLES" in heading_texts
        assert item.text == "You should implement all these principles."

    def test_ordinary_prose_is_not_mis_promoted(self):
        doc = DoclingDocument(name="x")
        item = doc.add_text(label=DocItemLabel.TEXT, text="The USA has many states.")
        item.prov = _prov(1)
        _full_repair(doc)
        assert not [t for t in doc.texts if t.label == DocItemLabel.SECTION_HEADER]
        assert item.text == "The USA has many states."

    def test_already_existing_heading_is_not_duplicated(self):
        doc = DoclingDocument(name="x")
        existing = doc.add_heading(text="ADVANCED CIRCUIT TRAINING", level=1)
        existing.prov = _prov(1)
        item = doc.add_text(
            label=DocItemLabel.TEXT,
            text="**ADVANCED CIRCUIT TRAINING Follow the routine below closely.**",
        )
        item.prov = _prov(2)
        _full_repair(doc)
        heading_texts = [t.text for t in doc.texts if t.label == DocItemLabel.SECTION_HEADER]
        assert heading_texts.count("ADVANCED CIRCUIT TRAINING") == 1
