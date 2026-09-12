import os
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from core import (
    Chunker,
    Embeddings,
    GenerationError,
    Generator,
    Parser,
    Retriever,
    StorageError,
    Uploader,
)

app = FastAPI(title="Honeywell RAG", version="1.0.0")

# Initialize the 6 core pipeline components
uploader = Uploader()
parser = Parser()
chunker = Chunker()
embeddings = Embeddings()
retriever = Retriever(embeddings=embeddings)
generator = Generator()


# Schema for representing user query
class GenerateRequest(BaseModel):
    question: str


@app.on_event("startup")
async def startup_event() -> None:
    # Create bucket if not exists
    uploader.ensure_bucket()


@app.post(
    "/upload",
    summary="Upload multiple files",
    description=(
        "Upload one or more files. In Swagger, choose a file and use "
        "'Add string item' to add more files before executing."
    ),
)
async def upload_files(files: list[UploadFile] = File(...)) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    try:
        # Upload multiple files sequentially
        uploaded_files = uploader.upload_files(files)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except StorageError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    return {
        "message": "Files uploaded successfully",
        "count": len(uploaded_files),
        "files": uploaded_files,
    }


@app.post(
    "/chunk-and-embed/{file_id}",
    summary="Chunk and embed one uploaded file",
    description="Read the uploaded file UUID from MinIO and persist its chunks in ChromaDB.",
)
async def chunk_and_embed(file_id: str) -> dict:
    try:
        # 1. Download raw file
        content, filename = uploader.download_file(file_id)

        # 2. Parse text pages
        pages = parser.parse(content, filename)

        # 3. Chunk text and attach metadata
        chunks, metadatas, chunk_ids = chunker.split(pages, file_id, filename)

        # 4. Generate vector embeddings
        vectors = embeddings.embed(chunks)

        # 5. Persist to ChromaDB
        retriever.upsert(
            ids=chunk_ids,
            documents=chunks,
            metadatas=metadatas,
            embeddings=vectors,
        )

        response_chunks = [
            {
                "id": chunk_ids[index],
                "text": chunks[index],
                "metadata": metadatas[index],
            }
            for index in range(0, len(chunks), 10)
        ]
        return {
            "collection": retriever.collection_name,
            "chroma_location": retriever.chroma_location,
            "file_id": file_id,
            "filename": filename,
            "chunk_count": len(chunks),
            "returned_chunk_count": len(response_chunks),
            "chunks": response_chunks,
        }
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
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty")

    try:
        # 1. Retrieve relevant chunks
        retrieval_k = int(os.getenv("RETRIEVAL_K", "5"))
        retrieved = retriever.retrieve(question, k=retrieval_k)
        documents = retrieved.get("documents", [[]])[0]
        metadatas = retrieved.get("metadatas", [[]])[0]
        distances = retrieved.get("distances", [[]])[0]
        if not documents:
            raise HTTPException(status_code=400, detail="No indexed document chunks were found")

        # 2. Build prompt and generate response with local Ollama
        prompt = generator.build_prompt(question, documents, metadatas)
        answer = generator.generate(prompt)

        return {
            "question": question,
            "answer": answer,
            "model": generator.model,
            "sources": [
                {"metadata": metadata, "distance": distance}
                for metadata, distance in zip(metadatas, distances)
            ],
        }
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except GenerationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error