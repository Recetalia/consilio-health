#!/usr/bin/env python3
"""Expandir advertencias de CLASE a los fármacos concretos de esa clase.

## El problema que resuelve

Fenelzina + fluoxetina es IMAO + ISRS: síndrome serotoninérgico, potencialmente
fatal. No está en DDInter (no publica la categoría ATC N) y **ningún matcheo por
nombre puede encontrarla**, porque el prospecto de fluoxetina advierte sobre la
clase y nunca nombra a la fenelzina:

    • Monoamine Oxidase Inhibitors (MAOIs): (2.9, 2.10, 4.1, 5.2)

Medido: la clase MOA `N0000000184` tiene 34 miembros, fenelzina entre ellos.

## Cómo funciona

1. Vocabulario de clases EPC/MOA/PE de RxClass (3.410; se descartan las CHEM,
   que son sustancias sueltas y no clases).
2. Se buscan esos nombres dentro del texto `drug_interactions` de cada prospecto.
3. Cada mención se expande a los miembros de la clase, y se emite un par entre
   el fármaco del prospecto y cada miembro.

Todo offline. El par queda con `note` diciendo de qué clase salió, porque una
expansión es una inferencia más débil que una mención directa y quien lea la
alerta tiene que poder saberlo.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger("expand_class")

BASE = "https://rxnav.nlm.nih.gov/REST/rxclass"
USER_AGENT = "consilio-build"

# Tipos de clase que representan una CLASE de fármacos. CHEM queda afuera: son
# 10.364 entradas que en su mayoría son una sustancia sola.
CLASS_TYPES = ("EPC", "MOA", "PE")
RELA_BY_TYPE = {"EPC": "has_EPC", "MOA": "has_MoA", "PE": "has_PE"}

# Nombres cortos producen falsos positivos masivos ("Oxidase", "Agonist").
MIN_CLASS_NAME = 14
# Una clase enorme no aporta: si el prospecto dice "antibiotics", expandir a 400
# fármacos genera ruido, no información.
MAX_MEMBERS = 60

SENT_SPLIT = re.compile(r"(?<=[.;:])\s+(?=[A-Z(])|\s+(?=\d+\.\d+\s+[A-Z])")
SECTION_HEAD = re.compile(r"^\s*\d+(?:\.\d+)*\s+")
MAX_SENTENCE = 400
# Una expansión por clase ya es una inferencia débil. Si además la oración no
# dice nada ("Protease inhibitors:", un encabezado de tabla), no hay nada que
# afirmar. Medido: sin este filtro, 1.443 de los pares salían de ese encabezado,
# con cosas como moexipril + amiodarona — MED-RT mete a los IECA en "Protease
# Inhibitors" porque la ECA es una proteasa, pero el prospecto habla de los
# del VIH.
MIN_EVIDENCE = 60

# Clases donde lo que MED-RT agrupa no es lo que el prospecto quiere decir.
# Expandirlas produce pares sin sentido clínico.
CLASS_DENYLIST = {
    # MED-RT mete a los IECA acá porque la ECA es una proteasa; el prospecto
    # habla de los inhibidores de proteasa del VIH. Medido: 75 pares con un
    # IECA, y evidencia que ni siquiera hablaba del par.
    "Protease Inhibitors",
}

SEV_MAJOR = re.compile(
    r"\b(contraindicat\w*|should not be (?:used|administered|co-?administered)|"
    r"avoid (?:concomitant|concurrent|coadministration|combination|use)|"
    r"must not be|do not (?:use|administer|combine)|fatal|life-threatening)\b", re.I)
SEV_MODERATE = re.compile(
    r"\b(caution|monitor\w*|may (?:increase|decrease|reduce|enhance|potentiate|prolong)|"
    r"dose (?:adjustment|reduction))\b", re.I)


def classify(s: str) -> str:
    if SEV_MAJOR.search(s):
        return "major"
    if SEV_MODERATE.search(s):
        return "moderate"
    return "unknown"


def _get(path: str, params: dict, *, retries: int = 3) -> dict:
    # safe="+" porque RxNav espera classTypes=EPC+MOA+PE literal;
    # urlencode por defecto lo convierte en %2B y devuelve 400.
    url = f"{BASE}{path}?{urllib.parse.urlencode(params, safe='+')}"
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
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
    p.add_argument("--rate", type=float, default=8.0)
    args = p.parse_args()

    db = sqlite3.connect(args.db)
    delay = 1.0 / max(args.rate, 1.0)

    logger.info("Bajando el vocabulario de clases (%s)...", "+".join(CLASS_TYPES))
    payload = _get("/allClasses.json", {"classTypes": "+".join(CLASS_TYPES)})
    classes = payload.get("rxclassMinConceptList", {}).get("rxclassMinConcept", [])
    classes = [c for c in classes
               if len(c["className"]) >= MIN_CLASS_NAME
               and c["className"] not in CLASS_DENYLIST]
    logger.info("Clases buscables: %d", len(classes))

    # Un patrón por clase, tolerante al plural y a "Inhibitor/Inhibitors".
    patterns = [
        (c["classId"], c["classType"], c["className"],
         re.compile(rf"\b{re.escape(c['className'])}s?\b", re.I))
        for c in classes
    ]

    labels = db.execute(
        "select l.drug_id, d.canonical, l.text from drug_label_text l "
        "join drug d using(drug_id) "
        "where l.section='drug_interactions' and l.source='openfda'").fetchall()
    logger.info("Prospectos a escanear: %d", len(labels))

    # --- 1) qué clases se mencionan, y en qué oración ---
    mentions: dict[tuple[int, str], tuple[str, str, str]] = {}
    for drug_id, drug_name, text in labels:
        for sent in SENT_SPLIT.split(text):
            sent = SECTION_HEAD.sub("", sent.strip())
            if not (MIN_EVIDENCE <= len(sent) <= MAX_SENTENCE):
                continue
            for class_id, class_type, class_name, pat in patterns:
                if pat.search(sent):
                    key = (drug_id, class_id)
                    sev = classify(sent)
                    prev = mentions.get(key)
                    rank = {"major": 3, "moderate": 2, "unknown": 1}
                    if sev == "unknown":
                        # sin verbo de advertencia no se sostiene una expansión
                        continue
                    if prev is None or rank[sev] > rank[prev[0]]:
                        mentions[key] = (sev, sent[:1200], class_name)
    wanted = {cid for _, cid in mentions}
    logger.info("Menciones de clase: %d, sobre %d clases distintas",
                len(mentions), len(wanted))

    # --- 2) miembros de cada clase mencionada ---
    type_by_id = {c["classId"]: c["classType"] for c in classes}
    members: dict[str, set[int]] = {}
    by_name = {n.lower(): i for i, n in db.execute(
        "select drug_id, canonical from drug")}
    for i, class_id in enumerate(sorted(wanted), 1):
        time.sleep(delay)
        rela = RELA_BY_TYPE.get(type_by_id.get(class_id, ""), "has_EPC")
        try:
            d = _get("/classMembers.json",
                     {"classId": class_id, "relaSource": "MEDRT", "rela": rela})
        except Exception as exc:
            logger.warning("classMembers falló para %s: %s", class_id, exc)
            continue
        names = {m["minConcept"]["name"].lower()
                 for m in d.get("drugMemberGroup", {}).get("drugMember", [])}
        ids = {by_name[n] for n in names if n in by_name}
        if 0 < len(ids) <= MAX_MEMBERS:
            members[class_id] = ids
        if i % 50 == 0:
            logger.info("  clases resueltas %d/%d", i, len(wanted))
    logger.info("Clases con miembros utilizables: %d", len(members))

    # --- 3) emitir los pares ---
    now = datetime.now(timezone.utc).isoformat()
    # Borrar ANTES de leer `known`: si no, las filas de la corrida anterior se
    # cuentan como ya conocidas y el re-run emite cero.
    db.execute("delete from interaction where source='openfda' and note like 'clase:%'")
    known = {(a, b) for a, b in db.execute(
        "select drug_a_id, drug_b_id from interaction")}

    rank = {"major": 3, "moderate": 2, "unknown": 1}
    out: dict[tuple[int, int], tuple[str, str, str]] = {}
    for (host_id, class_id), (sev, sent, class_name) in mentions.items():
        for member_id in members.get(class_id, ()):
            if member_id == host_id:
                continue
            lo, hi = (host_id, member_id) if host_id < member_id else (member_id, host_id)
            if (lo, hi) in known:
                continue
            prev = out.get((lo, hi))
            if prev is None or rank[sev] > rank[prev[0]]:
                out[(lo, hi)] = (sev, sent, class_name)

    db.executemany(
        "insert or replace into interaction "
        "(drug_a_id, drug_b_id, severity, evidence, source, note, reviewed_at) "
        "values (?,?,?,?,'openfda',?,?)",
        [(a, b, s, ev, f"clase: {cn}", now) for (a, b), (s, ev, cn) in out.items()])
    db.execute("insert or replace into meta (key,value) values ('class_expanded_at',?)", (now,))
    db.commit()

    logger.info("=== RESULTADO ===")
    logger.info("pares nuevos por expansión de clase: %d", len(out))
    for sev, n in db.execute(
            "select severity, count(*) from interaction "
            "where source='openfda' and note like 'clase:%' group by severity order by 2 desc"):
        logger.info("  %-10s %d", sev, n)
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
