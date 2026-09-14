from fastapi import APIRouter, File, HTTPException, UploadFile, status

from api.dependencies import chunker, embeddings, parser, retriever, uploader
from schemas.document import (
    DocumentIndexResponse,
    DocumentUploadItem,
    DocumentUploadResponse,
)

router = APIRouter(prefix="/documents", tags=["Documents"])

# POST /api/v1/documents
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentUploadResponse,
    summary="Upload multiple documents",
    description=(
        "Upload one or more documents to object storage. "
        "In Swagger UI, choose a file and click the 'Add string item' button below it "
        "to add more files before clicking Execute."
    ),
)
async def upload_documents(
    files: list[UploadFile] = File(...),
) -> DocumentUploadResponse:
    """Takes a list of files to uploaded, upload to MinIO and return response"""
    
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    uploaded_documents = uploader.upload_files(files)

    return DocumentUploadResponse(
        message="Documents uploaded successfully",
        count=len(uploaded_documents),
        documents=[
            DocumentUploadItem(
                document_id=item["document_id"],
                filename=item["filename"],
                size_bytes=item["size_bytes"],
            )
            for item in uploaded_documents
        ],
    )

# POST api/v1/documents/{document_id}/index
@router.post(
    "/{document_id}/index",
    response_model=DocumentIndexResponse,
    summary="Parse, chunk, embed and index a document",
    description="Download raw document from MinIO, split into chunks, generate embeddings, and persist in ChromaDB.",
)
async def index_document(document_id: str) -> DocumentIndexResponse:
    """Download raw file from MinIO and index it in ChromaDB, finally return success response"""

    # Download, parse, chunk and vectorize the file
    content, filename = uploader.download_file(document_id)
    pages = parser.parse(content, filename)
    chunks, metadatas, chunk_ids = chunker.split(pages, document_id, filename)

    vectors = embeddings.embed(chunks)
    retriever.upsert(
        ids=chunk_ids,
        documents=chunks,
        metadatas=metadatas,
        embeddings=vectors,
    )

    # Return response
    return DocumentIndexResponse(
        document_id=document_id,
        filename=filename,
        collection=retriever.collection_name,
        total_chunks=len(chunks),
        indexed_chunks=len(chunks),
    )

