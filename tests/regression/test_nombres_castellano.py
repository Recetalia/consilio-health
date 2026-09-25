"""Recetalia manda las sustancias del DNMA en castellano; tienen que resolver.

Medido 2026-09-24: `diclofenaco` no resolvía por `drug_alias` y `amlodipino`
sólo aparecía en `dnma_substance_map`. Sin resolver no hay interacción ni
duplicidad: el fármaco queda afuera en silencio.
"""
from __future__ import annotations

import os
import sqlite3
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


async def test_vitamina_c_no_resuelve_a_phylloquinone(db):
    """Medido 2026-09-25: 'vitamina c' resolvía por esqueleto a Phylloquinone
    (vitamina K) -`skeleton()` mapea k->c-. No hay alias exacto para
    'vitamina c' ni para 'ácido ascórbico' en la base real (verificado), así
    que lo correcto hoy es `None`; si en el futuro se carga ese alias, este
    test tiene que empezar a exigir el fármaco correcto, no Phylloquinone.
    """
    assert await db.drug_id_by_name("vitamina c") is None


async def test_vitamina_k_no_resuelve_a_otra_cosa(db):
    did = await db.drug_id_by_name("vitamina k")
    if did is not None:
        assert (await db.canonicals_for([did]))[did] == "Phylloquinone"


def _base_temporal_homonimo(tmp_path) -> str:
    """Arma una base mínima con dos fármacos cuyos alias colisionan por
    esqueleto sin paréntesis ni tokens de <=2 caracteres de por medio: la
    ambigüedad genuina que el guard de "un solo candidato" tiene que seguir
    bloqueando.

    Hace falta armarla a mano porque, medido sobre la base real tras excluir
    los tokens cortos del índice, no queda NINGÚN homónimo natural (0
    ambiguos): los 5 que había (`vitamin`, `vitamin d`, `iodid i`,
    `interferon alf n`, `iobenguan i`) tenían todos un token corto y ahora
    quedan afuera del índice por esa regla, no por la de un solo candidato.

    `Calitiazina` / `Calitiazine` son sintéticos -no existen en la base
    real-, elegidos porque `skeleton()` recorta igual la vocal final de las
    dos ("calitiazin"), sin usar ninguna letra suelta.
    """
    path = tmp_path / "homonimo.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        create table drug (
            drug_id integer primary key, canonical text not null unique,
            rxcui text, ddinter_id text unique, atc text,
            source text not null, created_at text not null
        );
        create table drug_alias (
            drug_id integer not null references drug(drug_id),
            alias text not null, alias_norm text not null,
            lang text not null default 'en', source text not null,
            primary key (drug_id, alias_norm)
        );
        create table dnma_substance_map (
            sustancia_id text primary key, sustancia_dsc text not null,
            drug_id integer references drug(drug_id), match_method text not null,
            match_score integer, note text, updated_at text not null
        );
        """
    )
    conn.executemany(
        "insert into drug values (?,?,?,?,?,?,?)",
        [
            (9001, "Calitiazina Sistemica", None, None, None, "recetalia", "2026-01-01"),
            (9002, "Calitiazine Topical", None, None, None, "recetalia", "2026-01-01"),
        ],
    )
    conn.executemany(
        "insert into drug_alias values (?,?,?,?,?)",
        [
            (9001, "Calitiazina", "calitiazina", "es", "manual"),
            (9002, "Calitiazine", "calitiazine", "es", "manual"),
        ],
    )
    conn.commit()
    conn.close()
    return str(path)


async def test_alergia_diclofenaco_matchea_diclofenac_recetado(db):
    """La alergia se declara en castellano ('diclofenaco') y el fármaco
    recetado llega en inglés ('Diclofenac'): tienen que resolver al mismo
    drug_id y salir como alerta de alergia exacta, no como 'unresolved'."""
    from app.services import contraindication_checker as cc
    from app.services.patient_profile import PatientProfile

    r = await cc.check(["Diclofenac"], PatientProfile(alergias=["diclofenaco"]))
    exactas = [a for a in r["allergies"] if a["match"] == "exact"]
    assert exactas, f"no matcheó: {r['allergies']}"
    assert exactas[0]["drug"] == "Diclofenac"
    assert exactas[0]["declared_as"] == "diclofenaco"


async def test_amlodipino_recetado_no_queda_sin_evaluar(db):
    """'amlodipino' sólo resolvía por `dnma_substance_map` (medido 2026-09-24,
    ver docstring del módulo). Antes de ese fix quedaba en `not_evaluated`."""
    from app.services import contraindication_checker as cc
    from app.services.patient_profile import PatientProfile

    r = await cc.check(["amlodipino"], PatientProfile())
    assert not any(e.get("drug") == "amlodipino" for e in r["not_evaluated"]), r["not_evaluated"]


async def test_homonimo_sin_tokens_cortos_sigue_sin_resolver(tmp_path):
    from app.clients.recetalia_db import RecetaliaDatabase

    homdb = RecetaliaDatabase(db_path=_base_temporal_homonimo(tmp_path))
    try:
        # 'Calitiazino' no es ninguno de los dos alias guardados (que
        # normalizan a 'calitiazina'/'calitiazine'): sólo puede resolver por
        # esqueleto, y los dos drug_id comparten el mismo ('calitiazin').
        assert await homdb.drug_id_by_name("Calitiazino") is None
    finally:
        await homdb.close()
