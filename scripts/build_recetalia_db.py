#!/usr/bin/env python3
"""Build the Recetalia interaction database.

Seeds from a DDInter artefact and layers Recetalia's own curation on top. The
two never share a row: every fact carries its `source`, so re-seeding from a
newer DDInter release replaces only the rows we did not author.

That separation is the whole point of this script. Editing the DDInter tables in
place would work until the first re-seed, which would silently discard months of
pharmacist review.

Usage:
    python -m scripts.build_recetalia_db seed   --from data/ddinter.db
    python -m scripts.build_recetalia_db stats
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("build_recetalia_db")

DEFAULT_SOURCE = "data/ddinter.db"
DEFAULT_TARGET = "data/recetalia_interactions.db"

SEVERITIES = ("minor", "moderate", "major", "unknown")

SCHEMA = """
PRAGMA journal_mode = WAL;

-- Un fármaco, sea de donde venga. `ddinter_id` queda NULL para los que agreguemos
-- nosotros y DDInter no conozca (dipirona, por ejemplo).
CREATE TABLE IF NOT EXISTS drug (
    drug_id      INTEGER PRIMARY KEY,
    canonical    TEXT    NOT NULL UNIQUE,   -- nombre canónico, inglés
    rxcui        TEXT,
    ddinter_id   TEXT    UNIQUE,
    atc          TEXT,
    source       TEXT    NOT NULL CHECK (source IN ('ddinter','recetalia')),
    created_at   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_drug_rxcui ON drug(rxcui);

-- Cualquier nombre por el que se pueda llegar a un fármaco: sinónimos de RxNorm,
-- marcas comerciales, y sobre todo los nombres en español del DNMA.
CREATE TABLE IF NOT EXISTS drug_alias (
    drug_id    INTEGER NOT NULL REFERENCES drug(drug_id) ON DELETE CASCADE,
    alias      TEXT    NOT NULL,
    alias_norm TEXT    NOT NULL,            -- minúsculas, sin acentos, sin sal
    lang       TEXT    NOT NULL DEFAULT 'en',
    source     TEXT    NOT NULL CHECK (source IN ('ddinter','rxnorm','dnma','manual','aemps')),
    PRIMARY KEY (drug_id, alias_norm)
);
CREATE INDEX IF NOT EXISTS idx_alias_norm ON drug_alias(alias_norm);

-- El par. `source` distingue lo heredado de lo nuestro; `supersedes_source`
-- permite que una fila nuestra tape a una de DDInter sin borrarla.
CREATE TABLE IF NOT EXISTS interaction (
    drug_a_id         INTEGER NOT NULL REFERENCES drug(drug_id),
    drug_b_id         INTEGER NOT NULL REFERENCES drug(drug_id),
    severity          TEXT    NOT NULL CHECK (severity IN ('minor','moderate','major','unknown')),
    mechanism         TEXT,                 -- DDInter no lo trae; lo cargamos nosotros
    management        TEXT,                 -- ídem
    evidence          TEXT,                 -- la oración del prospecto, para source='openfda'
    source            TEXT    NOT NULL CHECK (source IN ('ddinter','openfda','recetalia')),
    reviewed_by       TEXT,
    reviewed_at       TEXT,
    note              TEXT,
    PRIMARY KEY (drug_a_id, drug_b_id, source),
    CHECK (drug_a_id < drug_b_id)           -- par canónico: sin (a,b) y (b,a)
);
CREATE INDEX IF NOT EXISTS idx_ix_a ON interaction(drug_a_id);
CREATE INDEX IF NOT EXISTS idx_ix_b ON interaction(drug_b_id);

-- SUSTANCIA_ID del DNMA -> fármaco. Es nuestro puente con el vademécum uruguayo.
CREATE TABLE IF NOT EXISTS dnma_substance_map (
    sustancia_id   TEXT PRIMARY KEY,
    sustancia_dsc  TEXT    NOT NULL,        -- el nombre en español, tal cual
    drug_id        INTEGER REFERENCES drug(drug_id),
    match_method   TEXT    NOT NULL CHECK (match_method IN
                       ('exact','approximate','manual','unresolvable','unresolved')),
    match_score    INTEGER,
    note           TEXT,
    updated_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dnma_drug ON dnma_substance_map(drug_id);

-- Una patología. Guardamos el código en el sistema en que vino; el puente entre
-- sistemas vive en condition_xref, no acá, porque un mismo cuadro tiene código
-- distinto en MeSH, CIE-10 y CIE-10-CM y ninguno es "el verdadero".
CREATE TABLE IF NOT EXISTS condition (
    condition_id INTEGER PRIMARY KEY,
    code_system  TEXT NOT NULL CHECK (code_system IN ('mesh','icd10','icd10cm','icd10gm','snomed')),
    code         TEXT NOT NULL,
    name         TEXT NOT NULL,
    source       TEXT NOT NULL,
    UNIQUE (code_system, code)
);

CREATE TABLE IF NOT EXISTS condition_xref (
    from_id  INTEGER NOT NULL REFERENCES condition(condition_id) ON DELETE CASCADE,
    to_id    INTEGER NOT NULL REFERENCES condition(condition_id) ON DELETE CASCADE,
    method   TEXT    NOT NULL,          -- umls | mondo | manual | truncation
    source   TEXT    NOT NULL,
    PRIMARY KEY (from_id, to_id, method)
);

-- Alerta fármaco-paciente. Mismo criterio de procedencia que `interaction`:
-- un re-fetch de MED-RT borra sólo lo suyo.
CREATE TABLE IF NOT EXISTS drug_condition_alert (
    drug_id      INTEGER NOT NULL REFERENCES drug(drug_id),
    condition_id INTEGER NOT NULL REFERENCES condition(condition_id),
    kind         TEXT    NOT NULL CHECK (kind IN ('contraindication','precaution')),
    rela         TEXT,                  -- ci_with | ci_chemclass | ci_moa | ci_pe
    detail       TEXT,
    source       TEXT    NOT NULL CHECK (source IN ('medrt','interpolar','openfda','recetalia')),
    reviewed_by  TEXT,
    reviewed_at  TEXT,
    note         TEXT,
    PRIMARY KEY (drug_id, condition_id, kind, source)
);
CREATE INDEX IF NOT EXISTS idx_dca_drug ON drug_condition_alert(drug_id);
CREATE INDEX IF NOT EXISTS idx_dca_cond ON drug_condition_alert(condition_id);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _norm(s: str) -> str:
    """Normaliza un nombre para matchear: minúsculas, sin acentos, sin sal."""
    import re
    import unicodedata

    s = unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
    salts = (
        "potasico", "sodico", "calcico", "magnesico", "clorhidrato", "hidrocloruro",
        "sulfato", "maleato", "tartrato", "succinato", "fumarato", "mesilato",
        "besilato", "acetato", "fosfato", "nitrato", "bromuro", "citrato",
        "trometamina", "dihidratado", "monohidrato", "anhidro",
    )
    for salt in salts:
        s = s.replace(salt, "")
    return re.sub(r"[^a-z0-9 ]+", " ", re.sub(r"\s+", " ", s)).strip()


def cmd_seed(args: argparse.Namespace) -> int:
    src_path, dst_path = Path(args.source), Path(args.target)
    if not src_path.exists():
        logger.error("No existe %s — corré antes `build_ddinter_db build`", src_path)
        return 1
    if dst_path.exists() and not args.force:
        logger.error("%s ya existe. Usá --force para re-seedear.", dst_path)
        return 1

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    if args.force and dst_path.exists():
        dst_path.unlink()

    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    dst = sqlite3.connect(dst_path)
    dst.executescript(SCHEMA)
    now = datetime.now(timezone.utc).isoformat()

    # --- drogas ---
    names: dict[str, str] = {}          # ddinter_id -> nombre
    for a_id, a_name, b_id, b_name in src.execute(
        "select drug_a_id, drug_a_name, drug_b_id, drug_b_name from interactions"
    ):
        names.setdefault(a_id, a_name)
        names.setdefault(b_id, b_name)

    rx = {d: (r, c) for r, d, c in src.execute(
        "select rxcui, ddinter_id, canonical_name from rxnorm_to_ddinter"
    )}

    dst.executemany(
        "insert into drug (canonical, rxcui, ddinter_id, source, created_at) "
        "values (?,?,?,'ddinter',?)",
        [(n, rx.get(d, (None, None))[0], d, now) for d, n in sorted(names.items())],
    )
    ids = {d: i for i, d in dst.execute("select drug_id, ddinter_id from drug")}

    # --- alias: el nombre propio y el canónico de RxNorm si difiere ---
    aliases = []
    for ddid, name in names.items():
        did = ids[ddid]
        aliases.append((did, name, _norm(name), "en", "ddinter"))
        canon = rx.get(ddid, (None, None))[1]
        if canon and _norm(canon) != _norm(name):
            aliases.append((did, canon, _norm(canon), "en", "rxnorm"))
    dst.executemany(
        "insert or ignore into drug_alias (drug_id, alias, alias_norm, lang, source) "
        "values (?,?,?,?,?)", aliases)

    # --- interacciones, con el par ordenado para no duplicar (a,b)/(b,a) ---
    pairs, skipped = [], 0
    for a_id, b_id, sev in src.execute(
            "select drug_a_id, drug_b_id, severity from interactions"):
        a, b = ids[a_id], ids[b_id]
        if a == b:
            skipped += 1
            continue
        lo, hi = (a, b) if a < b else (b, a)
        pairs.append((lo, hi, sev.lower()))
    before = len(pairs)
    pairs = list({(a, b): (a, b, s) for a, b, s in pairs}.values())
    dst.executemany(
        "insert or ignore into interaction (drug_a_id, drug_b_id, severity, source) "
        "values (?,?,?,'ddinter')", pairs)

    meta = {k: v for k, v in src.execute("select key, value from meta")}
    meta.update({
        "recetalia_seeded_at": now,
        "recetalia_seed_source": str(src_path),
        "recetalia_schema_version": "1",
    })
    dst.executemany("insert or replace into meta (key, value) values (?,?)",
                    sorted(meta.items()))
    dst.commit()

    n_drug = dst.execute("select count(*) from drug").fetchone()[0]
    n_ix = dst.execute("select count(*) from interaction").fetchone()[0]
    n_al = dst.execute("select count(*) from drug_alias").fetchone()[0]
    logger.info("Escrito %s", dst_path)
    logger.info("  fármacos    %d", n_drug)
    logger.info("  alias       %d", n_al)
    logger.info("  interaccs.  %d  (colapsados %d simétricos, %d auto-pares)",
                n_ix, before - len(pairs), skipped)
    dst.close()
    src.close()
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    db = sqlite3.connect(f"file:{Path(args.target)}?mode=ro", uri=True)
    print("fármacos por origen:",
          dict(db.execute("select source, count(*) from drug group by source")))
    print("interacciones por origen:",
          dict(db.execute("select source, count(*) from interaction group by source")))
    print("severidad:",
          dict(db.execute("select severity, count(*) from interaction group by severity")))
    print("con mecanismo propio:",
          db.execute("select count(*) from interaction where mechanism is not null").fetchone()[0])
    print("mapeo DNMA:",
          dict(db.execute("select match_method, count(*) from dnma_substance_map "
                          "group by match_method")) or "vacío")
    print("meta:", json.dumps(
        dict(db.execute("select key, value from meta")), indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed", help="Crear la DB de Recetalia desde un artefacto DDInter")
    s.add_argument("--from", dest="source", default=DEFAULT_SOURCE)
    s.add_argument("--target", default=DEFAULT_TARGET)
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_seed)

    t = sub.add_parser("stats", help="Resumen de lo que hay adentro")
    t.add_argument("--target", default=DEFAULT_TARGET)
    t.set_defaults(func=cmd_stats)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
