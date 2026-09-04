
"""FastAPI application for document upload and metadata retrieval."""

from fastapi import FastAPI, UploadFile, File, HTTPException
from minio_client import (
    StorageError,
    create_bucket,
    get_document_metadata,
    upload_to_minio,
)

app = FastAPI()
BUCKET_NAME = "honeywell-documents"

@app.on_event("startup")
async def startup_event():
    """Ensure the document bucket exists before serving requests."""
    create_bucket(BUCKET_NAME)



@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    """Upload a document and return its original filename."""

    try:
        upload_to_minio(file, BUCKET_NAME)
        return {"message": "Upload successful", "filename": file.filename}
    except StorageError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

@app.get("/metadata/{filename}")
async def get_doc_metadata(filename: str, bucket_name: str = BUCKET_NAME):
    """Return object metadata for a document in the configured bucket."""

    try:
        return get_document_metadata(bucket_name, filename)
    except StorageError as error:
        status_code = 404 if error.not_found else 500
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    
