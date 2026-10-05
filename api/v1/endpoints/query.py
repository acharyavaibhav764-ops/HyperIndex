from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_rag_service
from schemas.query import QueryRequest, QueryResponse
from services.rag_service import RAGService

router = APIRouter(tags=["Query"])


# POST /api/v1/query
@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Query RAG pipeline",
    description="Retrieve relevant ChromaDB chunks and generate an answer using Ollama.",
)
async def query_pipeline(
    request: QueryRequest,
    service: RAGService = Depends(get_rag_service),
) -> QueryResponse:
    
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty")

    return service.answer_question(question)
