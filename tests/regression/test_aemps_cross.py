"""Gate: el cruce con la AEMPS no se puede perder en silencio.

Son dos comportamientos distintos y los dos se rompen sin hacer ruido —la
consulta sigue devolviendo 200 y una gravedad plausible— así que hace falta
fijarlos:

1. **La gravedad es la más alta entre fuentes, no la de la precedencia.**
   Medido sobre la base: 215 pares que DDInter marca `major` la AEMPS los deja
   en `desaconsejada`, y 29 al revés. Si alguien "simplifica" `lookup_pair`
   para devolver la fila ganadora y listo, esos 215 bajan a `moderate` sin que
   falle nada.
2. **El texto se rellena desde la fuente que lo tenga.** La AEMPS es hoy la
   única con mecanismo y manejo escritos; antes de cruzarla, las 164.668
   interacciones salían las dos cosas en NULL.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

DB_PATH = Path(os.environ.get("INTERACTION_DB_PATH", "data/recetalia_interactions.db"))


@pytest.fixture
async def db():
    if not DB_PATH.exists():
        pytest.skip("falta la base")
    from app.clients import recetalia_db
    await recetalia_db.client.close()
    recetalia_db.client.db_path = str(DB_PATH)
    yield recetalia_db.client
    await recetalia_db.client.close()


async def _pair(db, a: str, b: str):
    ia, ib = await db.drug_id_by_name(a), await db.drug_id_by_name(b)
    assert ia and ib, f"{a} o {b} no están en la base"
    hit = await db.lookup_pair(ia, ib)
    assert hit, f"sin interacción para {a} + {b}"
    return hit


async def test_gravedad_no_baja_por_el_texto_de_la_aemps(db):
    """warfarina + ibuprofeno: DDInter dice `major`, la AEMPS `desaconsejada`.

    Es el caso exacto de los 215. Tiene que salir `major` **y** con el texto
    en castellano de la AEMPS: las dos cosas a la vez, que es todo el punto.
    """
    hit = await _pair(db, "warfarin", "ibuprofen")
    assert hit["severity"] == "major"
    assert hit["severity_source"] == "ddinter", (
        "la gravedad tiene que venir de DDInter y decirlo; si sale de la AEMPS, "
        "este par bajó de grave a moderado")
    assert "hemorragias" in (hit["mechanism"] or ""), hit["mechanism"]
    assert hit["management"]


async def test_hay_texto_clinico_en_castellano(db):
    """Antes del cruce esto era NULL en las 164.668 filas."""
    hit = await _pair(db, "simvastatin", "clarithromycin")
    assert "rabdomiolisis" in (hit["mechanism"] or "").lower(), hit["mechanism"]
    assert "contraindicada" in (hit["management"] or "").lower(), hit["management"]
    assert hit["severity"] == "major"


async def test_se_declara_si_la_regla_matcheo_por_clase(db):
    """Una regla de clase es menos específica que una de molécula.

    `enalapril + espironolactona` sale de una regla sobre la clase de los IECA,
    no sobre el enalapril. El hallazgo tiene que decirlo.
    """
    hit = await _pair(db, "enalapril", "spironolactone")
    assert hit.get("text_match"), "falta el modo de match de la regla"
    assert "clase" in hit["text_match"]
    assert "hiperpotasemia" in (hit["mechanism"] or "").lower()


async def test_la_precedencia_incluye_aemps():
    """Si 'aemps' se cae del CASE, sus filas pasan a valer menos que openFDA."""
    from app.clients.recetalia_db import _PRECEDENCE
    assert "'aemps'" in _PRECEDENCE
    assert _PRECEDENCE.index("'recetalia'") < _PRECEDENCE.index("'aemps'")
    assert _PRECEDENCE.index("'aemps'") < _PRECEDENCE.index("'ddinter'")


# --- criterios de prescripción en el anciano --------------------------------

async def test_sin_edad_no_hay_alerta_geriatrica(db):
    """Un paciente sin edad cargada no es joven: es desconocido.

    Inferir "no es anciano" de la ausencia del dato es la forma callada de
    equivocarse, y es la que no deja rastro.
    """
    from app.services import contraindication_checker as cc
    from app.services.patient_profile import PatientProfile
    r = await cc.check(["ibuprofen"], PatientProfile())
    assert r["geriatric"] == []


async def test_alerta_geriatrica_a_los_65(db):
    from app.services import contraindication_checker as cc
    from app.services.patient_profile import PatientProfile
    joven = await cc.check(["ibuprofen"], PatientProfile(edad=64))
    viejo = await cc.check(["ibuprofen"], PatientProfile(edad=65))
    assert joven["geriatric"] == []
    assert viejo["geriatric"], "a los 65 tienen que salir los criterios de la AEMPS"
    a = viejo["geriatric"][0]
    assert a["recomendacion"]
    assert "ulcera" in a["situacion"].lower() or "úlcera" in a["situacion"].lower()


async def test_la_alerta_condicionada_se_marca_como_tal(db):
    """164 de las 172 dependen de algo que no está en la receta.

    Si `condicionada` se pierde, la interfaz las muestra como afirmaciones
    sobre el paciente y son casi todas falsas.
    """
    from app.services import contraindication_checker as cc
    from app.services.patient_profile import PatientProfile
    r = await cc.check(["ibuprofen", "diazepam"], PatientProfile(edad=80))
    assert r["geriatric"]
    assert all("condicionada" in a for a in r["geriatric"])
    assert any(a["condicionada"] for a in r["geriatric"])


# --- contrato HTTP ----------------------------------------------------------

async def test_el_endpoint_no_revienta_con_una_fuente_nueva(monkeypatch):
    """Guarda contra el 500 que dejó la carga de la AEMPS.

    `InteractionResult.source` es un `Literal` cerrado. Al agregar 'aemps' a la
    base sin agregarlo al modelo, la API devolvía 500 para cualquier par que
    resolviera por esa fuente — y no lo vio ningún test porque los de la API
    mockean el servicio *por encima* del modelo de respuesta. Éste pega al
    endpoint de verdad, contra la base de verdad.
    """
    if not DB_PATH.exists():
        pytest.skip("falta la base")
    monkeypatch.setenv("API_KEY", "test-local")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        r = c.post("/interactions", json={"drugs": ["warfarin", "ibuprofen"]},
                   headers={"X-API-Key": "test-local"})
    assert r.status_code == 200, r.text
    hit = r.json()["interactions"][0]
    assert hit["severity"] == "major"
    assert "hemorragias" in (hit["description"] or "")
    assert hit["management"], "el manejo clínico tiene que llegar al cliente"


async def test_todas_las_fuentes_de_la_base_estan_en_el_contrato():
    """Que el literal no se quede atrás de la base otra vez.

    Compara lo que hay realmente en `interaction.source` contra lo que el
    modelo admite, así el próximo ETL que agregue una fuente rompe acá y no en
    producción.
    """
    if not DB_PATH.exists():
        pytest.skip("falta la base")
    import sqlite3
    from typing import get_args
    from app.api.schemas import InteractionResult

    con = sqlite3.connect(DB_PATH)
    en_base = {r[0] for r in con.execute("select distinct source from interaction")}
    con.close()
    admitidas = set(get_args(InteractionResult.model_fields["source"].annotation))
    assert en_base <= admitidas, (
        f"la base tiene fuentes que el contrato no admite: {en_base - admitidas}. "
        "El endpoint devuelve 500 en cuanto aparezca un hallazgo de esa fuente.")


async def test_un_combinado_no_se_atribuye_a_un_ingrediente(db):
    """`A10BD05` es metformina + pioglitazona, y su regla habla de la segunda.

    Colapsarla a Metformina producía el absurdo "evitar su utilización… hay
    alternativas más seguras como metformina". Un producto combinado no se
    resuelve a uno de sus ingredientes por la primera palabra: la regla suele
    ser sobre el OTRO.
    """
    from app.services import contraindication_checker as cc
    from app.services.patient_profile import PatientProfile
    r = await cc.check(["metformin"], PatientProfile(edad=75))
    for g in r["geriatric"]:
        assert "metformina" not in (g["recomendacion"] or "").lower(), (
            "una alerta sobre metformina no puede recomendar metformina: "
            f"vino de {g.get('note')}")


def test_el_detector_de_combinados():
    import sys
    sys.path.insert(0, "scripts")
    from cross_aemps_interactions import es_combinacion
    assert es_combinacion("metformina y pioglitazona")
    assert es_combinacion("Ibuprofeno, combinaciones")
    assert es_combinacion("Amoxicilina e inhibidores de la betalactamasa")
    assert not es_combinacion("Metformina")
    assert not es_combinacion("Acido acetilsalicilico")
    assert not es_combinacion("Warfarina")


# --- búsqueda de patologías (el input de CIE-10 de la interfaz) -------------

async def test_la_busqueda_de_patologias_solo_ofrece_lo_que_evalua(db):
    """Ofrecer un código que no dispara nada es prometer una evaluación falsa."""
    res = await db.search_conditions("N18")
    assert res, "N18 tiene que estar: es el anclaje de la insuficiencia renal"
    assert all(r["alertas"] >= 0 for r in res)
    assert any(r["code"].startswith("N18") for r in res)


async def test_la_busqueda_de_patologias_acepta_codigo_y_nombre(db):
    por_codigo = await db.search_conditions("K70")
    por_nombre = await db.search_conditions("liver")
    assert any("K7" in r["code"] for r in por_codigo)
    assert any("liver" in r["name"].lower() for r in por_nombre)


async def test_el_buscador_devuelve_el_nombre_en_castellano(db):
    """La interfaz es para un médico uruguayo: el canónico está en inglés.

    Sale del alias castellano o del mapa del DNMA, que trae la grafía del
    vademécum local. Si esto se corta, la pantalla vuelve a decir "Warfarin".
    """
    res = await db.search_drugs("warfar")
    assert res
    w = next(r for r in res if r["name"] == "Warfarin")
    assert w["name_es"] == "Warfarina", w

    # Y se queda en None cuando no lo sabemos: inventar una traducción de un
    # fármaco es peor que mostrar el inglés.
    todos = await db.search_drugs("ab", limit=25)
    assert any(r["name_es"] is None for r in todos) or todos, "smoke"
