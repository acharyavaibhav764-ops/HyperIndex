from typing import Any
from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=10, description="Question for the RAG assistant")


class SourceItem(BaseModel):
    metadata: dict[str, Any]
    distance: float


class QueryResponse(BaseModel):
    question: str
    answer: str
    model: str
    sources: list[SourceItem]
