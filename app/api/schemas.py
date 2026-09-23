"""Pydantic request/response models for the Consilio."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints


# --- POST /interactions ---

class InteractionsRequest(BaseModel):
    drugs: list[Annotated[str, StringConstraints(min_length=1, max_length=200, strip_whitespace=True)]] = Field(
        ..., min_length=2, examples=[["ibuprofen", "warfarin"]]
    )


class DrugRef(BaseModel):
    name: str


class InteractionResult(BaseModel):
    drug_a: str
    drug_b: str
    rxcui_a: str | None = None
    rxcui_b: str | None = None
    severity: str
    source: Literal["ddinter", "openfda", "recetalia"]
    # Pueden faltar: DDInter aporta el par y el nivel, no texto. Antes se
    # rellenaban con una plantilla que sólo repetía los dos nombres, y eso se
    # lee como evidencia sin serlo.
    description: str | None = None
    management: str | None = None
    uncertain: bool = False


class DDInterDataSource(BaseModel):
    version: str
    license: str
    attribution_url: str


class InteractionsDataSources(BaseModel):
    ddinter: DDInterDataSource | None = None
    severity_classifier: str


_INTERACTION_LIMITATIONS = [
    "Checks pairwise interactions only — multi-drug cascades are not detected",
    "Does not account for patient-specific factors (age, weight, renal/hepatic function, genetics)",
    "Coverage depends on the DDInter 2.0 corpus and OpenFDA labels",
    "Not a substitute for professional medical advice",
]


class InteractionsResponse(BaseModel):
    interactions: list[InteractionResult]
    safe: bool | None
    error: str | None = None
    data_sources: InteractionsDataSources | None = None
    coverage_summary: dict[str, int] = Field(
        default_factory=lambda: {"recetalia": 0, "ddinter": 0, "openfda": 0, "unknown": 0})
    limitations: list[str] = _INTERACTION_LIMITATIONS


# --- POST /contraindications ---

class PatientProfileIn(BaseModel):
    """Perfil del paciente. Todo opcional: sin datos no hay alertas.

    Los estados fisiológicos son flags y no códigos de patología, porque no son
    diagnósticos. `patologias_mesh` existe para cuando el puente CIE-10 traduzca
    lo que el médico cargue; hoy se puede mandar directo si el llamador ya tiene
    descriptores MeSH.
    """
    sexo: Literal["M", "F"] | None = None
    edad: int | None = Field(None, ge=0, le=130)
    embarazo: bool = False
    semanas_gestacion: int | None = Field(None, ge=1, le=45)
    lactancia: bool = False
    funcion_renal: str | None = None
    funcion_hepatica: str | None = None
    alergias: list[str] = Field(default_factory=list, max_length=50)
    patologias_mesh: list[str] = Field(default_factory=list, max_length=50)
    patologias_icd10: list[str] = Field(default_factory=list, max_length=50)


class ContraindicationsRequest(BaseModel):
    drugs: list[Annotated[str, StringConstraints(min_length=1, max_length=200,
                                                 strip_whitespace=True)]] = Field(
        ..., min_length=1, examples=[["warfarin", "ibuprofen"]])
    profile: PatientProfileIn = Field(default_factory=PatientProfileIn)


class ContraindicationsResponse(BaseModel):
    contraindications: list[dict] = Field(default_factory=list)
    precautions: list[dict] = Field(default_factory=list)
    allergies: list[dict] = Field(default_factory=list)
    """Criterios de prescripción en el anciano. Casi todos vienen con
    `condicionada=true`: la situación que los dispara —una comorbilidad, un
    valor de laboratorio— no está en la receta, así que el hallazgo dice
    *verificar si*, no *pasa esto*."""
    geriatric: list[dict] = Field(default_factory=list)
    """Fármacos que no pudimos evaluar. Explícito, nunca omitido en silencio."""
    not_evaluated: list[dict] = Field(default_factory=list)
    """Incoherencias del perfil: se avisan, no se resuelven por nuestra cuenta."""
    profile_warnings: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "Informaci\u00f3n generada autom\u00e1ticamente a partir de fuentes p\u00fablicas. "
        "No sustituye el criterio cl\u00ednico.")
