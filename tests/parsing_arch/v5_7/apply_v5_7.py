#!/usr/bin/env python3
"""Apply the v5.7 patch to the project.  Usage:  python apply_v5_7.py [PROJECT_ROOT]

* copies files/pdf_cleanup.py and files/pdf_structure.py into parsers/
* copies tests/ into tests/parsing_arch/v5_7/
* edits config.py, parsers/docling_parser.py, parsers/pdf_router.py, core/chunker.py

Every edit is anchored on an exact string that must occur exactly once; if an anchor is
missing the script stops before writing anything.  Each file keeps its own line endings
(CRLF or LF).  Re-running on an already-patched tree is a no-op.
"""
import pathlib, shutil, sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else pathlib.Path.cwd()

EDITS = {}

EDITS["config.py"] = [(
'''    pdf_min_text_chars_for_text_route: int = int(os.getenv("PDF_MIN_TEXT_CHARS_FOR_TEXT_ROUTE", "800"))
''',
'''    pdf_min_text_chars_for_text_route: int = int(os.getenv("PDF_MIN_TEXT_CHARS_FOR_TEXT_ROUTE", "800"))
    # v5.7: a page whose text layer has at least this many characters is read from that
    # layer.  Docling's OCR is switched off for such pages (the PDF is often a full-page
    # bitmap with an embedded text layer; OCR over it replaced good text with garbage).
    pdf_text_layer_min_chars: int = int(os.getenv("PDF_TEXT_LAYER_MIN_CHARS", "40"))
    # v5.7 kill-switch: set PDF_ALLOW_OCR_ON_TEXT_PAGES=true to restore the v5.6 OCR behaviour.
    pdf_ocr_on_text_pages: bool = os.getenv("PDF_ALLOW_OCR_ON_TEXT_PAGES", "false").lower() == "true"
    # v5.7 kill-switch for the text/markdown clean-up + structure passes.
    pdf_v57_cleanup: bool = os.getenv("PDF_V57_CLEANUP", "true").lower() == "true"
''')]

EDITS["parsers/docling_parser.py"] = [
('''def _build_vlm_converter() -> DocumentConverter:''',
'''def _build_text_layer_converter() -> DocumentConverter:
    """v5.7: PDF converter that trusts the embedded text layer (no OCR).

    Table structure recognition stays on; only the OCR stage is removed.
    """
    from docling.datamodel.pipeline_options import PdfPipelineOptions

    opts = PdfPipelineOptions(do_ocr=False, do_table_structure=True)
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )


def _build_vlm_converter(do_ocr: bool = True) -> DocumentConverter:'''),
('''    if not settings.enable_picture_description:
        return DocumentConverter()
''',
'''    if not settings.enable_picture_description:
        return DocumentConverter() if do_ocr else _build_text_layer_converter()
'''),
('''    pdf_pipeline_options = PdfPipelineOptions(
        do_picture_classification=True,''',
'''    pdf_pipeline_options = PdfPipelineOptions(
        do_ocr=do_ocr,               # v5.7: False for pages that have a text layer
        do_picture_classification=True,'''),
]

EDITS["parsers/pdf_router.py"] = [
('''from .docling_parser import _build_vlm_converter, _inject_picture_descriptions
''',
'''from .docling_parser import (
    _build_text_layer_converter,
    _build_vlm_converter,
    _inject_picture_descriptions,
)
from . import pdf_cleanup, pdf_structure  # v5.7
'''),
('''        self._docling_converter: DocumentConverter | None = None
        self._vlm_converter: DocumentConverter | None = None
''',
'''        self._docling_converter: DocumentConverter | None = None
        self._vlm_converter: DocumentConverter | None = None
        # v5.7: OCR-free converters for pages that carry a text layer, and the
        # document vocabulary used by the text repair passes.
        self._text_layer_converter: DocumentConverter | None = None
        self._vlm_converter_text: DocumentConverter | None = None
        self._vocab = None
        self._ocr_pages: set[int] = set()
'''),
('''        pdf = fitz.open(stream=file_bytes, filetype="pdf")
        page_markdowns: list[str] = []

        for page in pdf:
            routes = self._triage_page(page)
            logger.debug("Page %d → routes=%s", page.number, routes)

            if routes == ["text"]:
                # Fast path: no tables or images — plain PyMuPDF4LLM extraction
                page_markdowns.append(pymupdf4llm.to_markdown(pdf, pages=[page.number]))
                continue
''',
'''        pdf = fitz.open(stream=file_bytes, filetype="pdf")
        page_markdowns: list[str] = []

        # v5.7: vocabulary from the PDF's own text layer + which pages have one.
        page_texts = [p.get_text() for p in pdf]
        self._vocab = pdf_cleanup.build_vocab(page_texts)
        self._ocr_pages = {
            i for i, t in enumerate(page_texts)
            if settings.pdf_ocr_on_text_pages or len(t.strip()) < settings.pdf_text_layer_min_chars
        }

        for page in pdf:
            routes = self._triage_page(page)
            logger.debug("Page %d → routes=%s", page.number, routes)
            use_ocr = page.number in self._ocr_pages

            if routes == ["text"]:
                # Fast path: no tables or images — plain PyMuPDF4LLM extraction
                page_markdowns.append(self._page_markdown(pdf, page.number, use_ocr))
                continue
'''),
('''            if "table" in routes:
                parts.append(self._docling_page(single_bytes, filename, page.number))
''',
'''            if "table" in routes:
                parts.append(self._docling_page(single_bytes, filename, page.number, use_ocr))
'''),
('''                    parts.append(
                        self._picture_descriptions_only(single_bytes, filename, page.number)
                    )
                else:
                    parts.append(self._smolvlm_page(single_bytes, filename, page.number))
''',
'''                    parts.append(
                        self._picture_descriptions_only(single_bytes, filename, page.number, use_ocr)
                    )
                else:
                    parts.append(self._smolvlm_page(single_bytes, filename, page.number, use_ocr))
'''),
('''    def _docling_full(self, file_bytes: bytes, filename: str) -> DoclingDocument:''',
'''    @staticmethod
    def _page_markdown(pdf: "fitz.Document", page_no: int, use_ocr: bool) -> str:
        """v5.7: pymupdf4llm markdown for one page, without running footers or OCR.

        ``header=False, footer=False`` drops the page-furniture blocks; ``use_ocr=False``
        keeps pymupdf4llm from re-OCRing a page that already has a text layer.  Older
        pymupdf4llm builds reject unknown keyword arguments, so we degrade gracefully.
        """
        attempts = (
            {"header": False, "footer": False, "use_ocr": use_ocr},
            {"header": False, "footer": False},
            {},
        )
        for kw in attempts:
            try:
                return pymupdf4llm.to_markdown(pdf, pages=[page_no], **kw)
            except TypeError:
                continue
        return pymupdf4llm.to_markdown(pdf, pages=[page_no])

    def _docling_full(self, file_bytes: bytes, filename: str, use_ocr: bool = True) -> DoclingDocument:'''),
('''        if self._docling_converter is None:
            self._docling_converter = DocumentConverter()
        stream = DocumentStream(name=filename, stream=BytesIO(file_bytes))
        result = self._docling_converter.convert(stream)
        return result.document

    def _docling_page(self, file_bytes: bytes, filename: str, page_no: int) -> str:''',
'''        if use_ocr:
            if self._docling_converter is None:
                self._docling_converter = DocumentConverter()
            converter = self._docling_converter
        else:                                    # v5.7: trust the text layer
            if self._text_layer_converter is None:
                self._text_layer_converter = _build_text_layer_converter()
            converter = self._text_layer_converter
        stream = DocumentStream(name=filename, stream=BytesIO(file_bytes))
        result = converter.convert(stream)
        return result.document

    def _vlm_for(self, use_ocr: bool) -> DocumentConverter:
        """v5.7: cached VLM converter, OCR-free when the page has a text layer."""
        if use_ocr:
            if self._vlm_converter is None:
                self._vlm_converter = _build_vlm_converter()
            return self._vlm_converter
        if self._vlm_converter_text is None:
            self._vlm_converter_text = _build_vlm_converter(do_ocr=False)
        return self._vlm_converter_text

    def _docling_page(self, file_bytes: bytes, filename: str, page_no: int, use_ocr: bool = True) -> str:'''),
('''        doc = self._docling_full(file_bytes, filename)
        return doc.export_to_markdown()

    def _smolvlm_page(self, file_bytes: bytes, filename: str, page_no: int) -> str:''',
'''        doc = self._docling_full(file_bytes, filename, use_ocr)
        return doc.export_to_markdown()

    def _smolvlm_page(self, file_bytes: bytes, filename: str, page_no: int, use_ocr: bool = True) -> str:'''),
('''            if self._vlm_converter is None:
                self._vlm_converter = _build_vlm_converter()
            stream = DocumentStream(name=filename, stream=BytesIO(file_bytes))
            doc = self._vlm_converter.convert(stream).document
            # v5.3 Fix 1''',
'''            stream = DocumentStream(name=filename, stream=BytesIO(file_bytes))
            doc = self._vlm_for(use_ocr).convert(stream).document
            # v5.3 Fix 1'''),
('''    def _picture_descriptions_only(
        self, file_bytes: bytes, filename: str, page_no: int
    ) -> str:''',
'''    def _picture_descriptions_only(
        self, file_bytes: bytes, filename: str, page_no: int, use_ocr: bool = True
    ) -> str:'''),
('''            if self._vlm_converter is None:
                self._vlm_converter = _build_vlm_converter()
            stream = DocumentStream(name=filename, stream=BytesIO(file_bytes))
            doc = self._vlm_converter.convert(stream).document
            _inject_picture_descriptions(doc)
            return "\\n\\n".join(''',
'''            stream = DocumentStream(name=filename, stream=BytesIO(file_bytes))
            doc = self._vlm_for(use_ocr).convert(stream).document
            _inject_picture_descriptions(doc)
            return "\\n\\n".join('''),
('''        combined = DoclingDocument(name=filename.rsplit(".", 1)[0])
        converter = DocumentConverter(allowed_formats=[InputFormat.MD])
''',
'''        combined = DoclingDocument(name=filename.rsplit(".", 1)[0])
        converter = DocumentConverter(allowed_formats=[InputFormat.MD])

        # v5.7: strip running footers, then clean each page's markdown (markup, glued
        # words, picture-text debris, table normalisation) before Docling parses it.
        if settings.pdf_v57_cleanup:
            page_markdowns = pdf_cleanup.strip_running_lines(page_markdowns)
            page_markdowns = [
                pdf_cleanup.clean_page_markdown(md, self._vocab) for md in page_markdowns
            ]
'''),
('''        _repair_pdf_headings(combined)

        # v5.4 Diagnostic A+B''',
'''        _repair_pdf_headings(combined)

        # v5.7: document-level structure repair (pseudo-headings, captions, levels).
        if settings.pdf_v57_cleanup:
            pdf_structure.repair_pdf_structure(combined, self._vocab)

        # v5.4 Diagnostic A+B'''),
]

EDITS["core/chunker.py"] = [
('''from docling.chunking import HybridChunker
from docling_core.types.doc import DoclingDocument
''',
'''from docling.chunking import HybridChunker
from docling_core.transforms.chunker.hierarchical_chunker import (
    ChunkingDocSerializer,
    ChunkingSerializerProvider,
)
from docling_core.transforms.serializer.base import BaseTableSerializer
from docling_core.transforms.serializer.markdown import MarkdownTableSerializer
from docling_core.types.doc import DoclingDocument
'''),
('''class Chunker:
    """
    Split extracted page text''',
'''class _MarkdownTableChunkSerializer(ChunkingDocSerializer):
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
    Split extracted page text'''),
('''        chunker = HybridChunker(tokenizer=settings.chunker_tokenizer)
''',
'''        chunker = HybridChunker(
            tokenizer=settings.chunker_tokenizer,
            serializer_provider=_MarkdownTableSerializerProvider(),  # v5.7
            repeat_table_header=True,
        )
'''),
]


def read(path):
    raw = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    return raw.replace("\r\n", "\n"), crlf


def main():
    staged = {}
    for rel, edits in EDITS.items():
        path = ROOT / rel
        if not path.exists():
            sys.exit(f"missing file: {path}  (pass the project root as the first argument)")
        text, crlf = read(path)
        for old, new in edits:
            if new in text:                       # already applied
                continue
            n = text.count(old)
            if n != 1:
                sys.exit(f"{rel}: anchor found {n}x (expected 1):\n{old[:120]!r}")
            text = text.replace(old, new)
        staged[path] = text.replace("\n", "\r\n") if crlf else text
    for path, text in staged.items():
        path.write_bytes(text.encode("utf-8"))
        print("patched", path.relative_to(ROOT))
    for name in ("pdf_cleanup.py", "pdf_structure.py"):
        shutil.copyfile(HERE / "files" / name, ROOT / "parsers" / name)
        print("wrote  ", f"parsers/{name}")
    tdst = ROOT / "tests" / "parsing_arch" / "v5_7"
    tdst.mkdir(parents=True, exist_ok=True)
    for f in (HERE / "tests").glob("*.py"):
        shutil.copyfile(f, tdst / f.name)
        print("wrote  ", f"tests/parsing_arch/v5_7/{f.name}")
    print("done")


if __name__ == "__main__":
    main()
