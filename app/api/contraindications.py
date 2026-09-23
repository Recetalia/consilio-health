"""POST /contraindications — alertas fármaco-paciente."""

import os

from fastapi import APIRouter, Request

from app.api.schemas import ContraindicationsRequest, ContraindicationsResponse
from app.main import limiter
from app.services import contraindication_checker
from app.services.patient_profile import PatientProfile

router = APIRouter()

RATE = os.environ.get("CONSILIO_CONTRAINDICATIONS_RATE", "120/minute")


@router.post("/contraindications", response_model=ContraindicationsResponse)
@limiter.limit(RATE)
async def check_contraindications(request: Request, body: ContraindicationsRequest):
    profile = PatientProfile(
        sexo=body.profile.sexo,
        edad=body.profile.edad,
        embarazo=body.profile.embarazo,
        semanas_gestacion=body.profile.semanas_gestacion,
        lactancia=body.profile.lactancia,
        funcion_renal=body.profile.funcion_renal,
        funcion_hepatica=body.profile.funcion_hepatica,
        alergias=body.profile.alergias,
        patologias_mesh=body.profile.patologias_mesh,
        patologias_icd10=body.profile.patologias_icd10,
    )
    result = await contraindication_checker.check(body.drugs, profile)
    return ContraindicationsResponse(**result)
