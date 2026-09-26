"""`drug_input`: a qué nombre de ENTRADA corresponde cada hallazgo.

`drug` es el canónico en inglés ("Metformin"). Recetalia manda "metformina"
y tiene que volver al producto que la contiene; sin el nombre de entrada, el
mapeo depende de adivinar la traducción. Es aditivo: `drug` no cambia.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

DB_PATH = Path(os.environ.get("INTERACTION_DB_PATH", "data/recetalia_interactions.db"))


@pytest.fixture
async def db():
    if not DB_PATH.exists():
        pytest.skip("falta la base")
    from app.clients import recetalia_db
    await recetalia_db.client.close()
    recetalia_db.client.db_path = str(DB_PATH)
    yield recetalia_db.client
    await recetalia_db.client.close()


async def _check(drugs, **perfil):
    from app.services import contraindication_checker as cc
    from app.services.patient_profile import PatientProfile
    return await cc.check(drugs, PatientProfile(**perfil))


async def test_contraindicacion_trae_el_nombre_de_entrada(db):
    r = await _check(["metformina"], funcion_renal="grave")
    hit = next(c for c in r["contraindications"] if c["drug"] == "Metformin")
    assert hit["drug_input"] == "metformina"
    assert "detail" in hit


async def test_geriatrica_trae_el_nombre_de_entrada(db):
    r = await _check(["ibuprofeno"], edad=80)
    assert r["geriatric"]
    assert all(g["drug_input"] == "ibuprofeno" for g in r["geriatric"])
    assert all("drug_id" not in g for g in r["geriatric"])


async def test_alergia_trae_el_nombre_de_entrada(db):
    r = await _check(["aspirina"], alergias=["acetylsalicylic acid", "nosequeesto"])
    exact = [a for a in r["allergies"] if a["match"] == "exact"]
    assert exact and exact[0]["drug_input"] == "aspirina"
    unresolved = [a for a in r["allergies"] if a["match"] == "unresolved"]
    assert unresolved and unresolved[0]["drug_input"] is None


async def test_no_evaluado_trae_el_nombre_de_entrada(db):
    r = await _check(["xyzfoo"])
    assert r["not_evaluated"][0]["drug_input"] == "xyzfoo"


async def test_dos_nombres_del_mismo_farmaco_salen_los_dos(db):
    """`aspirina` y `aspirin` son el mismo drug_id: cada nombre de entrada es
    un producto distinto del lado de Recetalia y los dos tienen que enterarse."""
    r = await _check(["aspirina", "aspirin"], edad=80)
    if not r["geriatric"]:
        pytest.skip("la aspirina no tiene criterios geriátricos en esta base")
    assert {g["drug_input"] for g in r["geriatric"]} == {"aspirina", "aspirin"}


def test_el_contrato_http_lo_expone(monkeypatch):
    if not DB_PATH.exists():
        pytest.skip("falta la base")
    monkeypatch.setenv("API_KEY", "test-local")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        r = c.post("/contraindications",
                   json={"drugs": ["metformina"], "profile": {"funcion_renal": "grave"}},
                   headers={"X-API-Key": "test-local"})
    assert r.status_code == 200, r.text
    assert r.json()["contraindications"][0]["drug_input"] == "metformina"
