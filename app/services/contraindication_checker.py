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


async def check(drug_names: list[str], profile: PatientProfile) -> dict[str, Any]:
    """Alertas para estos fármacos con este paciente."""
    out: dict[str, Any] = {
        "contraindications": [],
        "precautions": [],
        "allergies": [],
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
                {"drug": name, "reason": "el fármaco no está en la base"})
        else:
            drug_ids[name] = did

    if not drug_ids:
        return out

    # --- 1) alergias declaradas, sin pasar por MeSH ---
    out["allergies"] = await _match_allergies(drug_ids, profile)

    # --- 2) estados y patologías ---
    codes = profile.mesh_codes()
    if not codes:
        return out

    id_by_code = await db.condition_ids_for_codes([("mesh", c) for c in codes])
    condition_ids = [cid for (sys, code), cid in id_by_code.items()
                     if code not in NOT_A_CONDITION]
    if not condition_ids:
        return out

    by_id = {v: k for k, v in drug_ids.items()}
    for row in await db.alerts_for(list(drug_ids.values()), condition_ids):
        entry = {
            "drug": row.get("drug"),
            "condition": row.get("condition"),
            "condition_code": row.get("code"),
            "code_system": row.get("code_system"),
            "relation": row.get("rela"),
            "source": row.get("source"),
        }
        bucket = "contraindications" if row.get("kind") == "contraindication" else "precautions"
        out[bucket].append(entry)

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
                "declared_as": allergic_to[did],
                "match": "exact",
                "severity": "contraindication",
            })

    # Una alergia que no pudimos identificar NO se descarta en silencio: el
    # médico tiene que saber que ese dato no se usó.
    for u in unknown:
        out.append({
            "drug": None,
            "declared_as": u,
            "match": "unresolved",
            "severity": "unknown",
            "note": "no se pudo identificar el fármaco declarado como alergia",
        })
    return out
