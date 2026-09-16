"""Chequeo de interacciones contra la base de Recetalia.

La base local es la fuente: trae los pares de DDInter, los derivados de openFDA
y lo que haya curado un farmacéutico, cada uno con su procedencia. La llamada
en vivo a openFDA quedó como último recurso para fármacos que la base no
conoce — el 99% de los chequeos no toca la red.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.clients import openfda_client, recetalia_db, rxnorm_client
from app.middleware.audit_log import get_audit_context
from app.nlp import severity_classifier

logger = logging.getLogger(__name__)

_MANAGEMENT = "Consult a healthcare professional for guidance."
_EMPTY_COVERAGE = {"recetalia": 0, "ddinter": 0, "openfda": 0, "unknown": 0}


async def check(drug_names: list[str]) -> dict[str, Any]:
    """Check pairwise interactions for the supplied drug names."""
    if len(drug_names) < 2:
        return {
            "interactions": [],
            "safe": True,
            "error": None,
            "coverage_summary": dict(_EMPTY_COVERAGE),
        }

    unique_names = []
    seen_names: set[str] = set()
    for name in drug_names:
        key = name.casefold()
        if key not in seen_names:
            seen_names.add(key)
            unique_names.append(name)
    rxcui_results = await asyncio.gather(
        *[rxnorm_client.get_rxcui(name) for name in unique_names],
        return_exceptions=True,
    )
    rxcui_by_name: dict[str, str | None] = {}
    for name, result in zip(unique_names, rxcui_results):
        if isinstance(result, Exception):
            logger.warning("RxNorm failed for %s: %s", name, result)
            rxcui_by_name[name] = None
        else:
            rxcui_by_name[name] = result

    interactions: list[dict[str, Any]] = []
    coverage = dict(_EMPTY_COVERAGE)
    for index, drug_a in enumerate(unique_names):
        for drug_b in unique_names[index + 1:]:
            entry, bucket = await _resolve_pair(drug_a, drug_b, rxcui_by_name)
            coverage[bucket] += 1
            if entry is not None:
                interactions.append(entry)

    return {
        "interactions": interactions,
        "safe": len(interactions) == 0,
        "error": None,
        "coverage_summary": coverage,
    }


async def _resolve_pair(
    drug_a: str,
    drug_b: str,
    rxcui_by_name: dict[str, str | None],
) -> tuple[dict[str, Any] | None, str]:
    rxcui_a = rxcui_by_name.get(drug_a)
    rxcui_b = rxcui_by_name.get(drug_b)

    # 1) por RxCUI: el camino bueno, sin ambigüedad de nombre
    if rxcui_a and rxcui_b:
        try:
            hit = await recetalia_db.client.lookup_by_rxcui(rxcui_a, rxcui_b)
        except Exception:
            logger.warning("Búsqueda por RxCUI falló para %s + %s", drug_a, drug_b, exc_info=True)
        else:
            if hit:
                return _format_local(drug_a, drug_b, rxcui_a, rxcui_b, hit), hit["source"]

    # 2) por nombre normalizado contra drug_alias
    try:
        hit = await recetalia_db.client.lookup_by_name(drug_a, drug_b)
    except Exception:
        logger.warning("Búsqueda por nombre falló para %s + %s", drug_a, drug_b, exc_info=True)
    else:
        if hit:
            return _format_local(drug_a, drug_b, rxcui_a, rxcui_b, hit), hit["source"]

    # 3) openFDA en vivo: sólo para lo que la base no conoce
    fda_hit = await _openfda_pair(drug_a, drug_b)
    if fda_hit:
        return await _format_openfda(drug_a, drug_b, rxcui_a, rxcui_b, fda_hit), "openfda"

    return None, "unknown"


def _format_local(
    drug_a: str,
    drug_b: str,
    rxcui_a: str | None,
    rxcui_b: str | None,
    hit: dict[str, Any],
) -> dict[str, Any]:
    """Arma la respuesta desde una fila de la base, sea cual sea su procedencia."""
    severity = hit.get("severity") or "unknown"
    source = hit["source"]
    _audit_severity(drug_a, drug_b, severity, hit["uncertain"], source, "recetalia_db")

    if hit.get("evidence"):
        # openFDA: la oración del prospecto es la descripción, no una plantilla
        description = hit["evidence"]
    elif hit.get("mechanism"):
        description = hit["mechanism"]
    else:
        description = (
            f"Interaction reported in DDInter 2.0 for "
            f"{hit.get('drug_a_name', drug_a)} + {hit.get('drug_b_name', drug_b)}."
        )

    return {
        "drug_a": drug_a,
        "drug_b": drug_b,
        "rxcui_a": rxcui_a,
        "rxcui_b": rxcui_b,
        "severity": severity,
        "source": source,
        "description": description,
        "management": hit.get("management") or _MANAGEMENT,
        # openFDA sale de texto libre: el médico tiene que poder distinguirlo
        "uncertain": hit["uncertain"],
    }


def _format_ddinter(
    drug_a: str,
    drug_b: str,
    rxcui_a: str | None,
    rxcui_b: str | None,
    hit: dict[str, Any],
) -> dict[str, Any]:
    severity = hit.get("severity") or "unknown"
    _audit_severity(drug_a, drug_b, severity, False, "ddinter", "ddinter_sqlite")
    return {
        "drug_a": drug_a,
        "drug_b": drug_b,
        "rxcui_a": rxcui_a,
        "rxcui_b": rxcui_b,
        "severity": severity,
        "source": "ddinter",
        "description": (
            f"Interaction reported in DDInter 2.0 for "
            f"{hit.get('drug_a_name', drug_a)} + {hit.get('drug_b_name', drug_b)}."
        ),
        "management": _MANAGEMENT,
        "uncertain": False,
    }


async def _openfda_pair(drug_a: str, drug_b: str) -> dict[str, Any] | None:
    try:
        fda_hit = await openfda_client.check_pair(drug_a, drug_b)
        if fda_hit is None:
            fda_hit = await openfda_client.check_pair(drug_b, drug_a)
        return fda_hit
    except Exception:
        logger.warning("OpenFDA fallback failed for %s + %s", drug_a, drug_b, exc_info=True)
        return None


async def _format_openfda(
    drug_a: str,
    drug_b: str,
    rxcui_a: str | None,
    rxcui_b: str | None,
    hit: dict[str, Any],
) -> dict[str, Any]:
    description = hit.get("description", "")
    loop = asyncio.get_running_loop()
    severity, uncertain = await loop.run_in_executor(None, severity_classifier.classify, description)
    _audit_severity(drug_a, drug_b, severity, uncertain, "openfda", "zero_shot_classifier")
    return {
        "drug_a": drug_a,
        "drug_b": drug_b,
        "rxcui_a": rxcui_a,
        "rxcui_b": rxcui_b,
        "severity": severity,
        "source": "openfda",
        "description": description or "Interaction reported in FDA labeling.",
        "management": _MANAGEMENT,
        "uncertain": uncertain,
    }


def _audit_severity(
    drug_a: str,
    drug_b: str,
    severity: str,
    uncertain: bool,
    source: str,
    method: str,
) -> None:
    ctx = get_audit_context()
    if ctx:
        ctx.add("severity_classification", {
            "drug_a": drug_a,
            "drug_b": drug_b,
            "severity": severity,
            "uncertain": uncertain,
            "source": source,
            "method": method,
        })
