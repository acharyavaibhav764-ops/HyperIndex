from pydantic import BaseModel, Field


class DocumentUploadItem(BaseModel):
    document_id: str = Field(..., description="Unique document identifier in object storage")
    filename: str = Field(..., description="Original filename")
    size_bytes: int = Field(..., description="File size in bytes")


class DocumentUploadResponse(BaseModel):
    message: str
    count: int
    documents: list[DocumentUploadItem]


class ChunkItem(BaseModel):
    chunk_id: str
    text: str
    metadata: dict


class DocumentIndexResponse(BaseModel):
    document_id: str
    filename: str
    collection: str
    total_chunks: int
    indexed_chunks: int

