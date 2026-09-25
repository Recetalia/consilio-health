"""GET /data/summary: lo que muestra la sección "Los datos".

Dos garantías: con la base real los números son > 0 y las fechas son ISO, y
una key de `meta` ausente da `null` en vez de una fecha inventada.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

DB_PATH = Path(os.environ.get("INTERACTION_DB_PATH", "data/recetalia_interactions.db"))


def _iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


@pytest.fixture
def real_db():
    if not DB_PATH.exists():
        pytest.skip("falta la base")
    from app.clients import recetalia_db
    import asyncio
    asyncio.run(recetalia_db.client.close())
    recetalia_db.client.db_path = str(DB_PATH)
    yield recetalia_db.client
    asyncio.run(recetalia_db.client.close())


def test_endpoint_con_base_real(real_db):
    from app.main import app
    # Sin header de API key: la ruta es pública a propósito.
    with patch.dict(os.environ, {"API_KEY": "test-key"}):
        r = TestClient(app).get("/data/summary")
    assert r.status_code == 200
    d = r.json()

    assert d["drugs"]["total"] > 0
    assert 0 < d["drugs"]["with_spanish_name"] <= d["drugs"]["total"]
    assert 0 < d["drugs"]["spanish_name_pct"] <= 100
    ix = d["interactions"]
    assert ix["total"] > 0 and 0 < ix["distinct_pairs"] <= ix["total"]
    assert sum(ix["by_source"].values()) == ix["total"]
    assert sum(ix["by_severity"].values()) == ix["total"]
    for fuente in ("ddinter", "aemps", "openfda"):
        assert ix["by_source"].get(fuente, 0) > 0
    assert d["duplicity"]["classes"] > 0
    assert d["duplicity"]["curated_exceptions"] > 0
    assert d["condition_alerts"]["total"] > 0
    assert d["geriatric_criteria"] > 0
    assert d["conditions"]["total"] > 0

    s = d["sources"]
    for fuente in ("ddinter", "openfda", "medrt", "aemps", "dnma", "icd10_bridge"):
        assert s[fuente]["updated_at"], fuente
        _iso(s[fuente]["updated_at"])
    for k in ("cross_at", "duplicidad_at", "nombres_es_at"):
        _iso(s["aemps"][k])
    assert s["ddinter"]["release"]


async def test_key_ausente_da_null(tmp_path):
    """Base con el esquema real pero `meta` casi vacía: las fechas que faltan
    son `null`, y ninguna se completa con otra."""
    if not DB_PATH.exists():
        pytest.skip("falta la base")
    src = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    ddl = [r[0] for r in src.execute(
        "select sql from sqlite_master where sql is not null and name not like 'sqlite_%'")]
    src.close()
    path = tmp_path / "mini.db"
    dst = sqlite3.connect(path)
    for stmt in ddl:
        dst.execute(stmt)
    dst.execute("insert into meta values ('recetalia_seeded_at', '2026-09-16T01:21:56+00:00')")
    dst.execute("insert into meta values ('aemps_cross_at', '2026-09-25T17:04:45+00:00')")
    dst.commit()
    dst.close()

    from app.api import data as data_api
    from app.clients.recetalia_db import RecetaliaDatabase
    db = RecetaliaDatabase(str(path))
    with patch.object(data_api.recetalia_db, "client", db):
        s = await data_api.build_sources()
        counts = await db.data_counts()
    await db.close()

    assert s["openfda"] == {"fetched_at": None, "updated_at": None}
    assert s["medrt"]["updated_at"] is None
    assert s["dnma"]["updated_at"] is None
    assert s["icd10_bridge"]["updated_at"] is None
    # DDInter sin `extended_at`: cae a `seeded_at`, que sí existe.
    assert s["ddinter"]["extended_at"] is None
    assert s["ddinter"]["updated_at"] == "2026-09-16T01:21:56+00:00"
    assert s["ddinter"]["release"] is None
    # AEMPS: sólo uno de sus pasos dejó fecha, y es la que se muestra.
    assert s["aemps"]["duplicidad_at"] is None
    assert s["aemps"]["updated_at"] == "2026-09-25T17:04:45+00:00"
    # Base vacía: conteos en cero, sin dividir por cero.
    assert counts["drugs"] == {"total": 0, "with_spanish_name": 0,
                               "spanish_name_pct": 0.0, "with_rxcui": 0}
