from fastapi import APIRouter, File, HTTPException, UploadFile

from api.dependencies import uploader
from api.v1.endpoints.documents import index_document
from api.v1.endpoints.query import query_pipeline
from schemas import (
    FileIndexResponse,
    FileUploadItem,
    FileUploadResponse,
    QueryRequest,
    QueryResponse,
)

legacy_router = APIRouter(tags=["Legacy (v0.1/v0.3)"])


@legacy_router.post(
    "/upload",
    response_model=FileUploadResponse,
    deprecated=True,
    summary="[Legacy] Upload multiple files",
)
async def legacy_upload(files: list[UploadFile] = File(...)) -> FileUploadResponse:
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    uploaded = uploader.upload_files(files)
    return FileUploadResponse(
        message="Files uploaded successfully",
        count=len(uploaded),
        files=[
            FileUploadItem(
                file_id=item["file_id"],
                filename=item["filename"],
                size_bytes=item["size_bytes"],
            )
            for item in uploaded
        ],
    )


@legacy_router.post(
    "/chunk-and-embed/{file_id}",
    response_model=FileIndexResponse,
    deprecated=True,
    summary="[Legacy] Chunk and embed one uploaded file",
)
async def legacy_chunk_and_embed(file_id: str) -> FileIndexResponse:
    res = await index_document(document_id=file_id)
    return FileIndexResponse(
        file_id=res.document_id,
        filename=res.filename,
        collection=res.collection,
        total_chunks=res.total_chunks,
        indexed_chunks=res.indexed_chunks,
    )


@legacy_router.post(
    "/generate",
    response_model=QueryResponse,
    deprecated=True,
    summary="[Legacy] Answer question using indexed documents",
)
async def legacy_generate(request: QueryRequest) -> QueryResponse:
    return await query_pipeline(request=request)

