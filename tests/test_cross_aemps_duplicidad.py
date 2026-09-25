"""Detector de combinados y clase del ancla, sin base."""
import sys

sys.path.insert(0, "scripts")
from cross_aemps_duplicidad import clase_de, es_codigo_combinado  # noqa: E402

NOMBRES = {
    "C09AA": "Inhibidores de la ECA, monofarmacos",
    "C09AA02": "Enalapril",
    "C09AA05": "Ramipril",
    "C09BA": "Inhibidores de la ECA y diureticos",
    "C09BA02": "Enalapril y diureticos",
    "C09BA05": "Ramipril y diureticos",
    "N02BE": "Anilidas",
    "N02BE01": "Paracetamol",
    "N02BE51": "Paracetamol, combinaciones excluyendo psicolepticos",
    "N02BE71": "Paracetamol, combinaciones con psicolepticos",
    "A02BC": "Inhibidores de la bomba de protones",
    "A02BC01": "Omeprazol",
    "N04BA": "Dopa y derivados de la dopa",
    "N04BA01": "Levodopa",
    "N04BA02": "Levodopa e inhibidor de la decarboxilasa",
    "N04BA03": "Levodopa, inhibidor de la decarboxilasa e inhibidor de la COMT",
}


def test_la_clase_es_el_atc4_del_ancla():
    assert clase_de("N05BA01") == "N05BA"
    assert clase_de("C09AA") == "C09AA"
    assert clase_de("J01C") == "J01C"


def test_n4_monofarmaco_no_es_combinado_aunque_diga_inhibidores_de():
    assert not es_codigo_combinado("C09AA", NOMBRES)
    assert not es_codigo_combinado("A02BC", NOMBRES)


def test_n4_de_combinados_es_combinado():
    assert es_codigo_combinado("C09BA", NOMBRES)


def test_anilidas_no_es_combinado_aunque_casi_todos_sus_hijos_lo_sean():
    """El nombre no dice combinación: hace falta que lo digan nombre E hijos."""
    assert not es_codigo_combinado("N02BE", NOMBRES)


def test_n5():
    assert es_codigo_combinado("C09BA02", NOMBRES)
    assert es_codigo_combinado("N02BE51", NOMBRES)
    assert not es_codigo_combinado("N02BE01", NOMBRES)


def test_lista_explicita_de_falsos():
    assert not es_codigo_combinado("N04BA", NOMBRES)
