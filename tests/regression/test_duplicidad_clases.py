"""Las membresías que deciden si el módulo sirve o se ignora.

Cada assert es un falso positivo medido o un caso que tiene que alertar.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

DB_PATH = Path(os.environ.get("INTERACTION_DB_PATH", "data/recetalia_interactions.db"))


@pytest.fixture
def cx():
    if not DB_PATH.exists():
        pytest.skip("falta la base")
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    if not c.execute("select 1 from sqlite_master where name='drug_class'").fetchone():
        pytest.skip("drug_class no cargada: correr scripts/cross_aemps_duplicidad.py")
    yield c
    c.close()


def clases(cx, canonical):
    return {r[0] for r in cx.execute(
        "select class_id from drug_class dc join drug d using(drug_id) "
        "where d.canonical = ?", (canonical,))}


def test_benzodiacepinas_comparten_clase(cx):
    assert "N05BA" in clases(cx, "Diazepam") & clases(cx, "Lorazepam")


def test_isrs_comparten_clase(cx):
    assert "N06AB" in clases(cx, "Sertraline") & clases(cx, "Fluoxetine")


def test_ieca_aca_y_tiazida_no_comparten_clase(cx):
    """El falso positivo canónico: combinación intencional de primera línea."""
    e, a, h = clases(cx, "Enalapril"), clases(cx, "Amlodipine"), clases(cx, "Hydrochlorothiazide")
    assert not (e & a) and not (e & h) and not (a & h), (e, a, h)


def test_la_tiazida_no_entra_a_los_ara2_por_el_atc_del_combinado(cx):
    assert not (clases(cx, "Losartan") & clases(cx, "Hydrochlorothiazide"))
