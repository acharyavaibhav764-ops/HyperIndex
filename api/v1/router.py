from fastapi import APIRouter
from api.v1.endpoints import documents, health, query

api_router = APIRouter()

# /health
api_router.include_router(health.router)

# /api/v1
api_router.include_router(documents.router, prefix="/api/v1")
api_router.include_router(query.router, prefix="/api/v1")

