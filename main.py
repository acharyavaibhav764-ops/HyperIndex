"""FastAPI application for uploading documents to MinIO."""

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from document import DocumentService, StorageError
from generation_service import GenerationError, GenerationService
from rag_service import RagService

app = FastAPI(title="API Services", version="1.0.0")
document_service = DocumentService()
rag_service = RagService(document_service)
generation_service = GenerationService(rag_service)


class GenerateRequest(BaseModel):
    """Represent a user's question for retrieval-augmented generation."""

    question: str


@app.on_event("startup")
async def startup_event() -> None:
    """Create the document bucket before accepting uploads."""
    document_service.ensure_bucket()


@app.post(
    "/upload",
    summary="Upload multiple documents",
    description=(
        "Upload one or more documents. In Swagger, choose a file and use "
        "'Add string item' to add more files before executing."
    ),
)
async def upload_documents(files: list[UploadFile] = File(...)) -> dict:
    """Upload one or more documents and return their stored object details."""
    if not files:
        raise HTTPException(status_code=400, detail="At least one document is required")

    try:
        uploaded_documents = document_service.upload_documents(files)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except StorageError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    return {
        "message": "Documents uploaded successfully",
        "count": len(uploaded_documents),
        "documents": uploaded_documents,
    }


@app.post(
    "/chunk-and-embed/{document_id}",
    summary="Chunk and embed one uploaded document",
    description="Read the uploaded document UUID from MinIO and persist its chunks in ChromaDB.",
)
async def chunk_and_embed(document_id: str) -> dict:
    """Chunk, embed, persist, and return every generated vector for verification."""
    try:
        return rag_service.process_document(document_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except StorageError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.post(
    "/generate",
    summary="Answer a question using indexed documents",
    description="Retrieve relevant ChromaDB chunks and answer with the local Ollama model.",
)
async def generate_answer(request: GenerateRequest) -> dict:
    """Return a grounded answer and source metadata."""
    try:
        return generation_service.answer_question(request.question)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except GenerationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error