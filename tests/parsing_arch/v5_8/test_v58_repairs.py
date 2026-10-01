"""v5.8 regression tests. Pure modules are loaded by path, so no Docling install is needed."""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cc = _load("core/chunk_cleanup.py", "chunk_cleanup")
pc = _load("parsers/pdf_cleanup.py", "pdf_cleanup_v58")


def test_strip_markup_removes_hashes_bold_italic():
    t = "a. ###\n### **3.2 Basics**\n**bold**\n*Use Code X*\n* real bullet\n6*7*8 and #1 tip"
    out = cc.strip_markup(t)
    assert "#" not in out.replace("#1", "") and "**" not in out
    assert "Use Code X" in out and "* real bullet" in out and "6*7*8" in out and "#1 tip" in out


def test_trailing_hash_token_stripped_by_cleanup():
    assert "###" not in pc.strip_markup("about calisthenics. ###")


def test_next_heading_tail_and_heading_only_chunk_dropped():
    chunks = [
        "WHAT IS\n3.1 Origins\nBody text.\n### **3.2 Basics**",
        "WHAT IS\n3.2 Basics\nWith the basics we mean push ups.",
        "MYTHS\n### **8.1 Can you?**",
        "MYTHS\n8.1 Can you?\nYes.",
        "Calisthenics Family",
    ]
    metas = [{"i": i} for i in range(len(chunks))]
    out, m = cc.postprocess_chunks(chunks, metas, drop_micro=True)
    assert out[0].endswith("Body text.") and len(out) == 3
    assert [x["i"] for x in m] == [0, 1, 3]
    assert len(cc.postprocess_chunks(chunks, metas, drop_micro=False)[0]) == 4


def test_table_row_equal_to_next_header_is_kept():
    chunks = ["H\n| a | b |\n| 1 | 2 |", "H\n| 1 | 2 |\n| 3 | 4 |"]
    out, _ = cc.postprocess_chunks(chunks, [{}, {}])
    assert out[0].endswith("| 1 | 2 |")


def test_two_column_contents_table():
    md = ("|I. Introduction|4|\n|---|---|\n|2 About Us|5|\n|3 What is It|7|\n|7. 10 Crucial Principles|18|\n"
          "|10. Workout Programs|30|\n|I I. Equipment & Apparel|34|\n|12. Words of Encouragement|36|")
    out = pc.clean_markdown_tables(md)
    assert "| 1. | Introduction | 4 |" in out and "| 7. | 10 Crucial Principles | 18 |" in out
    assert "| 11. | Equipment & Apparel | 34 |" in out and "| 12. | Words of Encouragement | 36 |" in out


def test_non_toc_two_column_table_untouched():
    md = "|Fish|Protein|\n|---|---|\n|Tuna|25|\n|Cod|18|\n|Eel|20|"
    assert "| Fish | Protein |" in pc.clean_markdown_tables(md)


def test_heading_number_repairs():
    assert pc.fix_heading_number("6.5. 1Chest Circuit") == "6.5.1 Chest Circuit"
    assert pc.fix_heading_number("9.4.2 Proteins") == "9.4.2 Proteins"
    seq = ["6.5 Circuit Training", "6.5.1 Chest Circuit", "6.2.2 Core Circuit", "7 Principles"]
    assert pc.repair_heading_sequence(seq)[2] == "6.5.2 Core Circuit"
    assert pc.repair_heading_sequence(["9.3 Calories", "9.4.1 Carbs"]) == ["9.3 Calories", "9.4.1 Carbs"]


def test_renumber_sequence():
    assert pc.renumber_sequence(["Day 7", "Day 2"]) == ["Day 1", "Day 2"]
    assert pc.renumber_sequence(["Day 3", "Day 4"]) == ["Day 3", "Day 4"]
    assert pc.renumber_sequence(["Day 7"]) == ["Day 7"]


def test_button_debris_is_noise_but_normal_text_is_not():
    assert pc.is_noise_paragraph("r ^ Start Now L J")
    assert not pc.is_noise_paragraph("Step 2 of 4")
    assert not pc.is_noise_paragraph("Day 1 - Skill")


def test_known_fix_timeline_heading():
    assert pc.apply_known_fixes("THEFULLJOURNEYTIMELINE") == "THE FULL JOURNEY TIMELINE"


def test_is_micro_label():
    assert cc.is_micro_label("Calisthenics Family")
    assert not cc.is_micro_label("10.2 The Full Journey")
    assert not cc.is_micro_label("Two\nlines")
