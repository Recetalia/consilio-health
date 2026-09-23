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
