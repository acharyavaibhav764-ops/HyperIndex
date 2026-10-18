from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field
class DocumentDescription(BaseModel):
    document_id: str = Field(..., description="Unique document UUID")
    filename: str = Field(..., description="Original filename")
    product_id: str = Field(..., description="Product identifier tag")
    size_bytes: int = Field(..., description="File size in bytes")
    sha256: str = Field(..., description="SHA-256 fingerprint for deduplication")
    total_chunks: int = Field(..., description="Number of text chunks indexed in ChromaDB")
    status: str = Field(default="indexed", description="Indexing status")
    created_at: datetime = Field(..., description="Timestamp when document was ingested")


class GetDocumentsResponse(BaseModel):
    total_count: int = Field(..., description="Total documents matching query filters")
    limit: int = Field(..., description="Maximum items returned")
    skip: int = Field(..., description="Items skipped")
    documents: list[DocumentDescription] = Field(..., description="List of matching documents")


class ChunkDescription(BaseModel):
    chunk_id: str = Field(..., description="Unique chunk vector ID in ChromaDB")
    chunk_index: int = Field(..., description="Index of the chunk in document")
    page: int | str = Field(..., description="Page number of origin")
    text: str = Field(..., description="Extracted text chunk content")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Full chunk metadata attributes")


class GetDocumentChunksResponse(BaseModel):
    document_id: str = Field(..., description="Unique document UUID")
    filename: str = Field(..., description="Original filename")
    total_chunks: int = Field(..., description="Total chunks in ChromaDB for this document")
    chunks: list[ChunkDescription] = Field(..., description="Retrieved chunks")


class UpdateDocumentRequest(BaseModel):
    product_id: str = Field(..., min_length=1, description="New product identifier tag")


class DeleteDocumentResponse(BaseModel):
    document_id: str = Field(..., description="Document ID that was deleted")
    status: str = Field(default="deleted", description="Deletion status")
    deleted_chunks: int = Field(..., description="Number of vectors removed from ChromaDB")
    database_removed: bool = Field(default=True, description="Whether SQL record was deleted")
    storage_removed: bool = Field(default=True, description="Whether raw MinIO binary was deleted")
