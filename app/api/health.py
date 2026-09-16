"""Health check endpoints."""

from fastapi import APIRouter
from app.clients import recetalia_db
from app.nlp import severity_classifier

router = APIRouter()


@router.get("/health")
async def health_check():
    """Basic health check to verify the API is running."""
    return {
        "status": "ok",
        "version": "0.1.0",
        "severity_classifier_loaded": severity_classifier.is_loaded(),
    }


@router.get("/health/data")
async def data_health_check():
    """Check the status of the drug interaction data source."""
    connected = await recetalia_db.client.health_check()
    return {
        "status": "ready" if connected else "degraded",
        "ddinter": "connected" if connected else "unreachable",
    }
