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
