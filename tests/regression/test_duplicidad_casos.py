"""Casos clínicos de duplicidad contra la base real.

Es la misma lista que corre `scripts/eval_duplicidad.py` como métrica: un caso
que se rompe acá es un falso positivo o un falso negativo en producción.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.services.duplicity_checker import chequear, cumple

DB_PATH = Path(os.environ.get("INTERACTION_DB_PATH", "data/recetalia_interactions.db"))
CASOS = json.load(open(Path(__file__).parent / "casos_duplicidad.json", encoding="utf-8"))


@pytest.fixture
async def db():
    if not DB_PATH.exists():
        pytest.skip("falta la base")
    from app.clients import recetalia_db
    await recetalia_db.client.close()
    recetalia_db.client.db_path = str(DB_PATH)
    yield recetalia_db.client
    await recetalia_db.client.close()


@pytest.mark.parametrize("caso", CASOS, ids=[c["nombre"] for c in CASOS])
async def test_caso(db, caso):
    productos = [{"id": f"p{i}", "substances": s} for i, s in enumerate(caso["productos"])]
    out = await chequear(db, productos)
    assert not out["duplicity_not_evaluated"], f"no resolvieron: {out['duplicity_not_evaluated']}"
    ok, motivo = cumple(out, caso["esperado"])
    assert ok, motivo


async def test_interactions_endpoint_devuelve_duplicidad(monkeypatch):
    """End-to-end de `POST /interactions` con `products`, contra la base real
    (no mockeada): que el contrato de la Task 8 dispare `duplicity_checker` de
    punta a punta y no sólo por unit test con el servicio mockeado.

    Mismo patrón que `test_aemps_cross.py::test_el_endpoint_no_revienta_con_una_fuente_nueva`:
    `TestClient(app)` real, con `API_KEY` puesta por `monkeypatch` y mandada por
    header. `recetalia_db.client` toma `INTERACTION_DB_PATH` al importar el
    módulo (nivel de módulo, ver `app/clients/recetalia_db.py`), que ya está
    fijo por el comando de la suite — no hace falta el fixture `db` de este
    archivo, que reapunta `db_path` a mano para los tests que llaman a
    `chequear` directo.
    """
    if not DB_PATH.exists():
        pytest.skip("falta la base")
    monkeypatch.setenv("API_KEY", "test-local")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        r = c.post("/interactions", json={"products": [
            {"id": "p1", "substances": ["diazepam"]},
            {"id": "p2", "substances": ["lorazepam"]},
        ]}, headers={"X-API-Key": "test-local"})
    assert r.status_code == 200, r.text
    assert r.json()["duplicities"][0]["class_id"] == "N05BA"
