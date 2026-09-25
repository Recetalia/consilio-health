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


def anclas(cx, canonical_like):
    """Clases donde el fármaco entra como 'ancla' (viene de `atc_a`).

    Dos miembros ('atc_b') de la misma clase no son duplicidad entre sí: la
    regla AEMPS dice "un producto de atc_b duplica a atc_a", no que atc_b sea
    intercambiable consigo mismo.
    """
    return {r[0] for r in cx.execute(
        "select class_id from drug_class dc join drug d using(drug_id) "
        "where d.canonical like ? and dc.rol = 'ancla'", (canonical_like,))}


def test_benzodiacepinas_comparten_clase(cx):
    assert "N05BA" in clases(cx, "Diazepam") & clases(cx, "Lorazepam")


def test_benzodiacepinas_son_ancla(cx):
    assert "N05BA" in anclas(cx, "Diazepam") & anclas(cx, "Lorazepam")


def test_isrs_comparten_clase(cx):
    assert "N06AB" in clases(cx, "Sertraline") & clases(cx, "Fluoxetine")


def test_isrs_son_ancla(cx):
    assert "N06AB" in anclas(cx, "Sertraline") & anclas(cx, "Fluoxetine")


def test_corticoides_ancla_solo_en_su_propia_clase(cx):
    """Medido 2026-09-24 sin rol: prednisona/dexametasona compartían H02AA Y
    H02AB (alertaba dos veces). Como miembros ('atc_b') de reglas ancladas en
    otro corticoide, comparten ambas clases; como ancla, sólo H02AB."""
    pred, dexa = anclas(cx, "Prednisone"), anclas(cx, "Dexamethasone")
    assert "H02AB" in pred & dexa
    assert "H02AA" not in pred and "H02AA" not in dexa


def test_bifosfonatos_ancla_solo_en_m05ba(cx):
    """Medido 2026-09-24 sin rol: alendronato/risedronato compartían G03XC,
    H05AA, H05BA y M05BA (alertaba cuatro veces). Como ancla, sólo M05BA."""
    ale = anclas(cx, "Alendron%")
    rise = anclas(cx, "Risedron%")
    assert "M05BA" in ale & rise
    for cid in ("G03XC", "H05AA", "H05BA"):
        assert cid not in ale and cid not in rise


def test_ieca_aca_y_tiazida_no_comparten_clase(cx):
    """El falso positivo canónico: combinación intencional de primera línea."""
    e, a, h = clases(cx, "Enalapril"), clases(cx, "Amlodipine"), clases(cx, "Hydrochlorothiazide")
    assert not (e & a) and not (e & h) and not (a & h), (e, a, h)


def test_la_tiazida_no_entra_a_los_ara2_por_el_atc_del_combinado(cx):
    assert not (clases(cx, "Losartan") & clases(cx, "Hydrochlorothiazide"))
