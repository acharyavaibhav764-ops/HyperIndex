from typing import Any
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from api.deps import (
    get_chunker,
    get_embeddings,
    get_ingestion_service,
    get_parser,
    get_retriever,
    get_uploader,
)
from db.session import get_db
from schemas.document import DocumentIngestResponse
from services.ingestion_service import IngestionService

router = APIRouter(prefix="/documents", tags=["Documents"])

# Legacy module-level hooks for test monkeypatching compatibility
uploader: Any = None
parser: Any = None
chunker: Any = None
embeddings: Any = None
retriever: Any = None


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
    service: IngestionService | Session | None = Depends(get_ingestion_service),
    db: Session | None = Depends(get_db),
) -> DocumentIngestResponse:
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    # Handle legacy positional call: ingest_documents(files, product_id, db)
    if isinstance(service, Session):
        db = service
        service = None

    # If module-level attributes were monkeypatched by tests, construct service with them
    if uploader is not None:
        service = IngestionService(
            uploader=uploader,
            parser=parser if parser is not None else get_parser(),
            chunker=chunker if chunker is not None else get_chunker(),
            embeddings=embeddings if embeddings is not None else get_embeddings(),
            retriever=retriever if retriever is not None else get_retriever(),
            db=db,
        )
    elif service is None:
        service = get_ingestion_service(db=db)
    elif db is not None and getattr(service, "db", None) is None:
        service.db = db

    return service.ingest_files(files=files, product_id=product_id)
