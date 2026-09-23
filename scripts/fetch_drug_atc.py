#!/usr/bin/env python3
"""Traer el código ATC de cada fármaco, vía RxClass.

Hace falta para cruzar con la base de la AEMPS, que codifica sus 2.426 reglas de
interacción en ATC y no en RxCUI. Es el puente entre lo que tenemos (RxNorm) y
lo único que encontramos con mecanismo y manejo clínico escritos en castellano.

Se guarda en `drug.atc`, que ya existía en el esquema sin usar.
"""
from __future__ import annotations
import argparse, json, logging, os, sqlite3, time, urllib.error, urllib.parse, urllib.request

logger = logging.getLogger("fetch_atc")
BASE = "https://rxnav.nlm.nih.gov/REST/rxclass"
UA = "consilio-build"

def _get(path, params, retries=3):
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for a in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404: return {}
            if e.code in (429,500,502,503) and a < retries-1: time.sleep(2**a*2); continue
            raise
        except Exception:
            if a < retries-1: time.sleep(2**a); continue
            return {}
    return {}

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="data/recetalia_interactions.db")
    p.add_argument("--rate", type=float, default=10.0)
    args = p.parse_args()

    db = sqlite3.connect(args.db)
    # `atc` ya existe en la tabla drug; se usa por primera vez acá.
    rows = db.execute("select drug_id, rxcui, canonical from drug "
                      "where rxcui is not null and atc is null order by canonical").fetchall()
    logger.info("Fármacos sin ATC: %d", len(rows))
    delay = 1.0/max(args.rate,1.0)
    n = fail = 0
    for i,(did,rxcui,name) in enumerate(rows,1):
        time.sleep(delay)
        try:
            d = _get("/class/byRxcui.json", {"rxcui": rxcui, "relaSource":"ATC"})
        except Exception as e:
            logger.warning("ATC falló para %s: %s", name, e); fail += 1; continue
        codes = sorted({it.get("rxclassMinConceptItem",{}).get("classId","")
                        for it in (d.get("rxclassDrugInfoList",{}) or {}).get("rxclassDrugInfo",[])
                        if it.get("rxclassMinConceptItem",{}).get("classId")})
        if codes:
            # Varios ATC por fármaco es normal (distintas vías/indicaciones).
            db.execute("update drug set atc=? where drug_id=?", (",".join(codes), did))
            n += 1
        if i % 200 == 0:
            db.commit(); logger.info("  %d/%d  con ATC=%d  fallos=%d", i, len(rows), n, fail)
    db.commit()
    logger.info("=== con ATC: %d de %d (fallos %d) ===", n, len(rows), fail)
    db.close(); return 0

if __name__ == "__main__":
    raise SystemExit(main())
