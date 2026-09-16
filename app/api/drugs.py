"""GET /drugs/search — autocompletado de fármacos.

Lo necesita cualquier interfaz que deje escribir un nombre: sin esto el usuario
tiene que adivinar la ortografía exacta con la que el fármaco está guardado.
"""

import os

from fastapi import APIRouter, Query, Request

from app.clients import recetalia_db
from app.main import limiter

router = APIRouter()

SEARCH_RATE = os.environ.get("CONSILIO_SEARCH_RATE", "300/minute")


@router.get("/drugs/search")
@limiter.limit(SEARCH_RATE)
async def search_drugs(
    request: Request,
    q: str = Query(..., min_length=2, max_length=100),
    limit: int = Query(10, ge=1, le=25),
):
    return {"results": await recetalia_db.client.search_drugs(q, limit)}
