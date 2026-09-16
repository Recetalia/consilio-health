"""Gate de regresión: la base tiene que coincidir con las severidades curadas.

Guarda permanente contra derivas respecto de eval/interaction_seed_cases.json.
Corre contra la base de Recetalia, no contra el artefacto crudo de DDInter:
es la que lee el servicio, así que es la que hay que verificar.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


DB_PATH = Path(os.environ.get("INTERACTION_DB_PATH", "data/recetalia_interactions.db"))
_SEED = json.loads(Path("eval/interaction_seed_cases.json").read_text())["positive_pairs"]

# Pares que hoy NO podemos detectar, con el motivo medido. No se ablanda el
# gate: se deja constancia de por qué falla y se marca xfail. Cuando exista la
# expansión por clase van a empezar a pasar solos y hay que sacarlos de acá.
KNOWN_GAPS = {
    ("phenelzine", "fluoxetine"):
        "IMAO + ISRS. DDInter no publica la categoría N, así que el par no existe; "
        "y el prospecto de fluoxetina advierte sobre la CLASE ('Monoamine Oxidase "
        "Inhibitors'), nunca nombra a la fenelzina, así que ningún matcheo por "
        "nombre puede encontrarlo. Necesita expansión por clase.",
}


@pytest.mark.parametrize("case", _SEED)
async def test_ddinter_seed_severity_matches_expected(case, monkeypatch):
    if not DB_PATH.exists():
        pytest.skip("Falta la base; el gate necesita INTERACTION_DB_PATH o data/recetalia_interactions.db")

    from app.clients import recetalia_db
    from app.services import interaction_checker

    await recetalia_db.client.close()
    recetalia_db.client.db_path = str(DB_PATH)
    # sin red: ni openFDA en vivo ni RxNorm. La resolución va por nombre contra
    # drug_alias, que es lo que este gate tiene que ejercitar.
    monkeypatch.setattr(interaction_checker.openfda_client, "check_pair", _no_openfda)
    monkeypatch.setattr(interaction_checker.rxnorm_client, "get_rxcui", _no_rxcui)

    try:
        result = await interaction_checker.check([case["drug_a"], case["drug_b"]])
        gap = KNOWN_GAPS.get((case["drug_a"].lower(), case["drug_b"].lower()))
        if gap and not result["interactions"]:
            pytest.xfail(gap)
        assert result["interactions"], (
            f"sin interacción para {case['drug_a']} + {case['drug_b']}: "
            "o falta el par en la base, o falta el alias que lo encuentra")
        hit = result["interactions"][0]
        assert hit["source"] == "ddinter"
        assert hit["severity"] == case["severity"]
    finally:
        await recetalia_db.client.close()


async def _no_openfda(_drug_a: str, _drug_b: str):
    return None


async def _no_rxcui(_name: str):
    return None
