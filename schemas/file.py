from pydantic import BaseModel, Field


class FileUploadItem(BaseModel):
    file_id: str = Field(..., description="Unique file identifier in object storage")
    filename: str = Field(..., description="Original filename")
    size_bytes: int = Field(..., description="File size in bytes")


class FileUploadResponse(BaseModel):
    message: str
    count: int
    files: list[FileUploadItem]


class ChunkItem(BaseModel):
    chunk_id: str
    text: str
    metadata: dict


class FileIndexResponse(BaseModel):
    file_id: str
    filename: str
    collection: str
    total_chunks: int
    indexed_chunks: int
