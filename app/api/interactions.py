"""POST /interactions — check drug-drug interactions."""

import os

from fastapi import APIRouter, Request

from app.api.schemas import DDInterDataSource, InteractionsDataSources, InteractionsRequest, InteractionsResponse
from app.main import limiter
from app.nlp import severity_classifier
from app.services import interaction_checker

router = APIRouter()

# El upstream tenía 10/minute fijo. Detrás de un backend todas las requests
# llegan con la misma IP, así que dos médicos recetando en paralelo lo tumban:
# el chequeo se dispara cada vez que se agrega un medicamento, no una vez por
# receta. Configurable, y con un default que no estorba.
INTERACTIONS_RATE = os.environ.get("CONSILIO_INTERACTIONS_RATE", "120/minute")


@router.post("/interactions", response_model=InteractionsResponse)
@limiter.limit(INTERACTIONS_RATE)
async def check_interactions(request: Request, body: InteractionsRequest):
    result = await interaction_checker.check(body.drugs)
    return InteractionsResponse(
        **result,
        data_sources=InteractionsDataSources(
            ddinter=DDInterDataSource(
                version="2.0",
                license="CC BY-NC-SA 4.0",
                attribution_url="https://ddinter2.scbdd.com/",
            ),
            severity_classifier=severity_classifier.MODEL_ID,
        ),
    )
