"""Ruteo del checker: base local -> openFDA en vivo -> unknown."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services import interaction_checker


@pytest.fixture(autouse=True)
def patch_clients(monkeypatch):
    rx = AsyncMock(return_value=None)
    monkeypatch.setattr(interaction_checker.rxnorm_client, "get_rxcui", rx)

    ddc = AsyncMock(return_value=None)
    ddn = AsyncMock(return_value=None)
    monkeypatch.setattr(interaction_checker.recetalia_db.client, "lookup_by_rxcui", ddc)
    monkeypatch.setattr(interaction_checker.recetalia_db.client, "lookup_by_name", ddn)

    fda = AsyncMock(return_value=None)
    monkeypatch.setattr(interaction_checker.openfda_client, "check_pair", fda)

    dup = AsyncMock(return_value={"duplicities": [], "duplicities_suppressed": [],
                                  "duplicity_not_evaluated": [], "duplicity_warnings": []})
    monkeypatch.setattr(interaction_checker.duplicity_checker, "chequear", dup)
    return {"rxnorm": rx, "ddinter_rxcui": ddc, "ddinter_fts": ddn, "openfda": fda, "duplicity": dup}


async def test_ddinter_hit_via_rxcui(patch_clients):
    patch_clients["rxnorm"].side_effect = ["11289", "1191"]
    patch_clients["ddinter_rxcui"].return_value = {
        "drug_a_name": "Warfarin",
        "drug_b_name": "Aspirin",
        "severity": "major",
        "source": "ddinter",
        "uncertain": False,
    }
    result = await interaction_checker.check(["Warfarin", "Aspirin"])
    assert result["coverage_summary"]["ddinter"] == 1
    assert result["interactions"][0]["source"] == "ddinter"
    assert result["interactions"][0]["severity"] == "major"
    assert result["interactions"][0]["rxcui_a"] == "11289"
    patch_clients["openfda"].assert_not_called()


async def test_falls_back_to_fts_when_rxcui_misses(patch_clients):
    patch_clients["rxnorm"].side_effect = [None, None]
    patch_clients["ddinter_fts"].return_value = {
        "drug_a_name": "Warfarin",
        "drug_b_name": "Aspirin",
        "severity": "major",
        "source": "ddinter",
        "uncertain": False,
    }
    result = await interaction_checker.check(["Warfarin", "Aspirin"])
    assert result["interactions"][0]["source"] == "ddinter"
    patch_clients["openfda"].assert_not_called()


async def test_openfda_fallback_when_ddinter_misses(patch_clients):
    patch_clients["rxnorm"].side_effect = ["11289", "1191"]
    patch_clients["openfda"].return_value = {"drug": "Aspirin", "description": "Some FDA label sentence."}
    with patch.object(interaction_checker.severity_classifier, "classify", return_value=("moderate", False)):
        result = await interaction_checker.check(["Warfarin", "Aspirin"])
    assert result["interactions"][0]["source"] == "openfda"
    assert result["interactions"][0]["severity"] == "moderate"
    assert result["coverage_summary"]["openfda"] == 1


async def test_unknown_when_all_paths_miss(patch_clients):
    patch_clients["rxnorm"].side_effect = ["1", "2"]
    result = await interaction_checker.check(["A", "B"])
    assert result["coverage_summary"] == {
        "recetalia": 0, "aemps": 0, "ddinter": 0, "openfda": 0, "unknown": 1}
    assert result["interactions"] == []


async def test_openfda_low_confidence_keeps_safety_default(patch_clients):
    patch_clients["rxnorm"].side_effect = ["1", "2"]
    patch_clients["openfda"].return_value = {"drug": "B", "description": "vague text"}
    with patch.object(interaction_checker.severity_classifier, "classify", return_value=("major", True)):
        result = await interaction_checker.check(["A", "B"])
    assert result["interactions"][0]["severity"] == "major"
    assert result["interactions"][0]["uncertain"] is True


async def test_sin_products_cada_nombre_es_un_producto(patch_clients):
    patch_clients["rxnorm"].side_effect = ["1", "2"]
    await interaction_checker.check(["A", "B"])
    args = patch_clients["duplicity"].call_args.args
    assert args[1] == [{"id": "A", "substances": ["A"]}, {"id": "B", "substances": ["B"]}]


async def test_products_se_pasan_y_la_respuesta_trae_duplicidad(patch_clients):
    patch_clients["rxnorm"].side_effect = ["1", "2"]
    patch_clients["duplicity"].return_value = {
        "duplicities": [{"layer": "substance"}], "duplicities_suppressed": [],
        "duplicity_not_evaluated": [], "duplicity_warnings": []}
    prods = [{"id": "p1", "substances": ["paracetamol"]},
             {"id": "p2", "substances": ["paracetamol", "codeina"]}]
    out = await interaction_checker.check(["paracetamol", "codeina"], products=prods)
    assert patch_clients["duplicity"].call_args.args[1] == prods
    assert out["duplicities"] == [{"layer": "substance"}]
    assert out["safe"] is False


async def test_si_la_duplicidad_falla_las_interacciones_salen_igual(patch_clients):
    patch_clients["rxnorm"].side_effect = ["1", "2"]
    patch_clients["duplicity"].side_effect = RuntimeError("boom")
    out = await interaction_checker.check(["A", "B"])
    assert out["duplicities"] == [] and out["duplicity_warnings"]


async def test_drugs_con_mayusculas_distintas_no_rompe_duplicidad(patch_clients):
    patch_clients["rxnorm"].side_effect = ["1", "2"]
    out = await interaction_checker.check(["A", "a", "B"])
    assert out["duplicities"] == []
