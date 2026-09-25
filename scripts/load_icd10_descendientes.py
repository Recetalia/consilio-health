#!/usr/bin/env python3
"""Subcódigos CIE-10-CM de los anclajes: `N18.5` para el N18 que ya tenemos.

## El problema

`search_conditions` sólo ofrece los 552 anclajes (`condition.code_system=
'icd10cm'`): son los códigos a los que hay una alerta colgada. Un médico que
tipea `N18` sólo ve `N18` y `N18.9` — nunca `N18.5 — Chronic kidney disease,
stage 5`, porque ese código no existe en `condition`. El backend ya lo evalúa
bien (`condition_ids_for_icd10` sube por truncación hasta el anclaje), el
problema es sólo de **oferta**: no se puede elegir lo que no está.

## Qué carga

Todo el catálogo CMS 2026 (`data/icd10/icd10cm_order_2026.txt`, formato de
ancho fijo documentado en `data/icd10/icd10OrderFiles.pdf`) cuyo prefijo sea
un anclaje existente y que no sea el anclaje mismo. Cada fila lleva el
`anchor_code` más largo que la prefija — el mismo criterio de "ancestro más
específico" que ya usa `condition_ids_for_icd10` por truncación en runtime,
resuelto acá una sola vez en vez de en cada consulta.

Los anclajes de tipo RANGO (`K70-K77`) no son códigos reales y no se usan como
prefijo: no tiene sentido decir que `K71` es "hijo" de un guion.

## No se toca `condition` ni `condition_xref`

`icd10_descendant` es una tabla aparte, de sólo lectura para la app. No hace
falta traducir los descendientes a MeSH: la alerta ya cuelga del anclaje, y
`search_conditions` cuenta las alertas del anclaje para cada descendiente que
resuelve a él.

## Formato del catálogo (posiciones 1-indexadas, ver el PDF)

    1-5    número de orden
    7-13   código, SIN puntos
    15     '0' header (no facturable) / '1' válido para HIPAA
    17-76  descripción corta
    78-fin descripción larga
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("load_icd10_descendientes")

DEFAULT_CATALOG = Path("data/icd10/icd10cm_order_2026.txt")
DEFAULT_DB = "data/recetalia_interactions.db"

_SCHEMA = """
create table if not exists icd10_descendant (
    code text primary key,
    name text not null,
    anchor_code text not null
)
"""


def format_code(raw: str) -> str:
    """`N185` -> `N18.5`. El catálogo CMS no trae puntos; los códigos de
    `condition` sí, a partir del cuarto carácter."""
    raw = raw.strip()
    return raw if len(raw) <= 3 else f"{raw[:3]}.{raw[3:]}"


def parse_catalog(path: Path) -> list[tuple[str, str]]:
    """[(código sin puntos, nombre)] para cada línea del order file.

    El nombre sale de la descripción larga (más completa); si falta, de la
    corta. Las líneas vacías al final del archivo se ignoran.
    """
    out: list[tuple[str, str]] = []
    for line in path.read_text(encoding="latin-1").splitlines():
        if not line.strip():
            continue
        code = line[6:13].strip()
        if not code:
            continue
        short = line[16:76].strip()
        long_ = line[77:].strip()
        out.append((code, long_ or short))
    return out


def anchors_by_plain(db: sqlite3.Connection) -> dict[str, str]:
    """plain(code) -> code, para los anclajes reales (sin los rangos)."""
    rows = db.execute(
        "select code from condition where code_system='icd10cm' and code not like '%-%'"
    ).fetchall()
    return {code.replace(".", ""): code for (code,) in rows}


def longest_anchor(plain_code: str, anchors: dict[str, str]) -> str | None:
    """El anclaje más específico que prefija `plain_code`, o `None`.

    Prefijo PROPIO: el propio anclaje nunca es su descendiente. Se prueba de
    más largo a más corto, igual que `condition_ids_for_icd10` al truncar.
    """
    for n in range(len(plain_code) - 1, 2, -1):
        hit = anchors.get(plain_code[:n])
        if hit is not None:
            return hit
    return None


def build_descendants(
    catalog_rows: list[tuple[str, str]], anchors: dict[str, str]
) -> list[tuple[str, str, str]]:
    """[(code con puntos, name, anchor_code)]."""
    out = []
    for raw, name in catalog_rows:
        if len(raw) <= 3:
            continue          # no puede tener un anclaje propio más corto
        if raw in anchors:
            continue          # ya es un anclaje: no es descendiente de sí mismo
        anchor = longest_anchor(raw, anchors)
        if anchor is None:
            continue
        out.append((format_code(raw), name, anchor))
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--catalog", default=str(DEFAULT_CATALOG), type=Path)
    p.add_argument("--dry-run", action="store_true",
                   help="no escribe: sólo cuenta y muestra 10 ejemplos")
    args = p.parse_args()

    if not args.catalog.exists():
        logger.error("No existe el catálogo: %s", args.catalog)
        return 1

    db = sqlite3.connect(args.db)
    anchors = anchors_by_plain(db)
    logger.info("Anclajes icd10cm (sin rangos): %d", len(anchors))

    catalog_rows = parse_catalog(args.catalog)
    logger.info("Filas del catálogo CMS: %d", len(catalog_rows))

    descendants = build_descendants(catalog_rows, anchors)
    logger.info("Descendientes resueltos: %d", len(descendants))

    if args.dry_run:
        sorted_desc = sorted(descendants, key=lambda d: d[0])
        examples = sorted_desc[:9]
        n185 = next((d for d in descendants if d[0] == "N18.5"), None)
        if n185 is not None and n185 not in examples:
            examples.append(n185)
        elif len(sorted_desc) > 9:
            examples.append(sorted_desc[9])
        logger.info("=== DRY RUN ===")
        logger.info("cargaría %d descendientes", len(descendants))
        for code, name, anchor in examples[:10]:
            logger.info("  %-9s -> anclaje %-9s  %s", code, anchor, name)
        db.close()
        return 0

    db.execute(_SCHEMA)
    db.execute("delete from icd10_descendant")
    db.executemany(
        "insert into icd10_descendant (code, name, anchor_code) values (?,?,?)",
        descendants,
    )
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        "insert or replace into meta (key, value) values ('icd10_descendientes_at', ?)",
        (now,),
    )
    db.commit()

    total = db.execute("select count(*) from icd10_descendant").fetchone()[0]
    logger.info("=== RESULTADO ===")
    logger.info("icd10_descendant: %d filas", total)
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
