#!/usr/bin/env python3
"""Derivar pares de interacción del texto de los prospectos de la FDA.

Tapa el hueco de DDInter (pares donde ambas drogas son de categorías ATC no
publicadas: enalapril + losartán, sertralina + fluoxetina). openFDA es CC0.

## Cómo funciona

openFDA no tiene un endpoint "¿A interactúa con B?". Tiene el prospecto de A,
con una sección `drug_interactions` de texto libre. Así que para cada fármaco A
con texto se buscan los nombres de todos los demás dentro de ese texto, y el
match se guarda junto con **la oración** donde apareció.

Todo pasa offline. En runtime sólo se consulta la tabla.

## Por qué la severidad se evalúa sobre la oración

`drug_interactions` tiene varias páginas. Si se buscan las keywords sobre el
texto entero, un "contraindicated" que habla de otro fármaco tiñe de grave a
todos los pares del prospecto. Sobre la oración que matcheó, no.

## Por qué el umbral de nombre es alto

Buscar "Iron" o "Zinc" como substring encuentra cualquier cosa. Sólo se aceptan
nombres de 5+ caracteres, con límite de palabra, y se descartan los que son
palabras comunes del inglés médico.
"""

from __future__ import annotations

import argparse
import logging
import re
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger("derive_openfda")

MIN_NAME_LEN = 5

# Nombres de fármaco que también son palabras corrientes del texto de un
# prospecto. Buscarlos produce falsos positivos en masa.
STOPNAMES = {
    "water", "oxygen", "alcohol", "nitrogen", "glucose", "dextrose", "sucrose",
    "lactose", "starch", "sodium", "calcium", "potassium", "magnesium", "iron",
    "zinc", "copper", "iodine", "sulfur", "carbon", "protein", "insulin",
    "estrogen", "estrogens", "progesterone", "testosterone", "cortisone",
    "epinephrine", "histamine", "serotonin", "dopamine", "melatonin", "caffeine",
    "nicotine", "heparin", "aspirin", "vaccine", "plasma", "albumin", "gelatin",
    "mineral", "vitamin", "urea", "acid", "salt", "base", "gas", "air", "oil",
}

SEV_MAJOR = re.compile(
    r"\b(contraindicat\w*|should not be (?:used|administered|co-?administered)|"
    r"avoid (?:concomitant|concurrent|coadministration|combination)|"
    r"must not be|do not (?:use|administer|combine)|fatal|life-threatening)\b", re.I)
SEV_MODERATE = re.compile(
    r"\b(caution|monitor\w*|may (?:increase|decrease|reduce|enhance|potentiate|prolong)|"
    r"dose (?:adjustment|reduction)|consider reducing|closely observed?)\b", re.I)

# Separar oraciones en un prospecto no es separar por punto. El texto trae
# numeración de secciones ("7.1 Impact of Other Drugs"), viñetas y tablas
# aplanadas. Sin contemplarlas, una "oración" termina siendo media sección y
# empareja fármacos que no tienen nada que ver entre sí.
SENT_SPLIT = re.compile(
    r"(?<=[.;:])\s+(?=[A-Z(])"          # fin de oración normal
    r"|\s+(?=\d+\.\d+\s+[A-Z])"         # "7.1 Impact of…"
    r"|\s+(?=•|•|\-\s+[A-Z])"      # viñetas
)
MAX_SENTENCE = 400

# El texto SPL viene aplanado y los encabezados de sección no terminan en punto,
# así que quedan pegados al principio de la oración siguiente ("7.1 Impact of
# Other Drugs on Amlodipine CYP3A Inhibitors Co-administration con…").
SECTION_HEAD = re.compile(r"^\s*\d+(?:\.\d+)*\s+")

# Un fármaco nombrado dentro de "(e.g., a, b, c)" está ahí como ejemplo de una
# clase, no porque el prospecto afirme algo sobre él. Contarlo genera un par por
# cada miembro de la lista, y ninguno es una interacción declarada.
PAREN = re.compile(r"\(([^()]*)\)")
ENUM_HINT = re.compile(r"\be\.?g\.?\b|\bsuch as\b|\bincluding\b|\bfor example\b", re.I)


def in_enumeration(sentence: str, start: int, end: int) -> bool:
    """¿El match cae dentro de un paréntesis que enumera una clase?"""
    for m in PAREN.finditer(sentence):
        if m.start() < start and end < m.end():
            inner = m.group(1)
            if ENUM_HINT.search(inner) or inner.count(",") >= 2:
                return True
    return False


def classify(sentence: str) -> str:
    if SEV_MAJOR.search(sentence):
        return "major"
    if SEV_MODERATE.search(sentence):
        return "moderate"
    return "unknown"          # nunca 'major' por defecto: eso infla toda la rama


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default="data/recetalia_interactions.db")
    p.add_argument("--only-missing", action="store_true", default=True,
                   help="sólo pares que DDInter no tiene (por defecto)")
    p.add_argument("--include-known", dest="only_missing", action="store_false",
                   help="también los que DDInter ya tiene, para poder comparar")
    args = p.parse_args()

    db = sqlite3.connect(args.db)
    migrate(db)

    names: dict[int, str] = {}
    for drug_id, canonical in db.execute("select drug_id, canonical from drug"):
        n = canonical.strip()
        if len(n) >= MIN_NAME_LEN and n.lower() not in STOPNAMES and " " not in n:
            names[drug_id] = n
    logger.info("Nombres buscables: %d de %d fármacos",
                len(names), db.execute("select count(*) from drug").fetchone()[0])

    patterns = {did: re.compile(rf"\b{re.escape(n)}\w{{0,3}}\b", re.I)
                for did, n in names.items()}

    labels = db.execute(
        "select drug_id, text from drug_label_text "
        "where section='drug_interactions' and source='openfda'").fetchall()
    logger.info("Prospectos con texto de interacciones: %d", len(labels))
    if not labels:
        logger.error("No hay textos. Corré antes `fetch_openfda_labels`.")
        return 1

    known = {(a, b) for a, b in db.execute(
        "select drug_a_id, drug_b_id from interaction where source='ddinter'")}

    now = datetime.now(timezone.utc).isoformat()
    db.execute("delete from interaction where source='openfda'")

    derived: dict[tuple[int, int], tuple[str, str]] = {}
    dropped = {"larga": 0, "enumeracion": 0}
    for host_id, text in labels:
        for sent in SENT_SPLIT.split(text):
            sent = SECTION_HEAD.sub("", sent.strip())
            if len(sent) < 20:
                continue
            if len(sent) > MAX_SENTENCE:
                # es un bloque de sección, no una afirmación: no se puede
                # atribuir el match a un par concreto
                dropped["larga"] += 1
                continue
            for other_id, pat in patterns.items():
                if other_id == host_id:
                    continue
                m = pat.search(sent)
                if not m:
                    continue
                if in_enumeration(sent, m.start(), m.end()):
                    dropped["enumeracion"] += 1
                    continue
                lo, hi = (host_id, other_id) if host_id < other_id else (other_id, host_id)
                if args.only_missing and (lo, hi) in known:
                    continue
                sev = classify(sent)
                prev = derived.get((lo, hi))
                # nos quedamos con la oración de mayor severidad; a igualdad, la más larga
                rank = {"major": 3, "moderate": 2, "unknown": 1}
                if prev is None or rank[sev] > rank[prev[0]] or (
                        rank[sev] == rank[prev[0]] and len(sent) > len(prev[1])):
                    derived[(lo, hi)] = (sev, sent.strip()[:1500])

    db.executemany(
        "insert or replace into interaction "
        "(drug_a_id, drug_b_id, severity, evidence, source, reviewed_at) "
        "values (?,?,?,?,'openfda',?)",
        [(a, b, s, ev, now) for (a, b), (s, ev) in derived.items()])
    db.execute("insert or replace into meta (key, value) values ('openfda_derived_at',?)",
               (now,))
    db.commit()

    logger.info("=== RESULTADO ===")
    logger.info("descartados: %d por bloque largo, %d por enumeración de clase",
                dropped["larga"], dropped["enumeracion"])
    logger.info("pares derivados: %d %s", len(derived),
                "(sólo los que DDInter no tiene)" if args.only_missing else "")
    for sev, n in db.execute(
            "select severity, count(*) from interaction where source='openfda' "
            "group by severity order by 2 desc"):
        logger.info("  %-10s %d", sev, n)
    db.close()
    return 0


def migrate(db: sqlite3.Connection) -> None:
    """Agrega `evidence` y permite source='openfda'.

    SQLite no deja alterar un CHECK: hay que recrear la tabla. Se preserva todo.
    """
    ddl = db.execute(
        "select sql from sqlite_master where type='table' and name='interaction'"
    ).fetchone()
    if ddl and "'openfda'" in ddl[0]:
        return
    logger.info("Migrando `interaction`: +evidence, source permite 'openfda'")
    db.executescript("""
        PRAGMA foreign_keys=off;
        ALTER TABLE interaction RENAME TO interaction_old;
        CREATE TABLE interaction (
            drug_a_id   INTEGER NOT NULL REFERENCES drug(drug_id),
            drug_b_id   INTEGER NOT NULL REFERENCES drug(drug_id),
            severity    TEXT    NOT NULL CHECK (severity IN ('minor','moderate','major','unknown')),
            mechanism   TEXT,
            management  TEXT,
            evidence    TEXT,
            source      TEXT    NOT NULL CHECK (source IN ('ddinter','openfda','recetalia')),
            reviewed_by TEXT,
            reviewed_at TEXT,
            note        TEXT,
            PRIMARY KEY (drug_a_id, drug_b_id, source),
            CHECK (drug_a_id < drug_b_id)
        );
        INSERT INTO interaction
            (drug_a_id, drug_b_id, severity, mechanism, management, source,
             reviewed_by, reviewed_at, note)
        SELECT drug_a_id, drug_b_id, severity, mechanism, management, source,
               reviewed_by, reviewed_at, note FROM interaction_old;
        DROP TABLE interaction_old;
        CREATE INDEX IF NOT EXISTS idx_ix_a ON interaction(drug_a_id);
        CREATE INDEX IF NOT EXISTS idx_ix_b ON interaction(drug_b_id);
        PRAGMA foreign_keys=on;
    """)
    db.commit()


if __name__ == "__main__":
    raise SystemExit(main())
