"""Alertas fármaco-paciente.

Cruza los fármacos de la receta contra el perfil del paciente. Dos caminos
distintos, porque son dos cosas distintas:

1. **Estados y patologías** → `drug_condition_alert`, la tabla de MED-RT.
2. **Alergias** → no es una condición del paciente, es una relación con un
   fármaco. Se resuelve comparando el fármaco recetado contra lo que el paciente
   declaró, y no pasa por MeSH.

Todo local: no hay red en el camino de la request.
"""

from __future__ import annotations

import logging
from typing import Any

from app.clients import recetalia_db
from app.services.patient_profile import PatientProfile

logger = logging.getLogger(__name__)

# MED-RT clasifica algunas CLASES DE FÁRMACOS dentro de su árbol de
# enfermedades: "Monoamine Oxidase Inhibitors", "Sulfonamides". Como condición
# del paciente no significan nada, y mostrárselas a un médico como si fueran una
# patología es ruido. Se filtran por código.
NOT_A_CONDITION = {
    "D008996",  # Monoamine Oxidase Inhibitors
    "D013449",  # Sulfonamides
    "D000305",  # Adrenal Cortex Hormones
}

SEVERITY_ORDER = {"contraindication": 0, "precaution": 1}

# El umbral con el que la AEMPS escribió sus criterios de prescripción en el
# anciano. No se infiere de la edad: si el médico no la cargó, no hay alerta
# geriátrica. Suponer que un paciente sin edad es joven sería el mismo error
# que suponerlo viejo, pero en la dirección que calla.
EDAD_ANCIANO = 65


async def check(drug_names: list[str], profile: PatientProfile) -> dict[str, Any]:
    """Alertas para estos fármacos con este paciente."""
    out: dict[str, Any] = {
        "contraindications": [],
        "precautions": [],
        "allergies": [],
        "geriatric": [],
        "not_evaluated": [],
        "profile_warnings": profile.warnings(),
    }
    if not drug_names:
        return out

    db = recetalia_db.client

    # --- fármacos -> drug_id ---
    drug_ids: dict[str, int] = {}
    for name in dict.fromkeys(drug_names):
        did = await db.drug_id_by_name(name)
        if did is None:
            out["not_evaluated"].append(
                {"drug": name, "drug_input": name,
                 "reason": "el fármaco no está en la base"})
        else:
            drug_ids[name] = did

    if not drug_ids:
        return out

    # `drug` sale como el canónico en inglés; `drug_input` es el nombre tal
    # como llegó, para que el llamador vuelva a SU producto sin adivinar la
    # traducción. Dos nombres de entrada pueden ser el mismo fármaco
    # ("aspirina" y "aspirin"): el hallazgo sale una vez por cada uno.
    names_by_id: dict[int, list[str]] = {}
    for name, did in drug_ids.items():
        names_by_id.setdefault(did, []).append(name)

    # --- 1) alergias declaradas, sin pasar por MeSH ---
    out["allergies"] = await _match_allergies(drug_ids, profile)

    # --- 2) alertas geriátricas, que dependen de la edad y no de MeSH ---
    if profile.edad is not None and profile.edad >= EDAD_ANCIANO:
        for row in await db.population_alerts_for(list(drug_ids.values())):
            did = row.pop("drug_id", None)
            for name in names_by_id.get(did, [None]):
                out["geriatric"].append({**row, "drug_input": name})

    # --- 3) estados y patologías ---
    codes = profile.mesh_codes()
    if not codes and not profile.patologias_icd10:
        return out

    id_by_code = await db.condition_ids_for_codes([("mesh", c) for c in codes])
    condition_ids = [cid for (sys, code), cid in id_by_code.items()
                     if code not in NOT_A_CONDITION]

    # Las patologías que carga el médico vienen en CIE-10. El puente las
    # traduce resolviendo código exacto, ancestros por truncación y rangos.
    if profile.patologias_icd10:
        traducidas = await db.condition_ids_for_icd10(profile.patologias_icd10)
        for cid_list in traducidas.values():
            condition_ids.extend(cid_list)
        no_traducidas = [c for c in profile.patologias_icd10 if c not in traducidas]
        for c in no_traducidas:
            # No se omite en silencio: el médico tiene que saber que ese
            # diagnóstico no se pudo tener en cuenta.
            out["not_evaluated"].append(
                {"drug": None, "drug_input": None, "icd10": c,
                 "reason": "sin equivalencia conocida para ese código CIE-10"})
        condition_ids = list(dict.fromkeys(condition_ids))
    if not condition_ids:
        return out

    for row in await db.alerts_for(list(drug_ids.values()), condition_ids):
        bucket = "contraindications" if row.get("kind") == "contraindication" else "precautions"
        for name in names_by_id.get(row.get("drug_id"), [None]):
            out[bucket].append({
                "drug": row.get("drug"),
                "drug_input": name,
                "condition": row.get("condition"),
                "condition_code": row.get("code"),
                "code_system": row.get("code_system"),
                "relation": row.get("rela"),
                "detail": row.get("detail"),
                "source": row.get("source"),
            })

    logger.debug("Alertas fármaco-paciente: %d contraindicaciones, %d precauciones, "
                 "%d alergias sobre %d fármacos",
                 len(out["contraindications"]), len(out["precautions"]),
                 len(out["allergies"]), len(drug_ids))
    return out


async def _match_allergies(
    drug_ids: dict[str, int], profile: PatientProfile
) -> list[dict[str, Any]]:
    """Cruza lo recetado contra lo que el paciente declaró como alergia.

    Se compara por `drug_id`, no por string: así `aspirina`, `aspirin` y
    `Acetylsalicylic acid` son el mismo fármaco, que es justamente para lo que
    existe la tabla de alias.
    """
    if not profile.alergias:
        return []

    db = recetalia_db.client
    allergic_to: dict[int, str] = {}
    unknown: list[str] = []
    for declared in profile.alergias:
        did = await db.drug_id_by_name(declared)
        if did is None:
            unknown.append(declared)
        else:
            allergic_to[did] = declared

    out = []
    for name, did in drug_ids.items():
        if did in allergic_to:
            out.append({
                "drug": name,
                "drug_input": name,
                "declared_as": allergic_to[did],
                "match": "exact",
                "severity": "contraindication",
            })

    # Una alergia que no pudimos identificar NO se descarta en silencio: el
    # médico tiene que saber que ese dato no se usó.
    for u in unknown:
        out.append({
            "drug": None,
            "drug_input": None,
            "declared_as": u,
            "match": "unresolved",
            "severity": "unknown",
            "note": "no se pudo identificar el fármaco declarado como alergia",
        })
    return out
