import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded


def _get_real_client_ip(request: Request) -> str:
    """Extract real client IP from X-Forwarded-For (Cloud Run) or fall back to direct IP."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_get_real_client_ip)

from app.api.admin import router as admin_router
from app.api.drugs import router as drugs_router
from app.api.health import router as health_router
from app.api.interactions import router as interactions_router
from app.clients import recetalia_db
from app.middleware.api_key import APIKeyMiddleware
from app.middleware.audit_log import AuditLogMiddleware
from app.nlp import severity_classifier

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Loading severity classifier...")
    severity_classifier.load_model()
    logger.info("Severity classifier loaded: %s", severity_classifier.is_loaded())
    logger.info("Conectando al SQLite de interacciones...")
    # La base horneada es requisito de arranque: si falta, es mejor que la
    # revisión no levante a que sirva con cobertura degradada en silencio.
    await recetalia_db.client.connect()
    logger.info("Base de interacciones conectada: %s", await recetalia_db.client.stats())
    yield
    await recetalia_db.client.close()


app = FastAPI(
    title="Consilio",
    description="Medication interaction checker",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS: only needed for local development (different ports).
# In production, Cloud Run handles routing directly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)

app.add_middleware(APIKeyMiddleware)
app.add_middleware(AuditLogMiddleware)

app.include_router(health_router)
app.include_router(interactions_router)
app.include_router(drugs_router)

# Interfaz de consulta. Se sirve desde el mismo proceso: Consilio es un producto
# standalone, no una API a la que haya que construirle un frontend aparte.
_WEB = Path(__file__).parent / "web"
app.mount("/ui", StaticFiles(directory=_WEB), name="ui")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(_WEB / "index.html")
app.include_router(admin_router)
