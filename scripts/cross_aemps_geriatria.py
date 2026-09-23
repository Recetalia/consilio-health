#!/usr/bin/env python3
"""Cargar las alertas geriátricas de la AEMPS, cruzadas por ATC.

Reutiliza el resolvedor de `cross_aemps_interactions`: el puente ATC → fármaco
es el mismo problema y no tiene por qué resolverse dos veces.

## Por qué casi todas se guardan como condicionadas

Medido sobre las 310 reglas: **156 no dependen sólo de la edad**. Dicen
"Pacientes con estreñimiento crónico", "Tratamiento concomitante con AINE y
diurético", "Tasa de filtración glomerular estimada <60ml/min". Son situaciones
clínicas que en general **no podemos verificar** con lo que trae una receta.

Dispararlas todas como afirmaciones sobre cualquier paciente de 65 años es
exactamente cómo se fabrica la fatiga de alertas que hace que los médicos dejen
de mirarlas: hay evidencia publicada de 93 % de rechazo en alertas de dosis, con
el 88,8 % de esos rechazos juzgado apropiado — o sea, alertas malas, no médicos
distraídos.

Por eso cada fila lleva `condicionada`. Una alerta condicionada no afirma nada:
dice *verificar si* se da la situación. Es menos vistoso y es lo único honesto
mientras no tengamos el dato para evaluarla.

## Lo que este cruce NO trae

`aemps_extra.json` lista **1.012 situaciones** repartidas en 303 fármacos (hasta
9 por fármaco), mientras que `aemps_reglas.json` guardó **una sola por fármaco,
que es la única que vino con su recomendación**. O sea que hay ~700 situaciones
geriátricas más, sin el texto de qué hacer. Se cargan las 310 completas; las
otras hacen falta volver a extraerlas del origen.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone

from cross_aemps_interactions import Resolver, cargar_atc_names

logger = logging.getLogger("cross_geriatria")

DDL = """
create table if not exists drug_population_alert (
    drug_id      integer not null references drug(drug_id),
    population   text    not null,          -- 'elderly'
    situacion    text    not null,          -- cuándo aplica; '' si es sólo por edad
    recomendacion text   not null,
    condicionada integer not null,          -- 1 = hay que verificar la situación
    source       text    not null,
    note         text,
    primary key (drug_id, population, situacion, source)
);
create index if not exists idx_dpa_drug on drug_population_alert(drug_id);
"""

# Una situación que sólo habla de la edad no condiciona nada. Todo lo demás sí,
# incluso cuando el texto no arranca con "Pacientes con": "Uso crónico" y
# "Tratamiento de la osteoartritis" también son condiciones que no verificamos.
_SOLO_EDAD = re.compile(r"^\s*$")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="data/recetalia_interactions.db")
    p.add_argument("--reglas", default="data/aemps/aemps_reglas.json")
    p.add_argument("--dicc-atc", default="data/aemps/DICCIONARIO_ATC.xml")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    for f in (args.db, args.reglas, args.dicc_atc):
        if not os.path.exists(f):
            raise SystemExit(f"falta {f}")

    db = sqlite3.connect(args.db)
    res = Resolver(db, cargar_atc_names(args.dicc_atc))
    geri = json.load(open(args.reglas, encoding="utf-8"))["geriatria"]

    filas: dict[tuple[int, str], tuple] = {}
    sin_resolver = sin_texto = 0
    for atc, v in geri.items():
        situacion = (v.get("alerta") or "").strip()
        recomendacion = (v.get("recomendacion") or "").strip()
        if not recomendacion:
            sin_texto += 1
            continue
        ids, modo = res.resolver(atc)
        if not ids:
            sin_resolver += 1
            continue
        condicionada = 0 if _SOLO_EDAD.match(situacion) else 1
        for did in ids:
            filas[(did, situacion)] = (
                did, "elderly", situacion, recomendacion, condicionada,
                "aemps", f"match {modo} · {atc}")

    cond = sum(1 for f in filas.values() if f[4])
    logger.info("=== %d alertas sobre %d fármacos · %d condicionadas · %d directas ===",
                len(filas), len({f[0] for f in filas.values()}), cond, len(filas) - cond)
    logger.info("ATC que no resolvieron: %d · reglas sin recomendación: %d",
                sin_resolver, sin_texto)

    if args.dry_run:
        logger.info("dry-run: no se escribió nada")
        return

    db.executescript(DDL)
    borradas = db.execute(
        "delete from drug_population_alert where source='aemps'").rowcount
    if borradas:
        logger.info("Reemplazando %d filas previas", borradas)
    db.executemany(
        "insert into drug_population_alert (drug_id, population, situacion, "
        "recomendacion, condicionada, source, note) values (?,?,?,?,?,?,?)",
        list(filas.values()))
    db.execute("insert or replace into meta (key, value) values ('aemps_geriatria_at', ?)",
               (datetime.now(timezone.utc).isoformat(timespec="seconds"),))
    db.commit()
    logger.info("Escritas %d filas", len(filas))


if __name__ == "__main__":
    main()
