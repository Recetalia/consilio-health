#!/usr/bin/env python3
"""Traer el texto de `drug_interactions` de los prospectos de la FDA.

Tapa el hueco de DDInter: los pares donde ambas drogas son de categorías ATC no
publicadas (C, G, J, M, N, S) no existen en el dataset — enalapril + losartán,
sertralina + fluoxetina, amlodipina + atorvastatina. Son interacciones de
atención primaria y hoy salen como "sin hallazgos", que el médico lee como
"no interactúan".

openFDA es **CC0** (dominio público), así que no arrastra el problema de
licencia de DDInter.

Por defecto trae sólo los fármacos que Recetalia receta de verdad (los que
tienen mapeo desde el DNMA): son ~733 y entran en el límite de 1.000 requests
diarios sin API key. Con --all va por los 1.939, que **no** entra en ese límite
— para eso hace falta una API key gratuita (open.fda.gov/apis/authentication)
o el dump completo de 1,8 GB.

El texto se guarda una vez y se consulta local: openFDA nunca entra al camino de
una request de un médico.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("fetch_openfda")

ENDPOINT = "https://api.fda.gov/drug/label.json"
USER_AGENT = "consilio-build"

SCHEMA = """
CREATE TABLE IF NOT EXISTS drug_label_text (
    drug_id     INTEGER NOT NULL REFERENCES drug(drug_id),
    section     TEXT    NOT NULL,      -- drug_interactions | contraindications | ...
    text        TEXT    NOT NULL,
    label_count INTEGER NOT NULL,      -- cuántos prospectos coincidieron
    source      TEXT    NOT NULL CHECK (source IN ('openfda','recetalia')),
    fetched_at  TEXT    NOT NULL,
    PRIMARY KEY (drug_id, section, source)
);
CREATE INDEX IF NOT EXISTS idx_label_drug ON drug_label_text(drug_id);
"""

SECTIONS = ("drug_interactions", "contraindications")


def _get(params: dict, *, timeout: float = 30.0, retries: int = 3) -> dict | None:
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None                    # sin prospecto: no es un error
            if exc.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    return None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default="data/recetalia_interactions.db")
    p.add_argument("--all", action="store_true",
                   help="los 1.939 fármacos, no sólo los que Recetalia receta")
    p.add_argument("--rate", type=float, default=3.0,
                   help="req/s. El techo sin API key es 240/min = 4/s.")
    p.add_argument("--limit", type=int)
    args = p.parse_args()

    api_key = os.environ.get("OPENFDA_API_KEY")
    logger.info("API key: %s", "sí" if api_key else "no (límite 1.000/día)")

    db = sqlite3.connect(args.db)
    db.executescript(SCHEMA)

    if args.all:
        rows = db.execute(
            "select drug_id, canonical from drug order by canonical").fetchall()
    else:
        rows = db.execute(
            "select distinct d.drug_id, d.canonical from drug d "
            "join dnma_substance_map m on m.drug_id = d.drug_id "
            "order by d.canonical").fetchall()
    if args.limit:
        rows = rows[:args.limit]

    logger.info("Fármacos a consultar: %d", len(rows))
    if len(rows) > 1000 and not api_key:
        logger.warning("Son más de 1.000 sin API key: openFDA va a cortar a mitad "
                       "de camino. Conseguí una en open.fda.gov/apis/authentication")

    delay = 1.0 / max(args.rate, 0.5)
    now = datetime.now(timezone.utc).isoformat()
    found = miss = fail = 0
    per_section: dict[str, int] = {}

    for i, (drug_id, name) in enumerate(rows, 1):
        time.sleep(delay)
        # generic_name y substance_name: un prospecto indexa por uno u otro
        q = (f'openfda.generic_name:"{name}" OR openfda.substance_name:"{name}"')
        params = {"search": q, "limit": "5"}
        if api_key:
            params["api_key"] = api_key
        try:
            payload = _get(params)
        except Exception as exc:
            logger.warning("openFDA falló para %s: %s", name, exc)
            fail += 1
            continue

        results = (payload or {}).get("results") or []
        if not results:
            miss += 1
            continue

        hit = False
        for section in SECTIONS:
            # el prospecto más largo es el más completo
            texts = [t for r in results for t in (r.get(section) or [])]
            if not texts:
                continue
            best = max(texts, key=len)
            db.execute(
                "insert or replace into drug_label_text "
                "(drug_id, section, text, label_count, source, fetched_at) "
                "values (?,?,?,?,'openfda',?)",
                (drug_id, section, best, len(results), now))
            per_section[section] = per_section.get(section, 0) + 1
            hit = True
        found += 1 if hit else 0
        if not hit:
            miss += 1

        if i % 100 == 0:
            db.commit()
            logger.info("  %d/%d  con texto=%d  sin=%d  fallos=%d",
                        i, len(rows), found, miss, fail)

    db.execute("insert or replace into meta (key, value) values ('openfda_fetched_at',?)",
               (now,))
    db.commit()
    logger.info("=== RESULTADO ===")
    logger.info("consultados %d · con texto %d (%.1f%%) · sin %d · fallos %d",
                len(rows), found, found / max(len(rows), 1) * 100, miss, fail)
    for s, n in sorted(per_section.items()):
        logger.info("  %-20s %d", s, n)
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
