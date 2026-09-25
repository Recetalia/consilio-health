"""Capitalización de los nombres a mostrar."""
from app.clients.recetalia_db import _titulo


def test_sigla_del_dnma_queda_en_mayusculas():
    assert _titulo("AAS") == "AAS"


def test_nombre_en_mayusculas_pasa_a_oracion():
    assert _titulo("WARFARINA") == "Warfarina"
    assert _titulo("DICLOFENAC POTASICO") == "Diclofenac potasico"


def test_mixto_no_se_toca():
    assert _titulo("Ácido acetilsalicílico") == "Ácido acetilsalicílico"
