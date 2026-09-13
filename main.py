from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from config import settings
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
from schemas import (
    FileIndexResponse,
    FileUploadItem,
    FileUploadResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    SourceItem,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

uploader = Uploader()
parser = Parser()
chunker = Chunker()
embeddings = Embeddings()
retriever = Retriever(embeddings=embeddings)
generator = Generator()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle."""
    
    logger.info("Initializing application resources...")
    uploader.ensure_bucket()
    yield
    logger.info("Shutting down application resources...")


app = FastAPI(title="Honeywell RAG", version="1.0.0", lifespan=lifespan)


# Global Exception Handlers
@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})

@app.exception_handler(StorageError)
async def storage_error_handler(request: Request, exc: StorageError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})

@app.exception_handler(GenerationError)
async def generation_error_handler(request: Request, exc: GenerationError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health Check",
    description="Liveness probe indicating the service is running.",
)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok", version="1.0.0")


@app.post(
    "/upload",
    response_model=FileUploadResponse,
    summary="Upload multiple files",
    description=(
        "Upload one or more files. In Swagger, choose a file and use "
        "'Add string item' to add more files before executing."
    ),
)
async def upload_files(files: list[UploadFile] = File(...)) -> FileUploadResponse:
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    uploaded_files = uploader.upload_files(files)

    return FileUploadResponse(
        message="Files uploaded successfully",
        count=len(uploaded_files),
        files=[FileUploadItem(**item) for item in uploaded_files],
    )


@app.post(
    "/chunk-and-embed/{file_id}",
    response_model=FileIndexResponse,
    summary="Chunk and embed one uploaded file",
    description="Read the uploaded file UUID from MinIO and persist its chunks in ChromaDB.",
)
async def chunk_and_embed(file_id: str) -> FileIndexResponse:
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

    return FileIndexResponse(
        file_id=file_id,
        filename=filename,
        collection=retriever.collection_name,
        total_chunks=len(chunks),
        indexed_chunks=len(chunks),
    )


@app.post(
    "/generate",
    response_model=QueryResponse,
    summary="Answer a question using indexed documents",
    description="Retrieve relevant ChromaDB chunks and answer with the local Ollama model.",
)
async def generate_answer(request: QueryRequest) -> QueryResponse:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty")

    # 1. Retrieve relevant chunks
    retrieved = retriever.retrieve(question, k=settings.retrieval_k)
    documents = retrieved.get("documents", [[]])[0]
    metadatas = retrieved.get("metadatas", [[]])[0]
    distances = retrieved.get("distances", [[]])[0]
    if not documents:
        raise HTTPException(status_code=400, detail="No indexed document chunks were found")

    # 2. Build prompt and generate response with local Ollama
    prompt = generator.build_prompt(question, documents, metadatas)
    answer = generator.generate(prompt)

    return QueryResponse(
        question=question,
        answer=answer,
        model=generator.model,
        sources=[
            SourceItem(metadata=metadata, distance=distance)
            for metadata, distance in zip(metadatas, distances)
        ],
    )