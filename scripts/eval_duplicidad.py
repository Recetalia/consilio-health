#!/usr/bin/env python3
"""Métrica de duplicidad: corre los casos clínicos y dice cuántos acierta.

Es lo que corre la routine semanal: un refresco de fuentes que rompe un caso
aparece acá antes que en una receta. Sale con código 1 si falla alguno.

    .venv/bin/python scripts/eval_duplicidad.py [--json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app.clients import recetalia_db  # noqa: E402
from app.services.duplicity_checker import chequear, cumple  # noqa: E402

CASOS = os.path.join(os.path.dirname(__file__), "..", "tests", "regression",
                     "casos_duplicidad.json")


async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    casos = json.load(open(CASOS, encoding="utf-8"))
    filas = []
    for c in casos:
        prods = [{"id": f"p{i}", "substances": s} for i, s in enumerate(c["productos"])]
        out = await chequear(recetalia_db.client, prods)
        ok, motivo = cumple(out, c["esperado"])
        if out["duplicity_not_evaluated"]:
            ok, motivo = False, f"no resolvieron: {out['duplicity_not_evaluated']}"
        filas.append({"caso": c["nombre"], "ok": ok, "motivo": motivo})
    await recetalia_db.client.close()
    aciertos = sum(f["ok"] for f in filas)
    if args.json:
        print(json.dumps({"aciertos": aciertos, "total": len(filas), "casos": filas},
                         ensure_ascii=False, indent=2))
    else:
        for f in filas:
            print(("OK  " if f["ok"] else "FALLA ") + f["caso"] + (f"  — {f['motivo']}" if f["motivo"] else ""))
        print(f"\n{aciertos}/{len(filas)} casos")
    return 0 if aciertos == len(filas) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
