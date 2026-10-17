"""v5.9.1 offline checks - pure Python + PyMuPDF, no Docling / Chroma / MinIO needed.

Run from the repo root:   python -m pytest tests/parsing_arch/v5_9/test_v5_9_1.py -q
Set V59_TEST_PDF to the path of 89470K2.GB0_V2.pdf to enable the real-PDF cellmarks check.
"""
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# ---------------------------------------------------------------------------
# Offline-safe imports: load modules directly to avoid core/__init__.py which
# auto-imports docling-dependent Chunker (not available in offline test envs).
# ---------------------------------------------------------------------------
_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))


def _load(rel: str):
    """Load a module from a repo-relative path, bypassing package __init__.py."""
    p = _REPO / rel
    spec = importlib.util.spec_from_file_location(p.stem, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_cc = _load("core/chunk_cleanup.py")
extract_doc_meta = _cc.extract_doc_meta
postprocess_chunks = _cc.postprocess_chunks
section_id = _cc.section_id

pdf_coverage = _load("parsers/pdf_coverage.py")

PDF = os.getenv("V59_TEST_PDF", "")



# ---------------------------------------------------------------- WP3: ticks are inline images
@pytest.mark.skipif(not PDF or not Path(PDF).exists(), reason="V59_TEST_PDF not set")
@pytest.mark.parametrize("page_no,expected_min", [(5, 15), (21, 11)])
def test_cellmarks_detects_inline_ticks(page_no, expected_min):
    import pymupdf
    pdf_cellmarks = _load("parsers/pdf_cellmarks.py")

    page = pymupdf.open(PDF)[page_no - 1]
    tables = page.find_tables().tables
    assert tables, "PyMuPDF found no table"
    tab = max(tables, key=lambda t: len(t.cells))
    grid = []
    for row in tab.rows:
        cells = []
        for ci, rect in enumerate(row.cells):
            r = rect or (0, 0, 0, 0)
            cells.append(SimpleNamespace(
                bbox=SimpleNamespace(l=r[0], t=r[1], r=r[2], b=r[3]),
                text=page.get_textbox(r).strip() if rect else "",
                start_col_offset_idx=ci))
        grid.append(cells)
    doc = SimpleNamespace(tables=[SimpleNamespace(data=SimpleNamespace(grid=grid))])
    pdf_cellmarks.inject_marks(doc, page, {"tick": "Yes", "dots": "No"}, repeat_min=3)
    yes = sum(1 for row in grid for c in row if c.text.startswith("Yes"))
    assert yes >= expected_min, f"p.{page_no}: only {yes} ticks became 'Yes'"


# ---------------------------------------------------------------- WP4: coverage
def test_coverage_restores_dropped_bold_word():
    md = "Features:\n- plug out call\n- presence 2\n- I/O Port"
    raw = "Features:\n- plug out call\n- No presence 2\n- I/O Port"
    out = pdf_coverage.check_page(md, raw, set())
    assert "- No presence 2" in out
    assert "[Recovered text]" not in out


def test_coverage_never_rewrites_table_rows():
    md = "| Fire class | V-0 |\n|---|---|"
    out = pdf_coverage.check_page(md, "Fire protection class\nV-O", set())
    assert out.startswith("| Fire class | V-0 |")


def test_coverage_skips_toc_page():
    raw = "\n".join(f"{i}.{j} Some section title ........ {i * 3 + j}" for i in range(1, 5) for j in range(1, 4))
    assert pdf_coverage.check_page("Content", raw, set()) == "Content"


# ---------------------------------------------------------------- WP1/WP2: chunk cleanup
def _m(ct="table", hp=None, pages=(30,)):
    return {"content_type": ct, "heading_path": hp or ["7. Specifications"], "page_numbers": list(pages)}


def test_separator_only_chunk_with_breadcrumb_is_dropped():
    ch = ["7. Specifications\n |\n|---|---|---|---|", "7. Specifications\n| a | b | c | d |"]
    out, _ = postprocess_chunks(ch, [_m(), _m()])
    assert len(out) == 1 and "a | b" in out[0]


def test_header_fragment_is_carried_to_headerless_table_chunks():
    ch = ["intro text here", "7. Specifications\n| Name | SEM+ | SEM | SCL",
          "7. Specifications\n |\n|---|---|---|---|",
          "7. Specifications\n| Idle | 60mA | 52mA | ? |", "7. Specifications\n| Max | 140mA | 130mA | ? |"]
    out, _ = postprocess_chunks(ch, [_m("text")] + [_m()] * 4)
    assert len(out) == 3
    for body in out[1:]:
        assert "| Name | SEM+ | SEM | SCL |" in body and "|---|---|---|---|" in body


def test_toc_chunks_are_tagged_and_merged():
    toc = [f"Content\n| 3.{i} | Section {i} ... | {10 + i} |\n| 3.{i}1 | Other {i} ... | {11 + i} |" for i in range(4)]
    ch = ["Intro paragraph about the device."] + toc + ["1. General\nBody text of the real section."]
    ms = [_m("text", ["Intro"], (1,))] + [_m("table", ["Content"], (3,))] * 4 + [_m("text", ["1. General"], (4,))]
    out, metas = postprocess_chunks(ch, ms)
    assert len(out) == 3 and metas[1]["content_type"] == "toc"
    assert "..." not in out[1] and "3.2 Section 2" in out[1]


# ---------------------------------------------------------------- WP6
def test_section_id_uses_closest_numbered_heading():
    assert section_id(28, ["5. Notes", "1.2 Separate cancel push-button for bed"]) == "p28:1.2"
    assert section_id(18, ["3 Electrical connection", "3.9 Factory setting", "Profile 2:"]) == "p18:3.9"
    assert section_id(1, ["Titel"]) == "p1" and section_id(None, []) == ""


@pytest.mark.parametrize("text", ["89470K2.GB0_V2\n11.2020", "Installation Instruction\n89470K2.GB0\nV2 11.2020"])
def test_doc_meta_from_raw_and_docling_text(text):
    assert extract_doc_meta([text]) == {"doc_number": "89470K2.GB0", "doc_version": "V2", "doc_date": "11.2020"}


def test_doc_meta_ignores_system_software_versions():
    assert extract_doc_meta(["needs system software V05.xx and V12.xx"])["doc_version"] == ""
