import io
import logging
import re
from docling.datamodel.base_models import InputFormat
from docling.document_converter import (
    DocumentConverter,
    WordFormatOption,
    PowerpointFormatOption,
)
from docling_core.types.doc import DocItemLabel, DoclingDocument, SectionHeaderItem
from docling_core.types.io import DocumentStream

from .base import BaseParser
from core import pipeline_config

# Backward compatibility alias
settings = pipeline_config.pipeline_settings
parser_settings = pipeline_config.pipeline_settings

logger = logging.getLogger(__name__)


def _build_vlm_converter() -> DocumentConverter:
    """Configure vanilla DocumentConverter class to handle and provide pictures with text descriptions and hence return docx and pptx converter."""

    from docling.datamodel.pipeline_options import (
        ConvertPipelineOptions,
        PictureDescriptionVlmEngineOptions,
    )

    # Configure a VLM engine class using existing presets
    try:
        picture_opts = PictureDescriptionVlmEngineOptions.from_preset(
            pipeline_config.pipeline_settings.picture_description_preset
        )
    except Exception:
        logger.warning(
            "Preset %r not found; falling back to 'smolvlm'.",
            pipeline_config.pipeline_settings.picture_description_preset,
        )
        picture_opts = PictureDescriptionVlmEngineOptions.from_preset("smolvlm")

    # Update system prompt for the VLM engine
    if pipeline_config.pipeline_settings.picture_description_prompt:
        picture_opts = picture_opts.model_copy(
            update={"prompt": pipeline_config.pipeline_settings.picture_description_prompt}
        )

    # Store the VLM engine configuration in pipeline_options
    pipeline_options = ConvertPipelineOptions(
        do_picture_classification=True,
        do_picture_description=True,
        picture_description_options=picture_opts,
    )

    # Return DocumentConverter with options
    return DocumentConverter(
        format_options={
            InputFormat.DOCX: WordFormatOption(pipeline_options=pipeline_options),
            InputFormat.PPTX: PowerpointFormatOption(pipeline_options=pipeline_options),
        }
    )


def _inject_picture_descriptions(doc: DoclingDocument) -> None:
    """Inject picture descriptions into the DoclingDocument."""

    from docling_core.types.doc import PictureDescriptionData

    # Filter out empty picture descriptions
    for picture in doc.pictures:
        meta_desc = getattr(picture.meta, "description", None)
        raw_text = getattr(meta_desc, "text", "") or ""
        cleaned = re.sub(r"<!--\s*([a-zA-Z_]+)\s*-->", "", raw_text)
        cleaned = re.sub(r"<!--.*?-->", "", cleaned, flags=re.DOTALL)
        cleaned = re.sub(r"<[a-z_]{0,40}\s*$", "", cleaned).strip()
        if not cleaned:
            continue

        tagged_description = f"[Figure description] {cleaned}"

        # 1. Update picture.meta.description and picture.annotations with cleaned text
        if meta_desc is not None:
            meta_desc.text = tagged_description

        if getattr(picture, "annotations", None):
            for ann in picture.annotations:
                if isinstance(ann, PictureDescriptionData):
                    ann.text = tagged_description

        # Inject cleaned text as caption linked to picture
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
    """Promote plain text headings to actual headings by changing label in DoclingDocument."""

    # Find the first item of a DoclingDocument in each page
    page_first_items = {}
    for item in doc.texts:
        if getattr(item, "prov", None):
            p_no = item.prov[0].page_no
            if p_no not in page_first_items:
                page_first_items[p_no] = item


    for i, item in enumerate(doc.texts):
        p_no = item.prov[0].page_no if getattr(item, "prov", None) else None

        # For every text in doc, check if it is the first item of the page
        if p_no and page_first_items.get(p_no) is item:
            if item.label == DocItemLabel.PARAGRAPH:
                text = getattr(item, "text", "").strip()

                # If there is sub 100 character text, labelled as paragraph and not terminating with "." promote it to section header
                if text and len(text) < 100 and not text.endswith("."):
                    dump = item.model_dump()
                    dump["label"] = DocItemLabel.SECTION_HEADER
                    new_item = SectionHeaderItem(**dump)
                    doc.texts[i] = new_item


class DoclingParser(BaseParser):
    """
    Parse Microsoft Office documents (Word and PowerPoint) and PDF documents into a DoclingDocument.
    
    Attributes:
        _converter: DocumentConverter class from docling for text purely
        _converter_vlm: DocumentConverter class which also supports image descriptions with VLM

    Methods:
        can_handle()
        parse()

        _convert_with_vlm()
    """

    SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".docx", ".pptx", ".pdf"})

    def __init__(self) -> None:
        """Instantiate shared DocumentConverter(s) for Office & PDF formats."""

        self._converter: DocumentConverter | None = None # Initially None to prevent startup delay
        self._converter_vlm: DocumentConverter | None = None # Initially None due to heavyness of VLMs


    # BASE PARSER INSTANCE

    def can_handle(self, ext: str) -> bool:
        """Return True for .docx, .pptx, and .pdf extensions."""

        return ext.lower() in self.SUPPORTED_EXTENSIONS

    def parse(self, file_bytes: bytes, filename: str, **kwargs) -> DoclingDocument:
        """Convert raw file bytes to a DoclingDocument."""

        stream = DocumentStream(name=filename, stream=io.BytesIO(file_bytes))

        # Convert with VLM only if picture description enabled and supported
        if pipeline_config.pipeline_settings.enable_picture_description and not filename.lower().endswith(".pdf"):
            doc = self._convert_with_vlm(stream, filename)
        else:
            if self._converter is None:
                self._converter = DocumentConverter()
            result = self._converter.convert(stream)
            doc = result.document

        # Handle plain text headings in the DoclingDocument
        if filename.lower().endswith(".pptx"):
            _promote_pptx_pseudo_headings(doc)

        return doc


    # PRIVATE HELPERS

    def _convert_with_vlm(self, stream: DocumentStream, filename: str) -> DoclingDocument:
        """Run conversion with VLM picture description, falling back on error."""

        # Lazy build the VLM converter whenever required
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

            # Store picture data
            result = self._converter_vlm.convert(stream)
            doc = result.document
            _inject_picture_descriptions(doc)
            return doc
        except Exception as exc:
            logger.warning(
                "VLM conversion failed for %s: %s. Retrying without picture description.",
                filename,
                exc,
            )

            # Fallback text only parser in case of VLM failure
            fallback_stream = DocumentStream(
                name=filename, stream=io.BytesIO(stream.stream.getvalue())
            )
            if self._converter is None:
                self._converter = DocumentConverter()
            result = self._converter.convert(fallback_stream)
            return result.document
