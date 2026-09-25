"""Pydantic request/response models for the Consilio."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator


# --- POST /interactions ---

class ProductIn(BaseModel):
    """Un producto recetado y sus sustancias. Sin esto un combinado llega
    desarmado y la misma sustancia en dos productos es invisible."""
    id: Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)]
    substances: list[Annotated[str, StringConstraints(min_length=1, max_length=200,
                                                      strip_whitespace=True)]] = Field(
        ..., min_length=1, max_length=20)
    # Aceptada desde ya; la regla tópico/sistémico se escribe cuando Recetalia la mande.
    route: str | None = Field(None, max_length=50)


class InteractionsRequest(BaseModel):
    # Tope defensivo: `drugs` derivado de `products` puede acumular hasta 20
    # sustancias por 50 productos (1.000). Sin tope, eso dispara 1.000
    # llamadas a RxNorm y ~500.000 pares en interaction_checker.
    drugs: list[Annotated[str, StringConstraints(min_length=1, max_length=200,
                                                 strip_whitespace=True)]] = Field(
        default_factory=list, max_length=50, examples=[["ibuprofen", "warfarin"]])
    products: list[ProductIn] | None = Field(None, max_length=50)

    @model_validator(mode="after")
    def _al_menos_dos(self):
        # Compatible hacia atrás: sin `products`, `drugs` sigue exigiendo 2.
        if self.products:
            ids = [p.id for p in self.products]
            if len(ids) != len(set(ids)):
                raise ValueError("ids de producto repetidos")
            if not self.drugs:
                vistos: list[str] = []
                for p in self.products:
                    vistos += [s for s in p.substances if s not in vistos]
                # No pasa por el `max_length` del campo: se arma acá, después
                # de parsear, y una reasignación no vuelve a validar el campo.
                if len(vistos) > 50:
                    raise ValueError("demasiadas sustancias: máximo 50 distintas")
                self.drugs = vistos
            if len(self.products) < 2 and len(self.drugs) < 2:
                raise ValueError("hacen falta al menos dos productos o dos sustancias")
        elif len(self.drugs) < 2:
            raise ValueError("drugs necesita al menos dos elementos")
        return self


class DrugRef(BaseModel):
    name: str


class InteractionResult(BaseModel):
    drug_a: str
    drug_b: str
    rxcui_a: str | None = None
    rxcui_b: str | None = None
    severity: str
    # ⚠️ Este literal es un contrato, no una anotación: si se agrega una fuente
    # a la base y no se agrega acá, el endpoint devuelve 500 en cuanto aparece
    # un hallazgo de esa fuente. Pasó al cargar la AEMPS, y no lo vio ningún
    # test porque los de la API mockean el servicio por encima de este modelo.
    source: Literal["aemps", "ddinter", "openfda", "recetalia"]
    # Pueden faltar: DDInter aporta el par y el nivel, no texto. Antes se
    # rellenaban con una plantilla que sólo repetía los dos nombres, y eso se
    # lee como evidencia sin serlo.
    description: str | None = None
    management: str | None = None
    uncertain: bool = False
    # Presentes sólo cuando el hallazgo se armó con más de una fuente: la
    # gravedad de una y el texto de otra. Se declara en vez de disimularse.
    severity_source: str | None = None
    text_source: str | None = None


class DDInterDataSource(BaseModel):
    version: str
    license: str
    attribution_url: str


class InteractionsDataSources(BaseModel):
    ddinter: DDInterDataSource | None = None
    severity_classifier: str


_INTERACTION_LIMITATIONS = [
    "Checks pairwise interactions only — multi-drug cascades are not detected",
    "Therapeutic duplicity is evaluated separately (same substance, or same "
    "AEMPS class over quota) — it is not a drug-drug interaction",
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
        default_factory=lambda: {"recetalia": 0, "aemps": 0, "ddinter": 0,
                                 "openfda": 0, "unknown": 0})
    """Duplicidad terapéutica. Ver docs/2026-09-24-duplicidad-terapeutica-design.md."""
    duplicities: list[dict] = Field(default_factory=list)
    """Lo que NO se alertó por un cupo o una excepción, con el motivo."""
    duplicities_suppressed: list[dict] = Field(default_factory=list)
    duplicity_not_evaluated: list[str] = Field(default_factory=list)
    duplicity_warnings: list[str] = Field(default_factory=list)
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
