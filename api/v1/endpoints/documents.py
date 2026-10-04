from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from api.deps import get_ingestion_service
from schemas.document import DocumentIngestResponse
from services.ingestion_service import IngestionService

router = APIRouter(prefix="/documents", tags=["Documents"])


# POST /api/v1/documents/
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentIngestResponse,
    summary="Upload and ingest documents",
    description=(
        "Upload one or more documents, parse text, chunk, generate embeddings, "
        "and index them in ChromaDB synchronously."
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
