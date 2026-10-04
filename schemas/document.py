from pydantic import BaseModel, Field


class DocumentIngestItem(BaseModel):
    document_id: str = Field(..., description="Unique document identifier in object storage")
    product_id: str = Field(default="", description="Product identifier selected for this upload")
    version_id: str | None = Field(None, description="Metadata version identifier")
    version_message: str = Field(
        default="You are uploading version 1", description="Human-readable version information"
    )
    filename: str = Field(..., description="Original filename")
    size_bytes: int = Field(..., description="File size in bytes")
    collection: str = Field(..., description="ChromaDB collection name")
    total_chunks: int = Field(..., description="Number of chunks generated and indexed")
    status: str = Field(default="indexed", description="Ingestion status")


class DocumentIngestResponse(BaseModel):
    message: str
    count: int
    documents: list[DocumentIngestItem]

