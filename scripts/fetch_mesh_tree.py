#!/usr/bin/env python3
"""Traer el número de árbol MeSH de cada condición, para poder ascender.

## Por qué hace falta

El puente CIE-10 ancla `N18.5` (ERC estadio 5) en `Renal Insufficiency,
Chronic`. Pero la contraindicación de la metformina está en `Renal
Insufficiency` a secas, anclada en `N19`. En CIE-10 `N18` y `N19` son HERMANOS,
así que truncar el código del paciente nunca los conecta: el enfermo renal
estadio 5 se quedaba sin la alerta de insuficiencia renal, que es el caso más
grave.

En MeSH sí están conectados, y el número de árbol lo hace explícito:

    Renal Insufficiency, Chronic   C12.950.419.780.750
    Renal Insufficiency            C12.950.419.780       ← prefijo del anterior

O sea que la ascendencia es coincidencia de prefijo. Con los árboles cargados,
una condición que matchea arrastra a todos sus ancestros.

Fuente: la API pública de MeSH del NLM (id.nlm.nih.gov), sin autenticación.
"""
from __future__ import annotations
import argparse, json, logging, sqlite3, time, urllib.error, urllib.request

logger = logging.getLogger("mesh_tree")
BASE = "https://id.nlm.nih.gov/mesh"
UA = "consilio-build"

def trees(code: str, retries: int = 3) -> list[str]:
    req = urllib.request.Request(f"{BASE}/{code}.json",
                                 headers={"User-Agent": UA, "Accept": "application/json"})
    for a in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                d = json.loads(r.read())
            tn = d.get("treeNumber") or []
            if isinstance(tn, str): tn = [tn]
            return sorted({str(t).split("/")[-1] for t in tn})
        except urllib.error.HTTPError as e:
            if e.code == 404: return []
            if a < retries - 1: time.sleep(2 ** a); continue
            return []
        except Exception:
            if a < retries - 1: time.sleep(2 ** a); continue
            return []
    return []

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="data/recetalia_interactions.db")
    p.add_argument("--rate", type=float, default=6.0)
    args = p.parse_args()

    db = sqlite3.connect(args.db)
    cols = {r[1] for r in db.execute("pragma table_info(condition)")}
    if "tree" not in cols:
        db.execute("alter table condition add column tree TEXT")
        db.commit()
        logger.info("columna `tree` agregada")

    rows = db.execute("""select condition_id, code, name from condition
                          where code_system='mesh' and tree is null
                          order by (select count(*) from drug_condition_alert a
                                     where a.condition_id = condition.condition_id) desc""").fetchall()
    logger.info("Condiciones MeSH sin árbol: %d", len(rows))
    delay = 1.0 / max(args.rate, 1.0)
    n = sin = 0
    for i, (cid, code, name) in enumerate(rows, 1):
        time.sleep(delay)
        t = trees(code)
        if t:
            db.execute("update condition set tree=? where condition_id=?", (",".join(t), cid))
            n += 1
        else:
            sin += 1
        if i % 200 == 0:
            db.commit(); logger.info("  %d/%d  con árbol=%d  sin=%d", i, len(rows), n, sin)
    db.commit()
    logger.info("=== con árbol: %d · sin árbol: %d ===", n, sin)
    db.close(); return 0

if __name__ == "__main__":
    raise SystemExit(main())
