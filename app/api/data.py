"""GET /data/summary — qué hay en la base y cuándo se actualizó cada fuente.

Alimenta la sección "Los datos" de la interfaz, que es informativa y a la vez
de marketing. Por eso es pública (ver `PUBLIC_PATHS` en el middleware de API
key): sólo devuelve conteos agregados y fechas, nada que identifique un
fármaco, un par ni un paciente.

Las fechas salen de la tabla `meta` que escribe cada paso del ETL. Si un paso
no dejó su key, la fecha va en `null`: no se rellena con la del build ni con
ninguna otra, porque una fecha inventada es justo lo que esta sección no puede
permitirse.
"""

import os

from fastapi import APIRouter, Request

from app.clients import recetalia_db
from app.main import limiter
from app.services.duplicity_checker import cargar_cupos

router = APIRouter()

SUMMARY_RATE = os.environ.get("CONSILIO_SEARCH_RATE", "300/minute")

# Fuente -> {campo de la respuesta: key de `meta`}.
SOURCE_META_KEYS: dict[str, dict[str, str]] = {
    "ddinter": {
        "extended_at": "recetalia_extended_at",
        "seeded_at": "recetalia_seeded_at",
        "release": "source_release",
    },
    "openfda": {"fetched_at": "openfda_fetched_at"},
    "medrt": {"fetched_at": "medrt_fetched_at"},
    "aemps": {
        "cross_at": "aemps_cross_at",
        "duplicidad_at": "aemps_duplicidad_at",
        "nombres_es_at": "aemps_nombres_es_at",
        "geriatria_at": "aemps_geriatria_at",
    },
    "rxnorm": {"fetched_at": "rxnorm_rest_fetched_at"},
    "dnma": {"resolved_at": "dnma_resolved_at"},
    "icd10_bridge": {"built_at": "condition_xref_built_at"},
    "build": {"sha": "build_sha", "timestamp": "build_timestamp"},
}

# La fecha que se muestra como "Actualizado el": la primera no nula de la lista.
_UPDATED_AT = {
    "ddinter": ("extended_at", "seeded_at"),
    "openfda": ("fetched_at",),
    "medrt": ("fetched_at",),
    # La AEMPS entra en varios pasos; la fecha de la fuente es la más reciente.
    "aemps": None,
    "rxnorm": ("fetched_at",),
    "dnma": ("resolved_at",),
    "icd10_bridge": ("built_at",),
}


async def build_sources() -> dict[str, dict]:
    keys = [k for campos in SOURCE_META_KEYS.values() for k in campos.values()]
    meta = await recetalia_db.client.meta_values(keys)
    out: dict[str, dict] = {}
    for fuente, campos in SOURCE_META_KEYS.items():
        d = {campo: meta[key] for campo, key in campos.items()}
        if fuente in _UPDATED_AT:
            orden = _UPDATED_AT[fuente]
            if orden is None:
                fechas = [v for k, v in d.items() if k.endswith("_at") and v]
                d["updated_at"] = max(fechas) if fechas else None
            else:
                d["updated_at"] = next((d[c] for c in orden if d[c]), None)
        out[fuente] = d
    return out


@router.get("/data/summary")
@limiter.limit(SUMMARY_RATE)
async def data_summary(request: Request):
    counts = await recetalia_db.client.data_counts()
    cupos = cargar_cupos()
    return {
        **counts,
        "duplicity": {
            **counts["duplicity"],
            "curated_exceptions": len(cupos.get("excepciones", [])),
            "curated_quotas": len(cupos.get("clases", {})),
        },
        "sources": await build_sources(),
    }
