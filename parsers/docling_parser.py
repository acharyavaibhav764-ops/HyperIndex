"""
parsers/docling_parser.py — DoclingParser for .docx and .pptx files.

Wraps Docling's DocumentConverter with in-memory DocumentStream.
Optional SmolVLM picture description (ENABLE_PICTURE_DESCRIPTION=true).
Docling issue #1226 workaround: injects descriptions as CAPTION text items.
"""
import io
import logging

from docling.datamodel.base_models import InputFormat
from docling.document_converter import (
    DocumentConverter,
    WordFormatOption,
    PowerpointFormatOption,
    PdfFormatOption,
)
from docling_core.types.doc import DocItemLabel, DoclingDocument, SectionHeaderItem
from docling_core.types.io import DocumentStream

from config import settings
from .base import BaseParser

logger = logging.getLogger(__name__)


def _build_text_layer_converter() -> DocumentConverter:
    """PDF converter that trusts the embedded text layer (no OCR)."""
    from docling.datamodel.pipeline_options import PdfPipelineOptions

    opts = PdfPipelineOptions(do_ocr=False, do_table_structure=True)
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )


def _build_vlm_converter(do_ocr: bool = True) -> DocumentConverter:
    """Build a DocumentConverter with VLM picture description enabled.

    Falls back to plain converter if picture description is disabled.
    """
    from docling.datamodel.pipeline_options import (
        ConvertPipelineOptions,
        PdfPipelineOptions,
        PictureDescriptionVlmEngineOptions,
    )

    # Honour opt-out flag for PDF callers too.
    if not settings.enable_picture_description:
        return DocumentConverter() if do_ocr else _build_text_layer_converter()

    try:
        picture_opts = PictureDescriptionVlmEngineOptions.from_preset(
            settings.picture_description_preset
        )
    except Exception:
        logger.warning(
            "Preset %r not found; falling back to 'smolvlm'.",
            settings.picture_description_preset,
        )
        picture_opts = PictureDescriptionVlmEngineOptions.from_preset("smolvlm")

    if settings.picture_description_prompt:
        picture_opts = picture_opts.model_copy(
            update={"prompt": settings.picture_description_prompt}
        )

    # DOCX/PPTX generic pipeline options
    pipeline_options = ConvertPipelineOptions(
        do_picture_classification=True,
        do_picture_description=True,
        picture_description_options=picture_opts,
    )

    # PDF needs PdfPipelineOptions with generate_page_images for VLM.
    pdf_pipeline_options = PdfPipelineOptions(
        do_ocr=do_ocr,
        do_picture_classification=True,
        do_picture_description=True,
        picture_description_options=picture_opts,
        generate_page_images=True,
    )

    return DocumentConverter(
        format_options={
            InputFormat.DOCX: WordFormatOption(pipeline_options=pipeline_options),
            InputFormat.PPTX: PowerpointFormatOption(pipeline_options=pipeline_options),
            InputFormat.PDF:  PdfFormatOption(pipeline_options=pdf_pipeline_options),
        }
    )


def _inject_picture_descriptions(doc: DoclingDocument) -> None:
    """Inject VLM picture descriptions into doc.texts as CAPTION items.

    Cleans token artifacts and prefixes with '[Figure description]'.
    Workaround for Docling issue #1226.
    """
    import re
    from docling_core.types.doc import PictureDescriptionData

    for picture in doc.pictures:
        # Determine raw description from either picture.meta.description or annotations
        raw_text = ""
        meta_desc = getattr(getattr(picture, "meta", None), "description", None)
        if meta_desc and getattr(meta_desc, "text", None):
            raw_text = meta_desc.text
        elif getattr(picture, "annotations", None):
            for ann in picture.annotations:
                if isinstance(ann, PictureDescriptionData) and getattr(ann, "text", None):
                    raw_text = ann.text
                    break

        if not raw_text:
            continue

        # Strip complete tokens like <end_of_utterance>
        cleaned = re.sub(r"<[a-z_]{1,40}>", "", raw_text)
        # Strip dangling/unclosed token at end of string (e.g. <end_of_utteranc)
        cleaned = re.sub(r"<[a-z_]{0,40}\s*$", "", cleaned).strip()
        if not cleaned:
            continue

        tagged_description = f"[Figure description] {cleaned}"

        # 1. Update canonical picture.meta.description so HybridChunker picks it up
        if meta_desc is not None:
            meta_desc.text = tagged_description

        # 2. Update deprecated picture.annotations
        if getattr(picture, "annotations", None):
            for ann in picture.annotations:
                if isinstance(ann, PictureDescriptionData):
                    ann.text = tagged_description

        # 3. Inject CAPTION TextItem into doc
        try:
            doc.add_text(
                label=DocItemLabel.CAPTION,
                text=tagged_description,
                parent=picture,
            )
        except Exception as exc:
            logger.warning(
                f"Picture description failed for {picture.self_ref}: {exc}"
            )


def _promote_pptx_pseudo_headings(doc: DoclingDocument) -> None:
    """Promote short first-on-slide paragraphs to SECTION_HEADER for PPTX."""
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


class DoclingParser(BaseParser):
    """Parse .docx and .pptx files into DoclingDocument via Docling.

    Uses in-memory DocumentStream (no temp files). Optional VLM picture description.
    """

    SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".docx", ".pptx"})

    def __init__(self) -> None:
        """Lazy-init converters: plain (_converter) and VLM (_converter_vlm)."""
        self._converter: DocumentConverter | None = None
        self._converter_vlm: DocumentConverter | None = None

    # ------------------------------------------------------------------
    # BaseParser interface
    # ------------------------------------------------------------------

    def can_handle(self, ext: str) -> bool:
        """Return True for .docx and .pptx."""
        return ext.lower() in self.SUPPORTED_EXTENSIONS

    def parse(self, file_bytes: bytes, filename: str, **kwargs) -> DoclingDocument:
        """Convert raw Office file bytes to DoclingDocument.

        Uses VLM converter if picture description enabled, with crash-guard fallback.
        """
        stream = DocumentStream(name=filename, stream=io.BytesIO(file_bytes))

        if settings.enable_picture_description:
            doc = self._convert_with_vlm(stream, filename)
        else:
            if self._converter is None:
                self._converter = DocumentConverter()
            result = self._converter.convert(stream)
            doc = result.document

        if filename.lower().endswith(".pptx"):
            _promote_pptx_pseudo_headings(doc)

        return doc

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _convert_with_vlm(
        self, stream: DocumentStream, filename: str
    ) -> DoclingDocument:
        """VLM conversion with crash-guard fallback to plain converter."""
        # Lazy-init the VLM converter — only built if picture description is enabled
        if self._converter_vlm is None:
            try:
                self._converter_vlm = _build_vlm_converter()
            except Exception as exc:
                logger.warning(
                    "Failed to build VLM converter for %s: %s. "
                    "Falling back to plain conversion.",
                    filename,
                    exc,
                )
                if self._converter is None:
                    self._converter = DocumentConverter()
                result = self._converter.convert(stream)
                return result.document

        try:
            result = self._converter_vlm.convert(stream)
            doc = result.document
            # Inject VLM descriptions into the text stream (Docling issue #1226)
            _inject_picture_descriptions(doc)
            return doc
        except Exception as exc:
            logger.warning(
                "VLM conversion failed for %s: %s. Retrying without picture description.",
                filename,
                exc,
            )
            # Re-wrap bytes for the fallback (the stream may already be exhausted)
            fallback_stream = DocumentStream(
                name=filename, stream=io.BytesIO(stream.stream.getvalue())
            )
            if self._converter is None:
                self._converter = DocumentConverter()
            result = self._converter.convert(fallback_stream)
            return result.document
