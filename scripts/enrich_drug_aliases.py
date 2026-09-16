#!/usr/bin/env python3
"""Sumar alias a los fármacos: nombres de RxNorm y sinónimos en español.

## Por qué

La base guarda el nombre que usa DDInter, que muchas veces no es el que un
médico tipea. Medido: `aspirin` no devolvía nada en el buscador, porque el
fármaco está como `Acetylsalicylic acid` — aunque su RxCUI (1191) se llama
literalmente "aspirin" en RxNorm. El alias existía en la fuente y no lo
habíamos traído.

Dos aportes, los dos a `drug_alias`:

1. **RxNorm** (`source='rxnorm'`): el nombre canónico y los sinónimos que RxNorm
   tiene para cada RxCUI. Resuelve el caso aspirin y sus parientes.
2. **Español** (`source='manual'`): RxNorm es inglés. `paracetamol`,
   `dipirona` o `adrenalina` no existen ahí, y son los nombres que se usan acá.
   Van en `data/alias_es.json`, curado a mano.

Nada de esto pisa los alias que ya existen: se insertan con `insert or ignore`.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger("enrich_aliases")

BASE = "https://rxnav.nlm.nih.gov/REST"
USER_AGENT = "consilio-build"
ALIAS_ES = Path("data/alias_es.json")


def norm(s: str) -> str:
    """Debe coincidir con `recetalia_db.normalize`, o las búsquedas no encuentran."""
    from scripts.build_recetalia_db import _norm
    return _norm(s)


def _get(path: str, params: dict, *, retries: int = 3) -> dict:
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {}
            if exc.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    return {}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default="data/recetalia_interactions.db")
    p.add_argument("--rate", type=float, default=10.0)
    p.add_argument("--skip-rxnorm", action="store_true",
                   help="sólo cargar los alias en español")
    args = p.parse_args()

    db = sqlite3.connect(args.db)
    before = db.execute("select count(*) from drug_alias").fetchone()[0]

    # --- 1) español, curado a mano ---
    n_es = 0
    if ALIAS_ES.exists():
        by_canon = {c.lower(): i for i, c in db.execute("select drug_id, canonical from drug")}
        for canonical, aliases in json.loads(ALIAS_ES.read_text()).items():
            if canonical.startswith("_"):      # comentarios del JSON
                continue
            drug_id = by_canon.get(canonical.lower())
            if drug_id is None:
                logger.warning("alias_es: no existe el fármaco %r", canonical)
                continue
            for a in aliases:
                db.execute(
                    "insert or ignore into drug_alias "
                    "(drug_id, alias, alias_norm, lang, source) values (?,?,?,'es','manual')",
                    (drug_id, a, norm(a)))
                n_es += 1
        db.commit()
        logger.info("Alias en español cargados: %d", n_es)
    else:
        logger.warning("No existe %s; se omiten los alias en español", ALIAS_ES)

    # --- 2) nombres de RxNorm ---
    n_rx = fail = 0
    if not args.skip_rxnorm:
        rows = db.execute(
            "select drug_id, rxcui, canonical from drug "
            "where rxcui is not null order by canonical").fetchall()
        logger.info("Fármacos con RxCUI: %d", len(rows))
        delay = 1.0 / max(args.rate, 1.0)
        for i, (drug_id, rxcui, canonical) in enumerate(rows, 1):
            time.sleep(delay)
            try:
                d = _get(f"/rxcui/{rxcui}/allProperties.json", {"prop": "names"})
            except Exception as exc:
                logger.warning("RxNorm falló para %s (%s): %s", canonical, rxcui, exc)
                fail += 1
                continue
            names = {c.get("propValue") for c in
                     d.get("propConceptGroup", {}).get("propConcept", [])
                     if c.get("propValue")}
            for name in names:
                if norm(name) == norm(canonical):
                    continue          # ya está, es el mismo nombre
                db.execute(
                    "insert or ignore into drug_alias "
                    "(drug_id, alias, alias_norm, lang, source) values (?,?,?,'en','rxnorm')",
                    (drug_id, name, norm(name)))
                n_rx += 1
            if i % 200 == 0:
                db.commit()
                logger.info("  %d/%d  alias nuevos=%d  fallos=%d", i, len(rows), n_rx, fail)
        db.commit()

    after = db.execute("select count(*) from drug_alias").fetchone()[0]
    logger.info("=== RESULTADO ===")
    logger.info("alias: %d -> %d  (+%d)", before, after, after - before)
    for src, n in db.execute(
            "select source, count(*) from drug_alias group by source order by 2 desc"):
        logger.info("  %-10s %d", src, n)
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
