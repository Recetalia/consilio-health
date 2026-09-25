"""Gate: las 6 categorías ATC de DDInter que faltaban (C, G, J, M, N, S).

Hasta 2026-09-25 sólo se cargaban A B D H L P R V, por un comentario que decía
que las otras seis no estaban publicadas. Sí lo estaban. Sin ellas, pares graves
clásicos llegaban sólo desde openFDA, con severidad `unknown`. Los tres de acá
figuran como Major en los CSV C y N; si alguien vuelve a achicar
`ATC_CATEGORIES`, o re-siembra con un artefacto viejo, salen de nuevo "Revisar".
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

DB_PATH = Path(os.environ.get("INTERACTION_DB_PATH", "data/recetalia_interactions.db"))

# (nombre en castellano, nombre en castellano, categoría DDInter de donde sale)
PARES_GRAVES = [
    ("tramadol", "fluoxetina", "N"),
    ("amiodarona", "digoxina", "C"),
    ("sildenafilo", "nitroglicerina", "C"),
]


@pytest.fixture
async def db():
    if not DB_PATH.exists():
        pytest.skip("falta la base")
    from app.clients import recetalia_db
    await recetalia_db.client.close()
    recetalia_db.client.db_path = str(DB_PATH)
    yield recetalia_db.client
    await recetalia_db.client.close()


@pytest.mark.parametrize(("a", "b", "cat"), PARES_GRAVES)
async def test_par_grave_sale_major_desde_ddinter(db, a, b, cat):
    ia, ib = await db.drug_id_by_name(a), await db.drug_id_by_name(b)
    assert ia and ib, f"{a} o {b} no resuelven por su nombre en castellano"
    hit = await db.lookup_pair(ia, ib)
    assert hit, f"sin interacción para {a} + {b}"
    assert hit["severity"] == "major", (
        f"{a} + {b}: llegó {hit['severity']} desde {hit.get('severity_source')}; "
        f"¿falta la categoría {cat} de DDInter?")
    # `severity_source` sólo viene cuando difiere de la fila base (`source`).
    assert hit.get("severity_source", hit["source"]) == "ddinter", hit


def test_se_cargan_las_14_categorias():
    from scripts import ddinter_sources
    assert set(ddinter_sources.ATC_CATEGORIES) == set("ABCDGHJLMNPRSV")


async def test_el_endpoint_los_da_como_graves(monkeypatch):
    if not DB_PATH.exists():
        pytest.skip("falta la base")
    monkeypatch.setenv("API_KEY", "test-local")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        for a, b, _ in PARES_GRAVES:
            r = c.post("/interactions", json={"drugs": [a, b]},
                       headers={"X-API-Key": "test-local"})
            assert r.status_code == 200, r.text
            hits = r.json()["interactions"]
            assert hits, f"sin interacción para {a} + {b}"
            assert hits[0]["severity"] == "major", (a, b, hits[0])
