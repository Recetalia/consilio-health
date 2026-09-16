#!/usr/bin/env python3
"""Traer contraindicaciones fármaco-patología desde MED-RT, vía la API RxClass.

MED-RT es del NLM/VA y no exige licencia: "MED-RT has no copyright
acknowledgement required" (HL7 THO). Se accede por RxClass porque el ZIP del
NCI EVS está detrás de una SPA que no se puede bajar por HTTP plano.

Las condiciones vienen codificadas en **MeSH**, con descriptores gruesos
("Renal Insufficiency", no "N18.5"). El puente a CIE-10 es trabajo aparte y vive
en `condition_xref`.

Todo lo que escribe lleva source='medrt', así que un re-fetch borra sólo lo suyo
y deja intacta la curación propia.

Uso:
    python -m scripts.fetch_medrt_contraindications --limit 50   # prueba
    python -m scripts.fetch_medrt_contraindications              # completo
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from scripts.build_recetalia_db import SCHEMA

logger = logging.getLogger("fetch_medrt")

RXCLASS = "https://rxnav.nlm.nih.gov/REST/rxclass/class/byRxcui.json"
USER_AGENT = "consilio-build"

# `kind` por relación. ci_with es la contraindicación directa fármaco-patología;
# las otras tres son por clase química, mecanismo o efecto fisiológico, que son
# inferencias más flojas y por eso entran como precaución.
RELA_KIND = {
    "ci_with": "contraindication",
    "ci_chemclass": "precaution",
    "ci_moa": "precaution",
    "ci_pe": "precaution",
}


def _get(rxcui: str, *, timeout: float = 20.0, retries: int = 3) -> dict:
    qs = urllib.parse.urlencode({"rxcui": rxcui, "relaSource": "MEDRT"})
    req = urllib.request.Request(
        f"{RXCLASS}?{qs}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < retries - 1:
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
    p.add_argument("--rate", type=float, default=12.0,
                   help="requests/segundo. El techo de RxNav es 20/s por IP.")
    p.add_argument("--limit", type=int, help="cortar después de N fármacos (prueba)")
    args = p.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        logger.error("No existe %s — corré antes `build_recetalia_db seed`", db_path)
        return 1

    db = sqlite3.connect(db_path)
    db.executescript(SCHEMA)          # idempotente: crea condition/alert si faltan

    drugs = db.execute(
        "select drug_id, rxcui, canonical from drug "
        "where rxcui is not null order by canonical").fetchall()
    if args.limit:
        drugs = drugs[:args.limit]
    logger.info("Fármacos con RxCUI a consultar: %d", len(drugs))

    delay = 1.0 / max(args.rate, 1.0)
    now = datetime.now(timezone.utc).isoformat()
    n_alert = n_cond = n_fail = 0
    seen_cond: dict[tuple[str, str], int] = {}

    # El re-fetch reemplaza lo de MED-RT y nada más.
    db.execute("delete from drug_condition_alert where source='medrt'")

    for i, (drug_id, rxcui, name) in enumerate(drugs, 1):
        time.sleep(delay)
        try:
            payload = _get(rxcui)
        except Exception as exc:
            logger.warning("RxClass falló para %s (rxcui=%s): %s", name, rxcui, exc)
            n_fail += 1
            continue

        for item in (payload.get("rxclassDrugInfoList", {}) or {}).get("rxclassDrugInfo", []):
            rela = (item.get("rela") or "").lower()
            kind = RELA_KIND.get(rela)
            if kind is None:                       # may_treat, may_prevent, etc.
                continue
            cls = item.get("rxclassMinConceptItem", {})
            code, cname = cls.get("classId"), cls.get("className")
            if not code or not cname:
                continue

            key = ("mesh", code)
            cid = seen_cond.get(key)
            if cid is None:
                db.execute(
                    "insert or ignore into condition (code_system, code, name, source) "
                    "values ('mesh',?,?,'medrt')", (code, cname))
                cid = db.execute(
                    "select condition_id from condition where code_system='mesh' and code=?",
                    (code,)).fetchone()[0]
                seen_cond[key] = cid
                n_cond += 1

            db.execute(
                "insert or ignore into drug_condition_alert "
                "(drug_id, condition_id, kind, rela, source, reviewed_at) "
                "values (?,?,?,?,'medrt',?)", (drug_id, cid, kind, rela, now))
            n_alert += 1

        if i % 200 == 0:
            db.commit()
            logger.info("  %d/%d  alertas=%d  condiciones=%d  fallos=%d",
                        i, len(drugs), n_alert, n_cond, n_fail)

    db.execute("insert or replace into meta (key, value) values ('medrt_fetched_at',?)", (now,))
    db.commit()

    logger.info("Listo. alertas=%d  condiciones distintas=%d  fallos=%d",
                n_alert, n_cond, n_fail)
    for kind, n in db.execute(
            "select kind, count(*) from drug_condition_alert where source='medrt' group by kind"):
        logger.info("  %-18s %d", kind, n)
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
