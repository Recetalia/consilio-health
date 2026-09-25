"""classes_for cuando la tabla drug_class no existe: None, no {} ni excepción."""
from __future__ import annotations

import sqlite3

from app.clients.recetalia_db import RecetaliaDatabase


async def test_classes_for_none_si_no_existe_la_tabla(tmp_path):
    db_path = tmp_path / "sin_drug_class.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """create table drug (
            drug_id    integer primary key,
            canonical  text    not null unique,
            rxcui      text,
            ddinter_id text    unique,
            atc        text,
            source     text    not null,
            created_at text    not null
        )"""
    )
    conn.execute(
        "insert into drug (drug_id, canonical, source, created_at) "
        "values (1, 'Diazepam', 'recetalia', '2026-01-01')"
    )
    conn.commit()
    conn.close()

    db = RecetaliaDatabase(db_path=str(db_path))
    try:
        assert await db.classes_for([1]) is None
    finally:
        await db.close()
