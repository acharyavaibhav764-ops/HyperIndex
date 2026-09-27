from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.dependencies import chunker, embeddings, parser, retriever, uploader
from core.hasher import calculate_sha256
from db.models import Document, DocumentVersion
from db.session import get_db
from schemas.document import (
    DocumentIngestItem,
    DocumentIngestResponse,
)

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
    product_id: str = Form(..., min_length=1),
    db: Session = Depends(get_db),
) -> DocumentIngestResponse:
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    # Process sequentially so duplicates within this request see prior commits.
    ingested_items: list[DocumentIngestItem] = []
    for file in files:
        content = await file.read()
        await file.seek(0)
        file_hash = calculate_sha256(content)
        existing_version = db.scalar(
            select(DocumentVersion).where(DocumentVersion.sha256 == file_hash)
        )
        if existing_version is not None:
            existing_document = db.get(Document, existing_version.document_id)
            ingested_items.append(
                DocumentIngestItem(
                    document_id=existing_version.document_id,
                    product_id=existing_document.product_id if existing_document else product_id,
                    version_id=existing_version.version_id,
                    version_message=(
                        f"Duplicate file: this is already version "
                        f"{existing_version.version_number}"
                    ),
                    filename=file.filename or existing_version.filename,
                    size_bytes=len(content),
                    collection=retriever.collection_name,
                    total_chunks=0,
                    status="duplicate",
                )
            )
            continue

        item = uploader.upload_files([file])[0]
        doc_id = item["document_id"]
        filename = item["filename"]
        size_bytes = item["size_bytes"]

        # Download and parse text pages
        content, _ = uploader.download_file(doc_id)
        pages = parser.parse(content, filename)

        # Chunk text and attach metadata
        chunks, metadatas, chunk_ids = chunker.split(pages, doc_id, filename)

        # Generate vector embeddings
        vectors = embeddings.embed(chunks)

        # Persist to ChromaDB
        retriever.upsert(
            ids=chunk_ids,
            documents=chunks,
            metadatas=metadatas,
            embeddings=vectors,
        )

        version_id = str(uuid4())
        document = Document(
            document_id=doc_id,
            product_id=product_id,
            title=filename,
            current_version_id=version_id,
        )
        version = DocumentVersion(
            version_id=version_id,
            document_id=doc_id,
            version_number=1,
            filename=filename,
            sha256=file_hash,
            normalized_hash=None,
            object_key=doc_id,
            status="indexed",
        )
        db.add(document)
        db.add(version)
        db.commit()

        # Append to list of ingested items
        ingested_items.append(
            DocumentIngestItem(
                document_id=doc_id,
                product_id=product_id,
                version_id=version_id,
                version_message="You are uploading version 1",
                filename=filename,
                size_bytes=size_bytes,
                collection=retriever.collection_name,
                total_chunks=len(chunks),
                status="indexed",
            )
        )

    return DocumentIngestResponse(
        message="Documents processed successfully",
        count=len(ingested_items),
        documents=ingested_items,
    )

