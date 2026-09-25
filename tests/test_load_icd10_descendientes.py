"""ETL de subcódigos CIE-10: `scripts/load_icd10_descendientes.py`, sin base.

Cubre el parseo de ancho fijo del catálogo CMS y la resolución del anclaje
más específico, que es donde vive toda la lógica no trivial del script.
"""
import sys
from pathlib import Path

sys.path.insert(0, "scripts")
from load_icd10_descendientes import (  # noqa: E402
    build_descendants, format_code, longest_anchor, parse_catalog,
)


def test_format_code_inserta_el_punto_en_la_posicion_3():
    assert format_code("N185") == "N18.5"
    assert format_code("N18") == "N18"      # categoría: sin punto
    assert format_code("A1850") == "A18.50"


def test_longest_anchor_elige_el_mas_especifico():
    """`A18.5` prefija a `A1851` igual que `A18`, pero es el más largo: gana."""
    anchors = {"A18": "A18", "A185": "A18.5"}
    assert longest_anchor("A1851", anchors) == "A18.5"


def test_longest_anchor_sin_match():
    assert longest_anchor("Z999", {"A18": "A18"}) is None


def test_longest_anchor_no_matchea_el_propio_codigo():
    """El anclaje tiene que ser un prefijo PROPIO: más corto que el candidato."""
    anchors = {"N18": "N18"}
    assert longest_anchor("N18", anchors) is None


def _linea_cms(orden: str, code: str, flag: str, corta: str, larga: str = "") -> str:
    """Arma una línea con las posiciones fijas documentadas en el PDF de CMS:
    1-5 orden, 7-13 código, 15 flag, 17-76 corta, 78-fin larga."""
    linea = list(" " * 77)
    linea[0:len(orden)] = orden
    linea[6:6 + len(code)] = code
    linea[14] = flag
    linea[16:16 + len(corta)] = corta
    return "".join(linea) + (f" {larga}" if larga else "")


def test_parse_catalog_formato_de_ancho_fijo_cms(tmp_path):
    """Línea real de `icd10cm_order_2026.txt` para N18 (ver el PDF de formato)."""
    linea = _linea_cms("24965", "N18", "0", "Chronic kidney disease (CKD)",
                       "Chronic kidney disease (CKD), completa")
    f = tmp_path / "catalog.txt"
    f.write_text(linea + "\n")
    rows = parse_catalog(f)
    assert rows == [("N18", "Chronic kidney disease (CKD), completa")]


def test_parse_catalog_usa_la_corta_si_falta_la_larga(tmp_path):
    linea = _linea_cms("00001", "A00", "1", "Cholera")
    f = tmp_path / "catalog.txt"
    f.write_text(linea + "\n")
    rows = parse_catalog(f)
    assert rows == [("A00", "Cholera")]


def test_build_descendants_excluye_categorias_de_3_caracteres():
    """Una categoría (`N18`) no puede ser descendiente de nada: es el techo."""
    anchors = {"N18": "N18"}
    out = build_descendants([("N18", "algo")], anchors)
    assert out == []


def test_build_descendants_excluye_lo_que_ya_es_anclaje():
    """`A03.9` ya está en `condition`: no se duplica como descendiente de `A03`."""
    anchors = {"A03": "A03", "A039": "A03.9"}
    out = build_descendants([("A039", "Shigellosis, unspecified")], anchors)
    assert out == []


def test_build_descendants_resuelve_n18_5():
    anchors = {"N18": "N18", "N189": "N18.9"}
    out = build_descendants(
        [("N185", "Chronic kidney disease, stage 5")], anchors)
    assert out == [("N18.5", "Chronic kidney disease, stage 5", "N18")]


def test_build_descendants_sin_anclaje_no_se_carga():
    out = build_descendants([("Z9999", "algo sin anclaje")], {"N18": "N18"})
    assert out == []


def test_catalogo_real_contiene_n18_5():
    """Smoke test contra el catálogo del repo: si CMS cambia el archivo, avisa."""
    catalog = Path("data/icd10/icd10cm_order_2026.txt")
    if not catalog.exists():
        import pytest
        pytest.skip("falta el catálogo CMS")
    rows = parse_catalog(catalog)
    codes = {c for c, _ in rows}
    assert "N185" in codes
