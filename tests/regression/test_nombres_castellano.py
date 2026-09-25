"""Recetalia manda las sustancias del DNMA en castellano; tienen que resolver.

Medido 2026-09-24: `diclofenaco` no resolvía por `drug_alias` y `amlodipino`
sólo aparecía en `dnma_substance_map`. Sin resolver no hay interacción ni
duplicidad: el fármaco queda afuera en silencio.
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


async def _canon(db, nombre):
    did = await db.drug_id_by_name(nombre)
    assert did, f"{nombre} no resolvió"
    return (await db.canonicals_for([did]))[did]


async def test_por_esqueleto(db):
    assert await _canon(db, "diclofenaco") == "Diclofenac"


async def test_por_mapa_del_dnma(db):
    assert await _canon(db, "amlodipino") == "Amlodipine"


async def test_lo_que_ya_resolvia_no_cambia(db):
    assert await _canon(db, "LOSARTAN POTASICO") == "Losartan"
    assert await _canon(db, "paracetamol") == "Acetaminophen"


async def test_un_nombre_inexistente_sigue_sin_resolver(db):
    assert await db.drug_id_by_name("zzzz no existe") is None


async def test_homonimo_genuino_sigue_sin_resolver(db):
    """'vitamina' esqueletiza a 'vitamin', que tiene 2 drug_id sin paréntesis
    de por medio (no es un caso de vía/forma): sigue bloqueado a propósito.
    """
    assert await db.drug_id_by_name("vitamina") is None
