from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from api.deps import get_document_service, get_ingestion_service
from schemas.document import (
    DeleteDocumentResponse,
    DocumentDescription,
    GetDocumentChunksResponse,
    GetDocumentsResponse,
    UpdateDocumentRequest,
)
from schemas.ingestion import DocumentIngestResponse
from services.document_service import DocumentService
from services.ingestion_service import IngestionService

router = APIRouter(prefix="/documents", tags=["Documents"])


# POST /api/v1/documents
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentIngestResponse,
    summary="Upload and ingest documents",
    description=(
        "Upload one or more documents, parse text, chunk, generate embeddings, "
        "and index them in Qdrant synchronously."
    ),
)
async def ingest_documents(
    files: list[UploadFile] = File(...),
    product_id: str = Form(default="default", min_length=1),
    service: IngestionService = Depends(get_ingestion_service),
) -> DocumentIngestResponse:
    
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    return service.ingest_files(files=files, product_id=product_id)


# GET /api/v1/documents
@router.get(
    "",
    response_model=GetDocumentsResponse,
    summary="List documents",
    description="Retrieve a paginated list of indexed documents with optional filtering.",
)
async def list_documents(
    product_id: Optional[str] = Query(None, description="Filter by exact product identifier"),
    name_search: Optional[str] = Query(None, description="Filter by substring match on filename"),
    status: Optional[str] = Query(None, description="Filter by document status"),
    uploaded_after: Optional[datetime] = Query(None, description="Filter documents uploaded after timestamp"),
    uploaded_before: Optional[datetime] = Query(None, description="Filter documents uploaded before timestamp"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of documents to return"),
    skip: int = Query(0, ge=0, description="Offset for pagination"),
    service: DocumentService = Depends(get_document_service),
) -> GetDocumentsResponse:
    
    return service.list_documents(
        product_id=product_id,
        name_search=name_search,
        status=status,
        uploaded_after=uploaded_after,
        uploaded_before=uploaded_before,
        limit=limit,
        skip=skip,
    )


# GET /api/v1/documents/{document_id}
@router.get(
    "/{document_id}",
    response_model=DocumentDescription,
    summary="Get document details",
    description="Retrieve detailed metadata and chunk counts for a specific document.",
)
async def get_document(
    document_id: str,
    service: DocumentService = Depends(get_document_service),
) -> DocumentDescription:
    
    return service.get_document(document_id=document_id)


# GET /api/v1/documents/{document_id}/chunks
@router.get(
    "/{document_id}/chunks",
    response_model=GetDocumentChunksResponse,
    summary="Get document chunks",
    description="Inspect extracted text chunks and chunk-level metadata stored in ChromaDB.",
)
async def get_document_chunks(
    document_id: str,
    limit: int = Query(50, ge=1, le=100, description="Maximum number of chunks to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    service: DocumentService = Depends(get_document_service),
) -> GetDocumentChunksResponse:
    
    return service.get_document_chunks(
        document_id=document_id,
        limit=limit,
        offset=offset,
    )


# PATCH /api/v1/documents/{document_id}
@router.patch(
    "/{document_id}",
    response_model=DocumentDescription,
    summary="Update document metadata",
    description="Update metadata attributes (such as product_id) across SQLite and all associated chunks in ChromaDB.",
)
async def update_document_metadata(
    document_id: str,
    payload: UpdateDocumentRequest,
    service: DocumentService = Depends(get_document_service),
) -> DocumentDescription:
    
    return service.update_document_metadata(
        document_id=document_id,
        product_id=payload.product_id,
    )


# DELETE /api/v1/documents/{document_id}
@router.delete(
    "/{document_id}",
    response_model=DeleteDocumentResponse,
    summary="Delete document",
    description="Irreversibly delete a document and cascade deletion across ChromaDB vectors, SQLite metadata, and MinIO storage.",
)
async def delete_document(
    document_id: str,
    service: DocumentService = Depends(get_document_service),
) -> DeleteDocumentResponse:
    
    return service.delete_document(document_id=document_id)
