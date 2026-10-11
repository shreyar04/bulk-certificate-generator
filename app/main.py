"""Application entry point. Start it from the project root with:

    uvicorn app.main:app --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import config, database, models  # noqa: F401  (models must be imported so tables are known)
from app.routes import certificates, jobs
from app.schemas import HealthResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Runs once at startup: create the output folder and the database tables."""
    config.CERTIFICATE_DIR.mkdir(parents=True, exist_ok=True)
    database.Base.metadata.create_all(bind=database.engine)
    yield


app = FastAPI(
    title="Bulk Certificate Generator API",
    description="Create one job with many recipients and get a personalised PDF certificate for each.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(jobs.router)
app.include_router(certificates.router)


@app.get("/health", response_model=HealthResponse, tags=["Health"])
def health() -> HealthResponse:
    """Simple check that the API is running."""
    return HealthResponse(status="ok")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last safety net: log the details on the server, tell the client nothing sensitive."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
