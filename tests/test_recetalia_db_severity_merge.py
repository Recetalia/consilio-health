"""lookup_pair: si DDInter gradúa un par y openFDA lo trae `unknown`, gana la gradación.

Es el bug de 2026-09-25: sildenafilo + nitroglicerina, fluoxetina + tramadol y
amiodarona + digoxina salían "sin graduar" porque sólo los traía openFDA. Con las
14 categorías de DDInter llegan también como Major; este test fija que el merge
no deje que el `unknown` de openFDA los tape, sin depender de la base real (el
gate de `tests/regression/test_ddinter_categorias.py` se saltea si no está).
"""
from __future__ import annotations

import sqlite3

import pytest

from app.clients.recetalia_db import RecetaliaDatabase

PARES = [
    ("Sildenafil", "Nitroglycerin"),
    ("Fluoxetine", "Tramadol"),
    ("Amiodarone", "Digoxin"),
]


@pytest.fixture
async def db(tmp_path):
    path = tmp_path / "merge.db"
    con = sqlite3.connect(path)
    con.executescript("""
        create table drug (drug_id integer primary key, canonical text not null unique);
        create table interaction (
            drug_a_id integer not null, drug_b_id integer not null,
            severity text not null, mechanism text, management text, evidence text,
            source text not null, reviewed_by text, reviewed_at text, note text,
            primary key (drug_a_id, drug_b_id, source));
    """)
    ids = {}
    for a, b in PARES:
        for n in (a, b):
            ids[n] = con.execute("insert into drug (canonical) values (?)", (n,)).lastrowid
        lo, hi = sorted((ids[a], ids[b]))
        # openFDA primero en disco: el orden de inserción no puede decidir.
        con.execute("insert into interaction (drug_a_id, drug_b_id, severity, evidence, source) "
                    "values (?, ?, 'unknown', 'label sentence', 'openfda')", (lo, hi))
        con.execute("insert into interaction (drug_a_id, drug_b_id, severity, source) "
                    "values (?, ?, 'major', 'ddinter')", (lo, hi))
    # Control: un par que sólo trae openFDA sigue `unknown` (no se inventa gravedad).
    x = con.execute("insert into drug (canonical) values ('Xdrug')").lastrowid
    y = con.execute("insert into drug (canonical) values ('Ydrug')").lastrowid
    con.execute("insert into interaction (drug_a_id, drug_b_id, severity, source) "
                "values (?, ?, 'unknown', 'openfda')", (x, y))
    con.commit()
    con.close()
    d = RecetaliaDatabase(db_path=str(path))
    d.test_ids = ids | {"Xdrug": x, "Ydrug": y}
    yield d
    await d.close()


@pytest.mark.parametrize(("a", "b"), PARES)
async def test_ddinter_major_gana_a_openfda_unknown(db, a, b):
    ids = db.test_ids
    for x, y in ((ids[a], ids[b]), (ids[b], ids[a])):
        hit = await db.lookup_pair(x, y)
        assert hit["severity"] == "major", hit
        assert hit.get("severity_source", hit["source"]) == "ddinter", hit
        assert hit["uncertain"] is False, hit


async def test_solo_openfda_sigue_unknown(db):
    hit = await db.lookup_pair(db.test_ids["Xdrug"], db.test_ids["Ydrug"])
    assert hit["severity"] == "unknown"
    assert hit["source"] == "openfda"
    assert hit["uncertain"] is True
