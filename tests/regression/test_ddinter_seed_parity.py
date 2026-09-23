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
# Vacío a propósito. Acá van los pares que NO podemos detectar, con el motivo
# medido, para que el gate quede rojo documentado en vez de ablandado.
# (phenelzine + fluoxetine vivió acá hasta que la expansión por clase lo
# resolvió: el prospecto advierte sobre "Monoamine Oxidase Inhibitors" sin
# nombrar a la fenelzina, y la clase MOA la contiene.)
KNOWN_GAPS: dict[tuple[str, str], str] = {}


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
        # El origen no se fija: un par puede llegar de DDInter, de expansión por
        # clase sobre un prospecto, o de curación propia. Lo que el gate
        # garantiza es la severidad curada, venga de donde venga.
        assert hit["source"] in {"recetalia", "aemps", "ddinter", "openfda"}, hit["source"]
        assert hit["severity"] == case["severity"], (
            f"{case['drug_a']} + {case['drug_b']}: esperaba {case['severity']}, "
            f"llegó {hit['severity']} desde {hit['source']}")
    finally:
        await recetalia_db.client.close()


async def _no_openfda(_drug_a: str, _drug_b: str):
    return None


async def _no_rxcui(_name: str):
    return None
