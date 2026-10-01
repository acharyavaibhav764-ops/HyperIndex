"""v5.7 tests -- text clean-up, table normalisation, structure repair, table chunking.

Runs without Docling models: only docling_core (+ pymupdf for the optional real-PDF test).
"""
import os
import pathlib
import re

import pytest
from docling_core.transforms.chunker.hierarchical_chunker import HierarchicalChunker
from docling_core.types.doc import (
    BoundingBox, DocItemLabel, DoclingDocument, ProvenanceItem,
)
from docling_core.types.doc.document import TableCell, TableData

from parsers import pdf_cleanup as C
from parsers import pdf_structure as S
from parsers.pdf_router import _repair_pdf_headings
from core.chunker import _MarkdownTableSerializerProvider

VOCAB = C.build_vocab([
    "based on different muscle groups combined with training you should consume healthy food "
    "kind of fats instead of saturated fats per hour of training lose more water drinking",
] * 4)


# ---------------------------------------------------------------- text repairs
def test_urls_are_rejoined():
    assert C.rejoin_urls("at https:/ /calisthenics-family.com") == "at https://calisthenics-family.com"
    assert C.rejoin_urls("see https:/ /manytools.org/handy/ bmr-calculator/") == \
        "see https://manytools.org/handy/bmr-calculator/"
    assert C.rejoin_urls("at https:/ /calisthenics-family.com / meal-plan") == \
        "at https://calisthenics-family.com/meal-plan"


def test_lost_spaces_repaired_only_with_document_vocabulary():
    assert C.fix_lost_spaces("training days basedon different", VOCAB) == "training days based on different"
    assert C.fix_lost_spaces("shouldyouconsume", VOCAB) == "should you consume"
    assert C.fix_lost_spaces("Brinta Shrimpflip", VOCAB) == "Brinta Shrimpflip"   # unknown words untouched
    assert C.fix_lost_spaces("training", VOCAB) == "training"                      # real word untouched


def test_known_corpus_fixes():
    assert C.apply_known_fixes("Protein (perlOOg)") == "Protein (per 100g)"
    assert C.apply_known_fixes("Assisted Pistol Sguat") == "Assisted Pistol Squat"
    assert "FULLJOURNEY25" in C.apply_known_fixes("Use Code ‘FULUOURIMEY25’ to Get 25% Off")
    assert "BEGINNER25" in C.apply_known_fixes("Use Code ‘BEGINNER 25’ For 25% Off")
    assert "BURNFAT25" in C.apply_known_fixes("Use Code ‘BURNFAT25’ For 25% Off")


def test_markup_and_newline_fragments():
    assert C.strip_markup("end ### **7.1 Consistency**") .strip() == "end 7.1 Consistency"
    assert "**" not in C.strip_markup("**bold** and **-** **set**")
    assert C.join_soft_breaks("about 15\n-\n30 minute and well\n-\nstructured") == \
        "about 15-30 minute and well-structured"
    assert C.join_soft_breaks("a\nKalos\nb") == "a Kalos b"


def test_letter_spacing_and_punctuation():
    assert C.collapse_letter_spacing("R o u n d 1 (A d v a n c e d)") == "Round 1 (Advanced)"
    assert C.fix_punct_spacing("Exc . 1 ( per 100g )") == "Exc. 1 (per 100g)"


def test_photo_noise_detection():
    for junk in ("*<br>I<br>is<br>*", "I\nr\n/\n*\n/ !\n*\n\\\nf\nV\ni 1", "m\nML m &\n191 '\n>\nBK '\nISmam"):
        assert C.is_noise_paragraph(junk)
    for keep in ("BY CALISTHENICS FAMILY", "Best,", "Use Code BURNFAT25 For 25% Off"):
        assert not C.is_noise_paragraph(keep)


def test_doubled_paragraph_collapses_to_the_better_copy():
    good = ("If you do intensive sports, you lose about one liter of extra fluid per hour of training. "
            "So if you train 2 hours per day intensively you lose a total of 2 liters of fluid.")
    bad = good.replace("fluid per hour", "fluidperhour").replace("So if", "Soif")
    assert C.dedupe_doubled_text(bad + " " + good) == good
    assert C.dedupe_doubled_text(good) == good


def test_running_footers_removed_but_content_kept():
    words = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo".split()
    pages = [f"Unique {w} paragraph\n\n**Calisthenics Family | Calisthenics Training Guide {i+1}**\n\n**{i+1}**"
             for i, w in enumerate(words)]
    out = C.strip_running_lines(pages)
    assert all("Training Guide" not in p and f"**{i+1}**" not in p for i, p in enumerate(out))
    assert all(f"Unique {w} paragraph" in p for w, p in zip(words, out))


# ---------------------------------------------------------------- tables
def test_side_by_side_protein_table_is_split_per_group():
    md = ("| Meat / Eggs | Protein (perlOOg) | Fish | Protein (perlOOg) |\n|---|---|---|---|\n"
          "| Beef | 24 | Tuna | 25 |\n| Eggs | 13 | Mackerel | 18 |")
    out = C.clean_markdown_tables(md)
    assert "| Fish | Protein (per 100g) |" in out
    assert "| Beef | 24 |" in out and "Tuna" not in out.split("| Fish")[0]


def test_core_circuit_round_rows_become_their_own_tables():
    md = ("| Round | 1 (Dynamic) | Reps | Target Muscles |\n|---|---|---|---|\n"
          "| Exc. 1 | Dragon Fly's | 8 | Lower abs + back |\n"
          "| Round | 2 (Static) | Reps | Target Muscles |\n"
          "| Exc. 1 | Dragon Flag | Max | Lower abs + back |")
    out = C.clean_markdown_tables(md)
    assert out.count("| Round 1 (Dynamic) |") == 1 and out.count("| Round 2 (Static) |") == 1
    assert out.index("Dragon Fly's") < out.index("Round 2 (Static)") < out.index("Dragon Flag")


def test_contents_table_numerals_and_filler_rows():
    md = ("| I. | Introduction | 4 |\n|---|---|---|\n| 2 | About | 5 |\n"
          "| 10 | . Workout Programs | 30 |\n| II | . Equipment & Apparel | 34 |\n| ... | ... | ... |")
    out = C.clean_markdown_tables(md)
    assert "| 1. | Introduction | 4 |" in out and "| 11. | Equipment & Apparel | 34 |" in out
    assert "| 10. | Workout Programs | 30 |" in out and "..." not in out


def test_page_markdown_drops_picture_debris_keeps_logo_text():
    md = ("# **Calisthenics Training Guide**\n<!-- Start of picture text -->\n*<br>I<br>is<br>*\n<!-- End of picture text -->\n"
          "**- How to progress -**\n<!-- Start of picture text -->\nBY<br>CALISTHENICS FAMILY\n<!-- End of picture text -->\n")
    out = C.clean_page_markdown(md)
    assert "I is" not in out and "picture text" not in out
    assert "CALISTHENICS FAMILY" in out


# ---------------------------------------------------------------- structure
def _prov(n):
    return ProvenanceItem(page_no=n, bbox=BoundingBox(l=0, t=0, r=0, b=0), charspan=(0, 0))


def _table(doc, rows, page):
    cells = [TableCell(text=t, start_row_offset_idx=r, end_row_offset_idx=r + 1,
                       start_col_offset_idx=c, end_col_offset_idx=c + 1, column_header=(r == 0))
             for r, row in enumerate(rows) for c, t in enumerate(row)]
    return doc.add_table(data=TableData(num_rows=len(rows), num_cols=len(rows[0]), table_cells=cells), prov=_prov(page))


def _doc():
    d = DoclingDocument(name="t")
    H = lambda t, p, lvl=1: d.add_heading(text=t, level=lvl, prov=_prov(p))
    T = lambda t, p: d.add_text(label=DocItemLabel.TEXT, text=t, prov=_prov(p))
    H("9.4.2 Proteins", 26, 3); T("Proteins are the building blocks.", 26)
    H("Animal Protein", 27, 1)
    _table(d, [["Meat / Eggs", "Protein (per 100g)"], ["Beef", "24"]], 27)
    H("9.4.3 Fats", 27, 3); T("Fats are essential nutrients.", 27)
    H("9.8 Example Nutrition Plans", 29, 2)
    T("Day 1", 29); _table(d, [["Meal", "Consumption"], ["12:00 Breakfast", "Milk"]], 29)
    T("Day 2", 29); _table(d, [["Meal", "Consumption"], ["12:00 Breakfast", "Milk, Brinta"]], 29)
    H("10.1 The Beginner Program", 30, 2); T("Program text.", 30)
    H("Start Your Journey Now!", 30, 1); T("Use Code ‘BEGINNER25’ For 25% Off", 30)
    H("10.2 The Full Journey Program", 31, 2); T("Body of 10.2.", 31)
    H("> Beginner Calisthenics Program", 31, 1)
    H("Become a Master of Your Own Bodyweight", 32, 1); T("For us, it took a long time.", 32)
    T("Use Code ‘FULUOURIMEY25’ to Get 25% Off", 32)
    H("Get The Program", 32, 2)
    H("10.3 30 Day Fat-burn Program", 33, 2); T("Our 30 Day Fat Burn Program.", 33)
    H("Best,", 36, 2)
    return d


def _chunks(d):
    return list(HierarchicalChunker(serializer_provider=_MarkdownTableSerializerProvider()).chunk(d))


def test_pseudo_headings_are_demoted_and_levels_are_relative():
    d = _doc()
    _repair_pdf_headings(d)
    S.repair_pdf_structure(d, VOCAB)
    heads = {(t.text, t.level) for t in d.texts if t.label == DocItemLabel.SECTION_HEADER}
    texts = {t.text for t in d.texts if t.label == DocItemLabel.SECTION_HEADER}
    for junk in ("Start Your Journey Now!", "Beginner Calisthenics Program", "Get The Program", "Best,",
                 "Become a Master of Your Own Bodyweight"):
        assert junk not in texts, junk
    assert ("9.4.3 Fats", 3) in heads and ("10.3 30 Day Fat-burn Program", 2) in heads


def test_section_10_bodies_stay_under_their_own_headings():
    d = _doc()
    _repair_pdf_headings(d)
    S.repair_pdf_structure(d, VOCAB)
    by_text = {c.text.split("\n")[0][:20]: c.meta.headings for c in _chunks(d)}
    assert by_text["Body of 10.2."] == ["10.2 The Full Journey Program"]
    assert any(k.startswith("For us, it took") and h == ["10.2 The Full Journey Program"] for k, h in by_text.items())
    assert all("Start Your Journey" not in (h or [""])[-1] for h in by_text.values())


def test_day_labels_bind_to_their_tables_and_table_is_markdown():
    d = _doc()
    _repair_pdf_headings(d)
    S.repair_pdf_structure(d, VOCAB)
    tables = [c for c in _chunks(d) if "| Meal" in c.text]
    assert len(tables) == 2
    assert tables[0].text.startswith("Day 1") and tables[1].text.startswith("Day 2")
    assert "| 12:00 Breakfast | Milk, Brinta" in re.sub(r" +", " ", tables[1].text)
    assert "Meal, Consumption =" not in tables[1].text            # no triplet form
    assert tables[1].meta.headings == ["9.8 Example Nutrition Plans"]


def test_unnumbered_label_nests_under_last_numbered_heading():
    d = _doc()
    _repair_pdf_headings(d)
    S.repair_pdf_structure(d, VOCAB)
    animal = next(t for t in d.texts if t.text == "Animal Protein" or t.text.startswith("Animal Protein"))
    if animal.label == DocItemLabel.SECTION_HEADER:
        assert animal.level == 4            # one deeper than 9.4.2 (level 3)
    else:                                   # became the table caption
        assert animal.label == DocItemLabel.CAPTION


def test_promo_code_text_is_repaired_in_document():
    d = _doc()
    _repair_pdf_headings(d)
    S.repair_pdf_structure(d, VOCAB)
    all_text = " ".join(t.text for t in d.texts)
    assert "FULLJOURNEY25" in all_text and "FULUOURIMEY" not in all_text


def test_long_table_splits_on_row_boundaries_with_header_repeated():
    from docling_core.transforms.chunker.hybrid_chunker import HybridChunker as HC
    from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer

    class WordTokenizer(BaseTokenizer):          # offline stand-in: 1 token per word
        max_tokens: int = 40

        def count_tokens(self, text: str) -> int:
            return len(text.split())

        def get_max_tokens(self) -> int:
            return self.max_tokens

        def get_tokenizer(self):
            return lambda text: len(text.split())

    d = DoclingDocument(name="t")
    d.add_heading(text="9.4.1 Carbs", level=3, prov=_prov(1))
    _table(d, [["Product", "Carbs"]] + [[f"Item{i}", str(i)] for i in range(60)], 1)
    hc = HC(tokenizer=WordTokenizer(),
            serializer_provider=_MarkdownTableSerializerProvider(), repeat_table_header=True)
    chunks = list(hc.chunk(d))
    assert len(chunks) > 1
    for c in chunks:
        lines = [l for l in c.text.splitlines() if l.startswith("|")]
        assert lines[0].startswith("| Product")                      # header repeated
        assert all(l.count("|") == 3 for l in lines)                 # no row cut in half


# ---------------------------------------------------------------- real PDF (optional)
PDF = os.getenv("V57_TEST_PDF", "Calisthenics-Training-Guide-Calisthenics-Family.pdf")


@pytest.mark.skipif(not pathlib.Path(PDF).exists(), reason="sample PDF not present")
def test_real_pdf_pages_come_out_clean():
    import pymupdf
    import pymupdf4llm
    pdf = pymupdf.open(PDF)
    vocab = C.build_vocab(p.get_text() for p in pdf)
    pages = [pymupdf4llm.to_markdown(pdf, pages=[i], header=False, footer=False)
             for i in range(pdf.page_count)]
    pages = [C.clean_page_markdown(m, vocab) for m in C.strip_running_lines(pages)]
    joined = "\n".join(pages)
    assert not re.search(r"Calisthenics Family \| Calisthenics Training Guide", joined)
    assert not re.search(r"\S[ \t]+###", joined)               # no heading markup glued onto prose
    assert "**-**" not in joined and "https:/ /" not in joined and "<sup>" not in joined
    assert "7.5 Bodybuilding mind-set" in joined
    assert "https://calisthenics-family.com" in joined and "bmr-calculator" in joined
    assert "perlOOg" not in joined and "per 100g" in joined
    assert "I\nr\n/" not in joined and "picture text" not in joined
