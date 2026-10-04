from fastapi import APIRouter
from schemas.health import HealthResponse

router = APIRouter(tags=["Health"])


# GET /health
@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health Check",
    description="Liveness probe indicating the service is running.",
)
async def health_check() -> HealthResponse:
    
    return HealthResponse(status="ok", version="1.0.0")

