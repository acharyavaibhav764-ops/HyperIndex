from pydantic import BaseModel, Field


class DocumentIngestItem(BaseModel):
    document_id: str = Field(..., description="Unique document identifier in object storage")
    product_id: str = Field(default="", description="Product identifier selected for this upload")
    filename: str = Field(..., description="Original filename")
    size_bytes: int = Field(..., description="File size in bytes")
    collection: str = Field(..., description="Qdrant collection name")
    total_chunks: int = Field(..., description="Number of chunks generated and indexed")
    status: str = Field(
        default="indexed",
        description="Ingestion status: 'indexed', 'new_version', or 'duplicate'",
    )

    # Versioning fields
    version: int = Field(default=1, description="Version number assigned to this document")
    doc_family_id: str = Field(default="", description="Stable family ID grouping all versions of this document")
    parent_id: str | None = Field(default=None, description="document_id of the previous version, if any")
    storage_path: str = Field(default="", description="Hierarchical MinIO object key")
    similarity_score: float | None = Field(
        default=None,
        description="Jaccard similarity score against the matched parent version (None for new families or exact duplicates)",
    )


class DocumentIngestResponse(BaseModel):
    message: str
    count: int
    documents: list[DocumentIngestItem]
