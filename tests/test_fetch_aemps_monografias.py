"""ETL de monografías con un CIMA falso: universo DNMA, elección de referencia y guardado."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.fetch_aemps_monografias import cargar, elegir_referencia  # noqa: E402

FICHA = {"tipo": 1, "secc": True, "fecha": 1739316132000}


def _pres(nreg, vtm, oral=True, comerc=True, ficha=True):
    return {"nregistro": nreg, "nombre": f"MED {nreg}", "comerc": comerc, "vtm": {"nombre": vtm},
            "viasAdministracion": [{"nombre": "VÍA ORAL" if oral else "VÍA INTRAVENOSA"}],
            "docs": [FICHA] if ficha else []}


class CimaFalso:
    def __init__(self):
        self.por_principio = {
            "paracetamol": [_pres("90000", "paracetamol", oral=False), _pres("85780", "paracetamol"),
                            _pres("70000", "paracetamol", ficha=False),
                            _pres("89654", "paracetamol + ibuprofeno"),
                            _pres("50000", "paracetamol + codeína")],         # codeína no está en el DNMA
            "ibuprofeno": [_pres("89654", "paracetamol + ibuprofeno"), _pres("60000", "ibuprofeno", comerc=False)],
        }
        self.pedidas_secciones = []

    def presentaciones(self, principio):
        return self.por_principio.get(principio.lower(), [])

    def medicamento(self, nregistro):
        return {"atcs": [{"codigo": "N02B", "nombre": "OTROS ANALGESICOS Y ANTIPIRETICOS", "nivel": 3},
                         {"codigo": "N02BE01", "nombre": "Paracetamol", "nivel": 5}]}

    def secciones(self, nregistro):
        self.pedidas_secciones.append(nregistro)
        return [{"seccion": "4.1", "titulo": "Indicaciones terapéuticas",
                 "contenido": '<p style="x">Dolor leve.</p>'},
                {"seccion": "4.7", "titulo": "Conducción", "contenido": "<p>No.</p>"}]


def _db(tmp_path):
    db = sqlite3.connect(tmp_path / "m.db")
    db.executescript("""
        create table meta (key text primary key, value text);
        create table dnma_substance_map (sustancia_id text primary key, sustancia_dsc text);
        insert into dnma_substance_map values ('1', 'Paracetamol'), ('2', 'Ibuprofeno');
    """)
    return db


def test_elegir_referencia_prefiere_oral_con_ficha_y_menor_registro():
    ref = elegir_referencia([_pres("90000", "p", oral=False), _pres("85780", "p"), _pres("70000", "p", ficha=False),
                             _pres("99999", "p")])
    assert ref["nregistro"] == "85780"
    assert elegir_referencia([_pres("1", "p", ficha=False)]) is None


def test_cargar_arma_composiciones_del_dnma_y_guarda_secciones(tmp_path):
    db = _db(tmp_path)
    cima = CimaFalso()
    cuenta = cargar(db, cima)

    filas = {r[0]: r for r in db.execute(
        "select composicion, estado, nregistro, atc_codigo, atc_grupo, principios_activos, fecha_ficha from monografia")}
    # paracetamol, ibuprofeno+paracetamol, e ibuprofeno (sólo una presentación NO comercializada)
    assert set(filas) == {"paracetamol", "ibuprofeno+paracetamol", "ibuprofeno"}
    assert "codeina+paracetamol" not in filas            # codeína no existe en el DNMA
    assert filas["paracetamol"][1:5] == ("ok", "85780", "N02BE01", "Otros analgesicos y antipireticos")
    assert json.loads(filas["ibuprofeno+paracetamol"][5]) == ["paracetamol", "ibuprofeno"]
    assert filas["paracetamol"][6] == "2025-02-11"
    assert filas["ibuprofeno"][1] == "sin_referencia"
    assert cuenta == {"ok": 2, "sin_referencia": 1, "error": 0}

    secc = db.execute("select seccion, html from monografia_seccion where composicion='paracetamol'").fetchall()
    assert secc == [("4.1", "<p>Dolor leve.</p>")]        # saneada, 4.7 fuera
    assert db.execute("select value from meta where key='monografias_fuente'").fetchone()[0].startswith("Ficha")


def test_cargar_es_idempotente(tmp_path):
    db = _db(tmp_path)
    cargar(db, CimaFalso())
    cargar(db, CimaFalso())
    assert db.execute("select count(*) from monografia_seccion where composicion='paracetamol'").fetchone()[0] == 1


def test_un_error_en_una_composicion_no_corta_la_corrida(tmp_path):
    class CimaQueFalla(CimaFalso):
        def secciones(self, nregistro):
            if nregistro == "89654":
                raise RuntimeError("timeout")
            return super().secciones(nregistro)

    db = _db(tmp_path)
    cuenta = cargar(db, CimaQueFalla())
    assert cuenta["error"] == 1 and cuenta["ok"] == 1
    assert db.execute("select estado from monografia where composicion='ibuprofeno+paracetamol'").fetchone()[0] == "error"
