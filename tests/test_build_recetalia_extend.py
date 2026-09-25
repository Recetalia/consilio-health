"""`extend` suma fármacos y pares DDInter sin renumerar los que ya existen.

`seed --force` numera por `ddinter_id` ordenado: un fármaco nuevo en el medio
corre los `drug_id` y rompe todo lo derivado que los referencia. Esto fija que
`extend` no lo hace.
"""

from __future__ import annotations

import argparse
import sqlite3

from scripts import build_recetalia_db as b


def _ddinter(path, pairs, xwalk=()):
    con = sqlite3.connect(path)
    con.executescript("""
        create table interactions (drug_a_id, drug_a_name, drug_b_id, drug_b_name,
                                   severity, atc_category);
        create table rxnorm_to_ddinter (rxcui, ddinter_id, canonical_name, match_method);
        create table meta (key primary key, value);
    """)
    con.executemany("insert into interactions values (?,?,?,?,?,'X')", pairs)
    con.executemany("insert into rxnorm_to_ddinter values (?,?,?,'exact')", xwalk)
    con.execute("insert into meta values ('source_release', 'r')")
    con.commit()
    con.close()


def test_extend_conserva_ids_y_agrega_lo_nuevo(tmp_path):
    viejo, nuevo, dst = tmp_path / "v.db", tmp_path / "n.db", tmp_path / "r.db"
    _ddinter(viejo, [("DDInter1", "Alfa", "DDInter3", "Gama", "Major")])
    b.cmd_seed(argparse.Namespace(source=str(viejo), target=str(dst), force=False))
    con = sqlite3.connect(dst)
    antes = dict(con.execute("select ddinter_id, drug_id from drug"))
    # una fila derivada que referencia un drug_id, como las de AEMPS
    con.execute("insert into interaction (drug_a_id, drug_b_id, severity, source) "
                "values (?,?, 'moderate', 'openfda')", (antes["DDInter1"], antes["DDInter3"]))
    con.commit()
    con.close()

    # DDInter2 cae entre los dos existentes: con seed correría a DDInter3
    _ddinter(nuevo, [("DDInter1", "Alfa", "DDInter3", "Gama", "Major"),
                     ("DDInter2", "Beta", "DDInter3", "Gama", "Minor")],
             xwalk=[("99", "DDInter2", "Betamol")])
    assert b.cmd_extend(argparse.Namespace(source=str(nuevo), target=str(dst))) == 0

    con = sqlite3.connect(dst)
    despues = dict(con.execute("select ddinter_id, drug_id from drug"))
    assert {k: despues[k] for k in antes} == antes
    assert despues["DDInter2"] > max(antes.values())
    assert con.execute("select rxcui from drug where ddinter_id='DDInter2'").fetchone() == ("99",)
    alias = {a for (a,) in con.execute(
        "select alias from drug_alias where drug_id=?", (despues["DDInter2"],))}
    assert alias == {"Beta", "Betamol"}
    filas = set(con.execute("select drug_a_id, drug_b_id, severity, source from interaction"))
    lo, hi = sorted((despues["DDInter2"], despues["DDInter3"]))
    assert (lo, hi, "minor", "ddinter") in filas
    assert (antes["DDInter1"], antes["DDInter3"], "moderate", "openfda") in filas
    assert len(filas) == 3

    # idempotente
    assert b.cmd_extend(argparse.Namespace(source=str(nuevo), target=str(dst))) == 0
    assert con.execute("select count(*) from interaction").fetchone()[0] == 3
    con.close()
