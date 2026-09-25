"""Matching de nombres AEMPS contra el esqueleto del canónico, sin base."""
import sys

sys.path.insert(0, "scripts")
from enrich_nombres_aemps import asignar_nombres, indice_canonico  # noqa: E402

CANONICOS = {
    1: "Acarbose",
    2: "Nitroglycerin",
    3: "Diclofenac",
    4: "Diclofenac (topical)",
    5: "Diclofenac (horse)",     # vía no traducible: no se asigna
    6: "Vitamin A",
    7: "Vitamin E",               # mismo esqueleto que Vitamin A ("vitamin")
}


def test_match_exacto():
    idx = indice_canonico(CANONICOS)
    out = asignar_nombres(["Acarbosa"], idx)
    assert out == {1: "Acarbosa"}


def test_combinacion_descartada():
    idx = indice_canonico(CANONICOS)
    out = asignar_nombres(["Nitroglicerina y otros vasodilatadores"], idx)
    assert 2 not in out


def test_token_corto_descartado():
    idx = indice_canonico(CANONICOS)
    out = asignar_nombres(["Vitamina A"], idx)
    assert 6 not in out


def test_ambiguedad_descartada():
    """'Vitamin A' y 'Vitamin E' comparten esqueleto ('vitamin'): un nombre
    AEMPS que cayera ahí no sabría a cuál de los dos asignarse."""
    idx = indice_canonico(CANONICOS)
    out = asignar_nombres(["Vitamin"], idx)
    assert 6 not in out and 7 not in out


def test_variante_topica():
    idx = indice_canonico(CANONICOS)
    out = asignar_nombres(["Diclofenaco"], idx)
    assert out[3] == "Diclofenaco"
    assert out[4] == "Diclofenaco (tópico)"


def test_via_sin_traduccion_no_se_asigna():
    idx = indice_canonico(CANONICOS)
    out = asignar_nombres(["Diclofenaco"], idx)
    assert 5 not in out


def test_dos_nombres_aemps_distintos_no_se_asignan():
    """'Acarbosa' y 'Acarboso' normalizan distinto pero comparten esqueleto
    ('acarbos'): no hay un nombre único que asignarle al canónico."""
    idx = indice_canonico({1: "Acarbose"})
    out = asignar_nombres(["Acarbosa", "Acarboso"], idx)
    assert 1 not in out


def test_normalizacion_igual_cuenta_como_el_mismo_nombre():
    """'Nitroglicerina' y 'Nitroglicerina clorhidrato' normalizan igual (la
    sal se descarta): no es una ambigüedad, es el mismo nombre repetido."""
    idx = indice_canonico({2: "Nitroglycerin"})
    out = asignar_nombres(["Nitroglicerina", "Nitroglicerina clorhidrato"], idx)
    assert out[2] == "Nitroglicerina"


def test_correr_dos_veces_no_borra_los_nombres(tmp_path, monkeypatch):
    """La segunda corrida tiene que dejar lo mismo que la primera.

    Medido 2026-09-25: las filas propias contaban como "ya existentes", así que
    la re-corrida las filtraba, borraba las 967 y escribía sólo las nuevas (14).
    """
    import sqlite3

    import enrich_nombres_aemps as m

    db = tmp_path / "r.db"
    con = sqlite3.connect(db)
    con.executescript("""
        create table drug (drug_id integer primary key, canonical text);
        create table drug_alias (drug_id, alias, alias_norm, lang, source
            check (source in ('ddinter','rxnorm','dnma','manual','aemps')),
            primary key (drug_id, alias_norm));
        create table dnma_substance_map (drug_id);
        create table meta (key primary key, value);
    """)
    con.executemany("insert into drug values (?,?)", CANONICOS.items())
    con.commit()
    con.close()
    for f in ("atc.xml", "pa.xml"):
        (tmp_path / f).write_text("")
    monkeypatch.setattr(m, "nombres_candidatos",
                        lambda *_: ["Acarbosa", "Nitroglicerina"])
    monkeypatch.setattr(sys, "argv", ["x", "--db", str(db), "--dicc-atc",
                                      str(tmp_path / "atc.xml"), "--dicc-principios",
                                      str(tmp_path / "pa.xml")])

    def aemps():
        c = sqlite3.connect(db)
        try:
            return set(c.execute("select drug_id, alias from drug_alias where source='aemps'"))
        finally:
            c.close()

    m.main()
    primera = aemps()
    assert primera == {(1, "Acarbosa"), (2, "Nitroglicerina")}
    m.main()
    assert aemps() == primera
