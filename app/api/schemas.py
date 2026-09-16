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
