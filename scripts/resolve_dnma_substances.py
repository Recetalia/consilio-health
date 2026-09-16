#!/usr/bin/env python3
"""Resolver las sustancias del DNMA contra la base de interacciones.

Llena `dnma_substance_map`: SUSTANCIA_ID -> drug_id, con el método y el motivo.

## Por qué no alcanza con el score de RxNorm

`approximateTerm` devuelve un score que **no discrimina**. Medido el 2026-09-15:

    ibuprofen            10.5   (match perfecto)
    warfarin             12.1
    diclofenac potasico  11.5   (resuelve bien)
    xyzzy nonsense drug   9.4   (cadena inventada)

Una cadena sin sentido puntúa casi igual que un match perfecto. Cualquier umbral
que acepte los buenos acepta también la basura. El repo original exige
`score >= 80`, que ningún valor real alcanza: la rama aproximada es código muerto
y por eso el crosswalk salió 100% exacto.

Bajar el umbral sería peor que dejarlo roto. Mapear en silencio una sustancia
desconocida al fármaco equivocado produce advertencias con nombre y apellido
sobre algo que el paciente no toma. Un "no evaluable" honesto es mejor.

Por eso acá el score sólo ordena candidatos: **la aceptación la decide el
nombre**. Se trae el nombre del candidato y se compara con el que preguntamos.
"""

from __future__ import annotations

import argparse
import difflib
import json
import logging
import re
import sqlite3
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from scripts.build_recetalia_db import SCHEMA

logger = logging.getLogger("resolve_dnma")

BASE = "https://rxnav.nlm.nih.gov/REST"
USER_AGENT = "recetalia-interactions-build"

SIMILARITY_MIN = 0.85

SALTS = (
    "potasico", "sodico", "calcico", "magnesico", "clorhidrato", "hidrocloruro",
    "bromhidrato", "sulfato", "maleato", "tartrato", "bitartrato", "succinato",
    "fumarato", "mesilato", "besilato", "acetato", "propionato", "valerato",
    "dipropionato", "furoato", "palmitato", "estearato", "estolato", "fosfato",
    "nitrato", "bromuro", "cloruro", "yoduro", "citrato", "trometamina",
    "gluconato", "lactato", "malato", "oxalato", "pamoato", "salicilato",
    "carbonato", "monosodico", "disodico", "dihidratado", "monohidrato",
    "anhidro", "micronizado",
)

# Lo que no es un fármaco con interacciones documentables. No es una falla de
# cobertura: es una sustancia que nunca va a estar en una base de interacciones.
NOT_A_DRUG = re.compile(r"""
 vacuna|toxoide|inmunoglobulina|antisuero|bacilo|antigeno|alergeno|
 extracto|aceite\s|cera\b|talco|almidon|glicerol|glicerina|vaselina|parafina|
 ^agua$|solucion|cloruro\s+de\s+sodio|dextrosa|manitol|sorbitol|
 vitamina|tocoferol|retinol|calciferol|caroteno|
 oxido\b|dioxido|peroxido|^azufre$|^carbon|caolin|bentonita|silice|silicato|
 factor\s+[ivx]+|plasma|albumina\s+humana|
 espirulina|spirulina|levadura|probiotic|lactobacil|bifidobact|
 homeopat|placebo|excipiente|colorante|edulcorante|
 ^gas\b|nitrogeno|^oxigeno$|helio|
 contraste|gadolinio|iohexol|iopamidol|^bario|tecnecio
""", re.X | re.I)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def strip_salt(s: str) -> str:
    salts = "|".join(SALTS)
    s = re.sub(rf"\b(?:de|del)\s+(?:{salts})\b", " ", s)
    s = re.sub(rf"^(?:{salts})\s+de\s+", "", s)
    s = re.sub(rf"\b(?:{salts})\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _get(path: str, params: dict, *, timeout: float = 20.0, retries: int = 3) -> dict:
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
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


def rxnorm_name(rxcui: str, cache: dict[str, str | None], delay: float) -> str | None:
    if rxcui in cache:
        return cache[rxcui]
    time.sleep(delay)
    try:
        d = _get(f"/rxcui/{rxcui}/property.json", {"propName": "RxNormName"})
        props = d.get("propConceptGroup", {}).get("propConcept", [])
        cache[rxcui] = props[0].get("propValue") if props else None
    except Exception:
        cache[rxcui] = None
    return cache[rxcui]


def similar(a: str, b: str) -> float:
    """Parecido entre dos nombres ya normalizados."""
    if a == b:
        return 1.0
    ta, tb = set(a.split()), set(b.split())
    if ta and (ta <= tb or tb <= ta):       # uno contiene al otro, por tokens
        return 0.95
    return difflib.SequenceMatcher(None, a, b).ratio()


def resolve(name: str, cache: dict, delay: float) -> tuple[str | None, str, float]:
    """Devuelve (rxcui, metodo, similitud). metodo ∈ exact|approximate|unresolved."""
    clean = strip_salt(norm(name))
    if not clean:
        return None, "unresolved", 0.0

    for term in dict.fromkeys([clean, norm(name)]):     # limpio primero
        time.sleep(delay)
        try:
            d = _get("/rxcui.json", {"name": term, "search": "2"})
        except Exception:
            continue
        ids = d.get("idGroup", {}).get("rxnormId") or []
        if ids:
            return ids[0], "exact", 1.0

    time.sleep(delay)
    try:
        d = _get("/approximateTerm.json", {"term": clean, "maxEntries": "20"})
    except Exception:
        return None, "unresolved", 0.0

    seen: list[str] = []
    for c in d.get("approximateGroup", {}).get("candidate", []):
        rxcui = c.get("rxcui")
        if not rxcui or rxcui in seen:
            continue
        seen.append(rxcui)
        if len(seen) > 3:                    # los 3 mejores distintos, nada más
            break
        cand = rxnorm_name(rxcui, cache, delay)
        if not cand:
            continue
        score = similar(clean, strip_salt(norm(cand)))
        if score >= SIMILARITY_MIN:
            return rxcui, "approximate", score
    return None, "unresolved", 0.0


def load_dnma(dump: Path) -> list[tuple[str, str]]:
    src = dump.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"INSERT INTO `sustancia` VALUES (.*?);\n", src, re.S)
    if not m:
        raise SystemExit(f"No encontré INSERT INTO `sustancia` en {dump}")
    out = []
    for t in re.findall(r"\(((?:[^()']|'(?:[^'\\]|\\.)*')*)\)", m.group(1)):
        f = [a if a else b for a, b in re.findall(r"'((?:[^'\\]|\\.)*)'|(NULL)", t)]
        if len(f) >= 2:
            out.append((f[0], f[1]))
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default="data/recetalia_interactions.db")
    p.add_argument("--dump", required=True, help="dump SQL del schema dnma")
    p.add_argument("--rate", type=float, default=12.0)
    p.add_argument("--limit", type=int)
    args = p.parse_args()

    db = sqlite3.connect(args.db)
    db.executescript(SCHEMA)
    by_rxcui = {r: d for r, d in db.execute(
        "select rxcui, drug_id from drug where rxcui is not null")}

    subs = load_dnma(Path(args.dump))
    if args.limit:
        subs = subs[:args.limit]
    logger.info("Sustancias del DNMA: %d", len(subs))

    delay = 1.0 / max(args.rate, 1.0)
    cache: dict[str, str | None] = {}
    now = datetime.now(timezone.utc).isoformat()
    stats: dict[str, int] = {}

    for i, (sid, dsc) in enumerate(subs, 1):
        if NOT_A_DRUG.search(norm(dsc)):
            method, rxcui, score, note = "unresolvable", None, None, "no es un fármaco"
        else:
            rxcui, method, score = resolve(dsc, cache, delay)
            note = None
            if rxcui and rxcui not in by_rxcui:
                note = f"rxcui {rxcui} fuera de la base de interacciones"
        drug_id = by_rxcui.get(rxcui) if rxcui else None
        if method in ("exact", "approximate") and drug_id is None:
            method = "unresolved" if note is None else method

        key = method if drug_id or method == "unresolvable" else f"{method}_sin_droga"
        stats[key] = stats.get(key, 0) + 1
        db.execute(
            "insert or replace into dnma_substance_map "
            "(sustancia_id, sustancia_dsc, drug_id, match_method, match_score, note, updated_at) "
            "values (?,?,?,?,?,?,?)",
            (sid, dsc, drug_id, method,
             int(score * 100) if score else None, note, now))

        if i % 200 == 0:
            db.commit()
            logger.info("  %d/%d  %s", i, len(subs), stats)

    db.execute("insert or replace into meta (key, value) values ('dnma_resolved_at',?)", (now,))
    db.commit()

    total = len(subs)
    resolved = db.execute(
        "select count(*) from dnma_substance_map where drug_id is not null").fetchone()[0]
    unresolvable = db.execute(
        "select count(*) from dnma_substance_map where match_method='unresolvable'").fetchone()[0]
    real = total - unresolvable
    logger.info("=== RESULTADO ===")
    for k, v in sorted(stats.items(), key=lambda x: -x[1]):
        logger.info("  %-24s %5d  %5.1f%%", k, v, v / total * 100)
    logger.info("cobertura sobre %d fármacos reales: %d = %.1f%%",
                real, resolved, resolved / real * 100)
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
