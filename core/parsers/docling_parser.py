import io
import logging
from docling.datamodel.base_models import InputFormat
from docling.document_converter import (
    DocumentConverter,
    WordFormatOption,
    PowerpointFormatOption,
)
from docling_core.types.doc import DocItemLabel, DoclingDocument
from docling_core.types.io import DocumentStream

from config import settings
from .base import BaseParser

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
            settings.picture_description_preset
        )
    except Exception:
        logger.warning(
            "Preset %r not found; falling back to 'smolvlm'.",
            settings.picture_description_preset,
        )
        picture_opts = PictureDescriptionVlmEngineOptions.from_preset("smolvlm")

    # Update system prompt for the VLM engine
    if settings.picture_description_prompt:
        picture_opts = picture_opts.model_copy(
            update={"prompt": settings.picture_description_prompt}
        )

    # Store the VLM engine configuration in pipeline_options
    pipeline_options = ConvertPipelineOptions(
        do_picture_classification=True,
        do_picture_description=True,
        picture_description_options=picture_opts,
    )

    # Update the vanilla document converter with the VLM engine config
    return DocumentConverter(
        format_options={
            InputFormat.DOCX: WordFormatOption(pipeline_options=pipeline_options),
            InputFormat.PPTX: PowerpointFormatOption(pipeline_options=pipeline_options),
        }
    )


def _inject_picture_descriptions(doc: DoclingDocument) -> None:
    """Inject picture descriptions from doc.pictures into the text stream of the docling document."""

    import re
    from docling_core.types.doc import PictureDescriptionData

    for picture in doc.pictures:

        # Determine raw description from either picture.meta.description or picture.annotations
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

        # Strip tokens like <end_of_utterance>
        cleaned = re.sub(r"<[a-z_]{1,40}>", "", raw_text)
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


class DoclingParser(BaseParser):
    """Parse Microsoft Office documents (Word and PowerPoint) into a DoclingDocument`."""

    SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".docx", ".pptx"})

    def __init__(self) -> None:
        """Instantiate shared DocumentConverter(s) for Office formats."""

        self._converter = DocumentConverter()
        self._converter_vlm: DocumentConverter | None = None # Initially None due to heavyness of VLMs


    # BASE PARSER INSTANCE

    def can_handle(self, ext: str) -> bool:
        """Return True for .docx and .pptx extensions."""

        return ext.lower() in self.SUPPORTED_EXTENSIONS

    def parse(self, file_bytes: bytes, filename: str, **kwargs) -> DoclingDocument:
        """Convert raw Office file bytes to a DoclingDocument."""

        stream = DocumentStream(name=filename, stream=io.BytesIO(file_bytes))

        # Convert with VLM only if picture description enabled
        if settings.enable_picture_description:
            doc = self._convert_with_vlm(stream, filename)
        else:
            result = self._converter.convert(stream)
            doc = result.document

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
            result = self._converter.convert(fallback_stream)
            return result.document
