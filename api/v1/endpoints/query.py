from fastapi import APIRouter, HTTPException

from config import settings
from api.dependencies import generator, retriever
from schemas.query import QueryRequest, QueryResponse, SourceItem

router = APIRouter(tags=["Query"])


# POST /api/v1/query
@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Query RAG pipeline",
    description="Retrieve relevant ChromaDB chunks and generate an answer using Ollama.",
)
async def query_pipeline(request: QueryRequest) -> QueryResponse:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty")

    # Retrieve relevant chunks
    retrieved = retriever.retrieve(question, k=settings.retrieval_k)
    documents = retrieved.get("documents", [[]])[0]
    metadatas = retrieved.get("metadatas", [[]])[0]
    distances = retrieved.get("distances", [[]])[0]
    if not documents:
        raise HTTPException(status_code=400, detail="No indexed document chunks were found")

    # Build prompt and generate response with local Ollama
    prompt = generator.build_prompt(question, documents, metadatas)
    answer = generator.generate(prompt)

    # Return response
    return QueryResponse(
        question=question,
        answer=answer,
        model=generator.model,
        sources=[
            SourceItem(metadata=metadata, distance=distance)
            for metadata, distance in zip(metadatas, distances)
        ],
    )

