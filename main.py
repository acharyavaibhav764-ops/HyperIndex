from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.deps import get_uploader
from api.v1.router import api_router
from core import GenerationError, StorageError
from db.database import Base, engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle."""
    
    logger.info("Initializing application resources...")
    Base.metadata.create_all(bind=engine)
    get_uploader().ensure_bucket()
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


# Mount Versioned Modern RESTful API & Health Probe
app.include_router(api_router)
