from __future__ import annotations

import logging
import re
import zlib
from typing import TYPE_CHECKING

from docling_core.types.doc import DocItemLabel, PictureDescriptionData

if TYPE_CHECKING:
    from docling_core.types.doc import DoclingDocument, PictureItem

logger = logging.getLogger(__name__)

_GENERIC_RE = re.compile(r"^In this (image|picture|diagram|figure)\b", re.I)
_ZLIB_RATIO_MIN = 0.35
_NGRAM_REPEATS = 3


def _zlib_ratio(text: str) -> float:
    raw = text.encode("utf-8")
    return len(zlib.compress(raw)) / len(raw) if raw else 1.0


def _has_repeated_ngram(text: str, n: int = 4) -> bool:
    """Check for pathological repetitive n-grams in captions."""
    
    words = text.split()
    if len(words) < n:
        return False
    grams: dict[tuple[str, ...], int] = {}
    for i in range(len(words) - n + 1):
        g = tuple(words[i:i + n])
        grams[g] = grams.get(g, 0) + 1
    return any(c >= _NGRAM_REPEATS for c in grams.values())


def inject_figure_cards(doc: DoclingDocument) -> None:
    """
    Ensure picture elements in DoclingDocument have clean, deduplicated captions
    without repeating hallucinated phrases.
    """
    
    for pic in doc.pictures:
        # Check meta.description
        desc = getattr(getattr(pic, "meta", None), "description", None)
        text = getattr(desc, "text", "") if desc else ""

        if text and (_has_repeated_ngram(text) or _zlib_ratio(text) < _ZLIB_RATIO_MIN):
            desc.text = ""

        # Check annotations (PictureDescriptionData)
        if getattr(pic, "annotations", None):
            for ann in pic.annotations:
                if isinstance(ann, PictureDescriptionData) and getattr(ann, "text", None):
                    if _has_repeated_ngram(ann.text) or _zlib_ratio(ann.text) < _ZLIB_RATIO_MIN:
                        ann.text = ""
