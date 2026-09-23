#!/usr/bin/env python3
"""Puente CIE-10 ↔ MeSH: traduce la patología del paciente a lo que MED-RT entiende.

## El problema

MED-RT codifica sus 965 patologías en **MeSH** (`D051437 Renal Insufficiency`).
El médico carga la patología en **CIE-10** (`N18.5`). Sin traducción no se tocan,
y las 5.794 alertas por patología quedan inertes.

## Por qué no alcanza una tabla de equivalencias

Medido con el crosswalk de UMLS, un descriptor MeSH ancla de tres formas
distintas, y hay que soportar las tres:

    Renal Insufficiency, Chronic  →  N18.9, N18      código y categoría
    Liver Diseases                →  K76.9, K70-K77  código y RANGO
    Pregnancy                     →  Z33.1           código suelto

Un paciente con `N18.5` no matchea `N18.9` ni `N19`, pero **sí matchea `N18`
truncando**. Sin ese ascenso, el paciente con insuficiencia renal estadio 5 no
dispara la alerta de insuficiencia renal — justo el que más la necesita.

## Cómo se resuelve

1. Acá (offline): crosswalk MeSH → CIE-10-CM por cada condición que tengamos
   alertas, guardando los anclajes en `condition` + `condition_xref`.
2. En runtime (gratis, sin red): el código del paciente se compara contra los
   anclajes por igualdad, por truncación de ancestros, y por pertenencia a rango.

## Licencias

- **CIE-10-CM** (CMS/NCHS) es dominio público. Se usa ése y no el CIE-10 de la
  OMS, que es CC BY-ND y prohíbe derivados — una tabla de mapeo embebida en un
  producto ES un derivado.
- **UMLS** permite el uso comercial embebido ("as an integral part of computer
  applications developed by LICENSEE") pero **prohíbe redistribuir el
  vocabulario**. Esta tabla va adentro del producto, no como dataset.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger("condition_xref")

UTS = "https://uts-ws.nlm.nih.gov/rest"
USER_AGENT = "consilio-build"

# Medido: llamadas seguidas hacen que el NLM corte la conexión a nivel TCP (falla
# en ~40 ms, no es timeout). Con espaciado responde sin problema.
DEFAULT_DELAY = 1.5

RANGE_RE = re.compile(r"^([A-Z]\d{2})-([A-Z]\d{2})$")


def _get(path: str, params: dict, *, retries: int = 4) -> dict | None:
    params = dict(params)
    params["apiKey"] = os.environ.get("UMLS_API_KEY", "")
    url = f"{UTS}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None          # sin equivalencia: no es un error
            if exc.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            # El corte de conexión por throttling entra por acá.
            if attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            return None
    return None


def crosswalk(mesh_code: str) -> list[tuple[str, str]]:
    """MeSH → [(código CIE-10-CM, nombre)]. Lista vacía si no hay equivalencia."""
    d = _get(f"/crosswalk/current/source/MSH/{mesh_code}", {"targetSource": "ICD10CM"})
    if not d:
        return []
    return [(r["ui"], r.get("name") or "") for r in d.get("result", []) if r.get("ui")]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default="data/recetalia_interactions.db")
    p.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    p.add_argument("--limit", type=int, help="cortar después de N condiciones (prueba)")
    p.add_argument("--only-with-alerts", action="store_true", default=True,
                   help="sólo las condiciones que tienen alertas (por defecto)")
    p.add_argument("--all", dest="only_with_alerts", action="store_false")
    args = p.parse_args()

    if not os.environ.get("UMLS_API_KEY"):
        logger.error("Falta UMLS_API_KEY. Está en el .env (gitignoreado).")
        return 1

    db = sqlite3.connect(args.db)

    sql = """select c.condition_id, c.code, c.name,
                    (select count(*) from drug_condition_alert a
                      where a.condition_id = c.condition_id) n
             from condition c where c.code_system = 'mesh'"""
    if args.only_with_alerts:
        sql += " and n > 0"
    sql += " order by n desc"
    rows = db.execute(sql).fetchall()
    if args.limit:
        rows = rows[:args.limit]
    logger.info("Condiciones MeSH a traducir: %d", len(rows))

    now = datetime.now(timezone.utc).isoformat()
    n_anchor = n_none = n_range = 0
    seen: dict[str, int] = {}

    for i, (cond_id, mesh_code, mesh_name, n_alerts) in enumerate(rows, 1):
        time.sleep(args.delay)
        try:
            anchors = crosswalk(mesh_code)
        except Exception as exc:
            logger.warning("crosswalk falló para %s (%s): %s", mesh_name, mesh_code, exc)
            continue

        if not anchors:
            n_none += 1
            continue

        for code, name in anchors:
            key = code
            icd_id = seen.get(key)
            if icd_id is None:
                db.execute(
                    "insert or ignore into condition (code_system, code, name, source) "
                    "values ('icd10cm',?,?,'umls')", (code, name or mesh_name))
                icd_id = db.execute(
                    "select condition_id from condition where code_system='icd10cm' and code=?",
                    (code,)).fetchone()[0]
                seen[key] = icd_id
            if RANGE_RE.match(code):
                n_range += 1
            db.execute(
                "insert or ignore into condition_xref (from_id, to_id, method, source) "
                "values (?,?,'umls','umls')", (icd_id, cond_id))
            n_anchor += 1

        if i % 50 == 0:
            db.commit()
            logger.info("  %d/%d  anclajes=%d  sin equivalencia=%d", i, len(rows), n_anchor, n_none)

    db.execute("insert or replace into meta (key,value) values ('condition_xref_built_at',?)", (now,))
    db.commit()

    total_mesh = len(rows)
    con_puente = db.execute("""
        select count(distinct x.to_id) from condition_xref x""").fetchone()[0]
    alertas_alcanzables = db.execute("""
        select count(*) from drug_condition_alert a
         where a.condition_id in (select to_id from condition_xref)""").fetchone()[0]
    alertas_total = db.execute("select count(*) from drug_condition_alert").fetchone()[0]

    logger.info("=== RESULTADO ===")
    logger.info("anclajes CIE-10 creados: %d (%d son rangos)", n_anchor, n_range)
    logger.info("condiciones MeSH con puente: %d de %d", con_puente, total_mesh)
    logger.info("ALERTAS ALCANZABLES desde CIE-10: %d de %d (%.1f%%)",
                alertas_alcanzables, alertas_total, alertas_alcanzables / alertas_total * 100)
    logger.info("sin equivalencia en CIE-10: %d condiciones", n_none)
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
