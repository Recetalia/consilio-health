"""Nombres en castellano de la CIE-10-ES: ETL (`scripts/load_cie10es.py`) y búsqueda del autocompletado."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from app.clients.recetalia_db import RecetaliaDatabase, norm_texto

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from load_cie10es import aplicar, nombres_desde_filas, normalizar, titulo_capitulo  # noqa: E402


def test_normalizar_saca_tildes_y_mayusculas_igual_que_el_runtime():
    assert normalizar("Trastorno de Glándula  Suprarrenal") == "trastorno de glandula suprarrenal"
    assert normalizar("Pingüécula") == norm_texto("Pingüécula") == "pinguecula"


def test_titulo_capitulo():
    assert titulo_capitulo("ENFERMEDADES DEL SISTEMA NERVIOSO (G00-G99)") == "Enfermedades del sistema nervioso"


def test_nombres_desde_filas_toma_codigos_y_el_rango_de_los_capitulos():
    nombres = nombres_desde_filas([
        ("Código", "Descripción"),  # el encabezado no tiene forma de código: queda como fila más, no molesta
        ("Cap.06", "ENFERMEDADES DEL SISTEMA NERVIOSO (G00-G99)"),
        ("E00-E07", "TRASTORNOS DE GLÁNDULA TIROIDES (E00-E07)"),
        ("E27.9", "Trastorno de glándula suprarrenal, no especificado"),
        ("M10.311", "Gota debida a insuficiencia renal, hombro derecho"),
        (None, None),
    ])
    assert nombres["E00-E07"] == "Trastornos de glándula tiroides"
    assert nombres["G00-G99"] == "Enfermedades del sistema nervioso"
    assert nombres["E27.9"].startswith("Trastorno de glándula")
    assert nombres["M10.311"].endswith("hombro derecho")


def _base(tmp_path) -> Path:
    path = tmp_path / "cie.db"
    db = sqlite3.connect(path)
    db.executescript("""
        create table condition (condition_id integer primary key, code_system text, code text, name text);
        create table icd10_descendant (code text primary key, name text, anchor_code text);
        create table condition_xref (from_id integer, to_id integer);
        create table drug_condition_alert (condition_id integer);
        create table meta (key text primary key, value text);
        insert into condition values (1, 'icd10cm', 'E27.9', 'Disorder of adrenal gland, unspecified');
        insert into condition values (2, 'icd10cm', 'M10', 'Gout');
        insert into condition values (3, 'mesh', 'D006073', 'Gout');
        insert into icd10_descendant values ('M10.311', 'Gout due to renal impairment, right shoulder', 'M10');
        insert into icd10_descendant values ('G35.A', 'Relapsing-remitting multiple sclerosis', 'G35');
    """)
    db.commit()
    db.close()
    return path


NOMBRES = {
    "E27.9": "Trastorno de glándula suprarrenal, no especificado",
    "M10": "Gota",
    "M10.311": "Gota debida a insuficiencia renal, hombro derecho",
}


def test_aplicar_escribe_castellano_y_deja_en_null_lo_que_la_fuente_no_trae(tmp_path):
    path = _base(tmp_path)
    db = sqlite3.connect(path)
    resultado = aplicar(db, NOMBRES)
    db.commit()
    assert resultado == {"condition": (2, 2), "icd10_descendant": (1, 2)}
    # La fila MeSH no se toca; el código CMS sin traducción oficial queda sin nombre en castellano.
    assert db.execute("select name_es from condition where code_system='mesh'").fetchone()[0] is None
    assert db.execute("select name_es from icd10_descendant where code='G35.A'").fetchone()[0] is None
    assert db.execute("select name_es_norm from condition where code='E27.9'").fetchone()[0] == \
        "trastorno de glandula suprarrenal, no especificado"


async def test_busqueda_muestra_castellano_y_encuentra_sin_tildes(tmp_path):
    path = _base(tmp_path)
    db = sqlite3.connect(path)
    aplicar(db, NOMBRES)
    db.commit()
    db.close()

    cliente = RecetaliaDatabase(db_path=str(path))
    try:
        por_es = await cliente.search_conditions("glandula", 10)
        assert [(r["code"], r["name"]) for r in por_es] == [
            ("E27.9", "Trastorno de glándula suprarrenal, no especificado")]

        por_codigo = {r["code"]: r["name"] for r in await cliente.search_conditions("M10", 10)}
        assert por_codigo["M10.311"] == "Gota debida a insuficiencia renal, hombro derecho"

        # Sin traducción oficial: el nombre en inglés, nunca uno inventado.
        sin_es = await cliente.search_conditions("G35", 10)
        assert sin_es[0]["name"] == "Relapsing-remitting multiple sclerosis"

        # El inglés sigue encontrando (hay médicos que lo buscan así).
        assert [r["code"] for r in await cliente.search_conditions("adrenal", 10)] == ["E27.9"]
    finally:
        await cliente.close()


async def test_base_vieja_sin_columnas_sigue_funcionando_en_ingles(tmp_path):
    cliente = RecetaliaDatabase(db_path=str(_base(tmp_path)))
    try:
        r = await cliente.search_conditions("E27", 10)
        assert r[0]["name"] == "Disorder of adrenal gland, unspecified"
    finally:
        await cliente.close()
