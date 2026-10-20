"""v6 phase 1: `fitz` -> `import pymupdf` migration.

The behaviour tests run real PyMuPDF (no mocks).  They matter because pdf_cellmarks wraps its
PyMuPDF calls in ``except Exception`` and quietly returns a default: a wrong import would
silently switch the v5.9 tick/legend logic off instead of failing.  Every assertion below is on
a value the fallback path could not produce.
"""
import ast
import pathlib

import pymupdf

from parsers import pdf_cellmarks as cm
from parsers.pdf_router import PdfPageRouter

ROOT = pathlib.Path(__file__).resolve().parents[3]


def _png(shade=200, size=20) -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, size, size), False)
    pix.set_rect(pix.irect, (shade, shade, shade))
    return pix.tobytes("png")


# ----------------------------------------------------------------------------
# the library itself
# ----------------------------------------------------------------------------
def test_pymupdf_version_supports_the_new_import_name():
    major, minor, patch = (int(x) for x in pymupdf.__version__.split(".")[:3])
    assert (major, minor, patch) >= (1, 24, 3)       # `import pymupdf` was introduced in 1.24.3
    for name in ("open", "Rect", "csRGB", "Document", "Page"):
        assert hasattr(pymupdf, name), name


def test_requirements_pin_a_version_that_has_the_new_name():
    line = next(l for l in (ROOT / "requirements.txt").read_text().splitlines() if l.lower().startswith("pymupdf>="))
    assert line.strip() >= "pymupdf>=1.24.3"


# ----------------------------------------------------------------------------
# static: nothing in the app still imports or uses the old module name
# ----------------------------------------------------------------------------
def _app_py_files():
    skip = {"tests", ".venv", "venv", "__pycache__", "scratch", "chroma_data", "node_modules"}
    for p in ROOT.rglob("*.py"):
        if not skip.intersection(p.relative_to(ROOT).parts):
            yield p


def test_no_app_module_imports_or_references_fitz():
    offenders = []
    for path in _app_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "fitz" for a in node.names):
                offenders.append(f"{path.name}:{node.lineno} import fitz")
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "fitz":
                offenders.append(f"{path.name}:{node.lineno} from fitz")
            elif isinstance(node, ast.Name) and node.id == "fitz":
                offenders.append(f"{path.name}:{node.lineno} name fitz")
    assert offenders == []


def test_router_module_exposes_pymupdf_for_patching():
    import parsers.pdf_router as r
    assert r.pymupdf is pymupdf and not hasattr(r, "fitz")


# ----------------------------------------------------------------------------
# pdf_cellmarks: real pages, values the silent fallbacks cannot return
# ----------------------------------------------------------------------------
def _colour_page():
    pdf = pymupdf.open()
    page = pdf.new_page(width=300, height=200)
    page.draw_rect(pymupdf.Rect(20, 20, 60, 60), color=None, fill=(0.0, 0.7, 0.1))     # green
    page.draw_rect(pymupdf.Rect(120, 20, 160, 60), color=None, fill=(0.8, 0.1, 0.1))   # red
    page.insert_text((20, 120), "Hello cell", fontsize=12)
    page.insert_text((200, 40), "= available", fontsize=10)
    return page


def test_is_greenish_distinguishes_green_from_red():
    page = _colour_page()
    assert cm._is_greenish(page, 20, 20, 60, 60) is True
    assert cm._is_greenish(page, 120, 20, 160, 60) is False       # fallback would return True


def test_is_tick_colour_needs_mostly_green_ink():
    page = _colour_page()
    assert cm._is_tick_colour(page, 20, 20, 60, 60) is True       # fallback would return False
    assert cm._is_tick_colour(page, 120, 20, 160, 60) is False


def test_ocr_cell_reads_the_text_layer_of_the_clip():
    page = _colour_page()
    assert cm._ocr_cell(page, 10, 105, 120, 130) == "Hello cell"  # fallback would return ""


def test_legend_swatch_detects_the_equals_key_to_the_right():
    page = _colour_page()
    # swatch box ends at x=190; the word "=" starts right after it
    pdf = pymupdf.open()
    p2 = pdf.new_page(width=300, height=200)
    p2.insert_text((150, 60), "= available", fontsize=10)
    assert cm._is_legend_swatch(p2, (120, 40, 148, 64)) is True    # fallback would return False
    assert cm._is_legend_swatch(page, (120, 20, 160, 60)) is False


# ----------------------------------------------------------------------------
# pdf_router: real documents
# ----------------------------------------------------------------------------
def _three_page_pdf():
    pdf = pymupdf.open()
    for n in (1, 2, 3):
        body = f"Page {n} marker. " + "This is a body paragraph with several sentences. " * 6
        pdf.new_page(width=595, height=842).insert_textbox(pymupdf.Rect(72, 300, 520, 600), body, fontsize=11)
    return pdf


def test_single_page_bytes_extracts_exactly_that_page():
    data = PdfPageRouter._single_page_bytes(_three_page_pdf(), 1)
    out = pymupdf.open(stream=data, filetype="pdf")
    assert out.page_count == 1 and "Page 2 marker" in out[0].get_text()


def test_triage_text_image_and_table_pages():
    router = PdfPageRouter()
    pdf = pymupdf.open()
    text = pdf.new_page(width=595, height=842)
    text.insert_textbox(pymupdf.Rect(40, 40, 550, 800), "plain paragraph of text. " * 80, fontsize=10)
    assert router._triage_page(text) == ["text"]

    img = pdf.new_page(width=595, height=842)
    img.insert_image(pymupdf.Rect(100, 200, 400, 420), stream=_png())
    img.insert_text((50, 60), "tiny caption", fontsize=9)
    assert "image" in router._triage_page(img)

    grid = pdf.new_page(width=595, height=842)
    for i in range(4):                                  # a ruled 3x3 grid with text in each cell
        grid.draw_line((50, 100 + i * 40), (350, 100 + i * 40))
        grid.draw_line((50 + i * 100, 100), (50 + i * 100, 220))
    for r in range(3):
        for c in range(3):
            grid.insert_text((58 + c * 100, 125 + r * 40), f"r{r}c{c}", fontsize=9)
    assert "table" in router._triage_page(grid)


def test_page_markdown_uses_pymupdf4llm_on_a_real_page():
    md = PdfPageRouter._page_markdown(_three_page_pdf(), 2, use_ocr=False)
    assert "Page 3 marker" in md and "Page 1 marker" not in md
