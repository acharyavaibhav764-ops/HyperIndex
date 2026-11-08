"""
Schemas for the document version-check endpoint (dry-run, no upload).

POST /api/v1/documents/check
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class DocumentCheckItem(BaseModel):
    """Result for a single file submitted to the check endpoint."""

    filename: str = Field(..., description="Original filename of the submitted file")
    size_bytes: int = Field(..., description="File size in bytes")
    sha256: str = Field(..., description="SHA-256 hex digest of the submitted file")

    # -------------------------------------------------------------------
    # Classification
    # -------------------------------------------------------------------
    status: str = Field(
        ...,
        description=(
            "Classification result:\n"
            "  'exact_duplicate'  – identical bytes already exist in the system\n"
            "  'new_version'      – near-duplicate of an existing document detected\n"
            "  'new_document'     – no match found; would be ingested as a fresh v1"
        ),
    )

    # -------------------------------------------------------------------
    # Matched document info (populated for exact_duplicate & new_version)
    # -------------------------------------------------------------------
    matched_document_id: str | None = Field(
        default=None,
        description="document_id of the existing document this file matched against",
    )
    matched_filename: str | None = Field(
        default=None,
        description="Filename of the matched existing document",
    )
    matched_product_id: str | None = Field(
        default=None,
        description="product_id of the matched existing document",
    )
    matched_doc_family_id: str | None = Field(
        default=None,
        description="doc_family_id of the matched document family",
    )
    matched_version: int | None = Field(
        default=None,
        description="Current version number of the matched document",
    )
    would_be_version: int | None = Field(
        default=None,
        description=(
            "Version number this file would receive if ingested:\n"
            "  matched_version + 1 for 'new_version', 1 for 'new_document', "
            "None for 'exact_duplicate'"
        ),
    )
    similarity_score: float | None = Field(
        default=None,
        description=(
            "Estimated Jaccard similarity against the matched document "
            "(None for exact_duplicate or new_document)"
        ),
    )
    storage_path_preview: str | None = Field(
        default=None,
        description=(
            "MinIO object key this file would be stored at if ingested "
            "(None for exact_duplicate)"
        ),
    )


class DocumentCheckResponse(BaseModel):
    """Response envelope for the check endpoint."""

    product_id: str = Field(..., description="product_id used for the check")
    count: int = Field(..., description="Number of files evaluated")
    results: list[DocumentCheckItem] = Field(..., description="Per-file classification results")
