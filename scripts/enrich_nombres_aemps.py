#!/usr/bin/env python3
"""Nombres oficiales en castellano desde la AEMPS.

## Por qué

Medido 2026-09-25: de los 1.939 fármacos de la base, 725 ya tenían nombre en
castellano (65 por alias curado a mano + 716 por el mapa del DNMA); 1.214 no
tenían ninguno. Cruzando esos 1.214 por esqueleto INN contra el diccionario
ATC de la AEMPS (sólo los códigos de nivel 5, que nombran una molécula y no
una clase) 779 consiguen nombre oficial. Este script suma esa fuente más el
`DICCIONARIO_PRINCIPIOS_ACTIVOS.xml`, que trae principios activos sueltos
(`RANITIDINA`) que el diccionario ATC no siempre cubre.

No hay traducción automática: sólo se carga lo que viene firmado por un
regulador. Ver `docs/2026-09-25-castellano-y-colores.md`.

## Cómo empareja

El nombre de la AEMPS se compara contra el canónico por esqueleto INN
(`app.nlp.nombres.skeleton`), igual que hace `cross_aemps_interactions.py`
para las reglas de interacción. El match se descarta si:

* el nombre AEMPS es de combinación (`es_combinacion`);
* el nombre AEMPS tiene algún token de <=2 caracteres una vez normalizado
  (mismo criterio que `recetalia_db._token_corto`: sin eso 'vitamina a' y
  'vitamina e' colisionan);
* el match no es único en los dos sentidos: o el esqueleto de la AEMPS
  apunta a más de un canónico sin vía (homónimos genuinos, como
  `Vitamin A`/`Vitamin E`), o el esqueleto del canónico recibe más de un
  nombre AEMPS distinto. Excepción: si dos nombres AEMPS normalizan igual
  (la sal se descarta, `RANITIDINA` == `RANITIDINA HIDROCLORURO`), cuentan
  como el mismo nombre, no como ambigüedad.

Un canónico con vía entre paréntesis (`Diclofenac (topical)`) empareja por el
esqueleto de la parte sin vía (`skeleton()` ya descarta el paréntesis) y
recibe `"<nombre> (<vía>)"` traducida por un diccionario cerrado. Si la vía no
está en el diccionario, esa variante se queda sin nombre: no se inventa.

## Qué no pisa

No inserta si el fármaco ya tiene un alias `es` curado a mano (`source`
distinto de 'aemps'), ni si ya existe ese `alias_norm` para ese fármaco.

Reseedable: `delete from drug_alias where source='aemps' and lang='es'` antes
de insertar. Deja fecha en `meta.aemps_nombres_es_at`.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app.clients.recetalia_db import normalize  # noqa: E402
from app.nlp.nombres import skeleton  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cross_aemps_interactions import cargar_atc_names, es_combinacion  # noqa: E402

logger = logging.getLogger("enrich_nombres_aemps")

_PRINCIPIO_ACTIVO_RE = re.compile(r"<principioactivo>([^<]*)</principioactivo>")

# Diccionario cerrado: si la vía no está acá, la variante no recibe nombre.
VIAS_ES = {
    "topical": "tópico", "ophthalmic": "oftálmico", "otic": "ótico",
    "nasal": "nasal", "oral": "oral", "vaginal": "vaginal", "rectal": "rectal",
    "inhalation": "inhalado", "injection": "inyectable", "liposomal": "liposomal",
    "transdermal": "transdérmico", "systemic": "sistémico",
}


def token_corto(nombre: str) -> bool:
    """Mismo criterio que `recetalia_db._token_corto`, sobre el nombre AEMPS."""
    return any(len(tok) <= 2 for tok in normalize(nombre).split())


def _capitalizar_oracion(s: str) -> str:
    """Primera letra mayúscula, resto minúscula: los principios activos de la
    AEMPS vienen todos en mayúsculas (`RANITIDINA`)."""
    s = s.strip().lower()
    return s[0].upper() + s[1:] if s else s


def cargar_principios_activos(path: str) -> list[str]:
    xml = open(path, encoding="utf-8-sig").read()
    return [_capitalizar_oracion(n) for n in _PRINCIPIO_ACTIVO_RE.findall(xml) if n.strip()]


def nombres_candidatos(dicc_atc: str, dicc_principios: str) -> list[str]:
    """Nombres crudos de la AEMPS: los N5 (7 caracteres) del diccionario ATC
    más los principios activos, sin filtrar todavía (lo hace `asignar_nombres`)."""
    atc_names = cargar_atc_names(dicc_atc)
    n5 = [nombre for codigo, nombre in atc_names.items() if len(codigo) == 7 and nombre]
    principios = cargar_principios_activos(dicc_principios)
    return n5 + principios


def indice_canonico(canonicals: dict[int, str]) -> dict[str, list[tuple[int, str | None]]]:
    """Esqueleto de la parte sin vía del canónico -> [(drug_id, vía)].

    `skeleton()` ya descarta el contenido entre paréntesis, así que
    `Diclofenac` y `Diclofenac (topical)` caen en la misma clave y se
    distinguen por `vía` (`None` para el que no tiene paréntesis).
    """
    idx: dict[str, list[tuple[int, str | None]]] = defaultdict(list)
    for drug_id, canonical in canonicals.items():
        m = re.search(r"\(([^)]*)\)", canonical or "")
        via = m.group(1).strip().lower() if m else None
        s = skeleton(canonical or "")
        if s:
            idx[s].append((drug_id, via))
    return idx


def asignar_nombres(
    nombres: list[str], indice: dict[str, list[tuple[int, str | None]]]
) -> dict[int, str]:
    """`drug_id` -> nombre en castellano a insertar.

    Aplica los tres descartes (combinación, token corto, ambigüedad en los
    dos sentidos) y arma la variante con vía cuando corresponde.
    """
    validos = [n for n in nombres if n and not es_combinacion(n) and not token_corto(n)]

    # Por esqueleto, los nombres AEMPS distintos (por normalización) que
    # caen ahí. Si hay más de uno, el esqueleto de canónico no tiene un
    # nombre único que recibir (segundo sentido de la unicidad).
    por_skel: dict[str, dict[str, str]] = defaultdict(dict)
    for nombre in validos:
        s = skeleton(nombre)
        if not s:
            continue
        por_skel[s].setdefault(normalize(nombre), nombre)

    asignaciones: dict[int, str] = {}
    for s, por_norm in por_skel.items():
        candidatos = indice.get(s)
        if not candidatos or len(por_norm) != 1:
            continue
        nombre = next(iter(por_norm.values()))

        # Primer sentido de la unicidad: si más de un canónico SIN vía
        # comparte este esqueleto, es un homónimo genuino (Vitamin A /
        # Vitamin E) y no hay a quién asignárselo.
        sin_via = [d for d, via in candidatos if via is None]
        if len(sin_via) == 1:
            asignaciones[sin_via[0]] = nombre

        for drug_id, via in candidatos:
            if via is None:
                continue
            via_es = VIAS_ES.get(via)
            if via_es:
                asignaciones[drug_id] = f"{nombre} ({via_es})"

    return asignaciones


def migrar_source(db: sqlite3.Connection) -> None:
    """Agregar 'aemps' al CHECK de `drug_alias.source`.

    SQLite no sabe alterar un CHECK: hay que reconstruir la tabla. Mismo
    patrón que `cross_aemps_interactions.migrar_source`, para `drug_alias` en
    vez de `interaction`. Se hace una sola vez y es idempotente.
    """
    ddl = db.execute(
        "select sql from sqlite_master where type='table' and name='drug_alias'"
    ).fetchone()[0]
    if "'aemps'" in ddl:
        return
    logger.info("Migrando el CHECK de drug_alias.source para admitir 'aemps'")
    nuevo = ddl.replace(
        "'ddinter','rxnorm','dnma','manual'", "'ddinter','rxnorm','dnma','manual','aemps'")
    if nuevo == ddl:
        raise SystemExit("no se pudo reescribir el CHECK; revisar el DDL a mano")
    db.executescript(f"""
        pragma foreign_keys=off;
        begin;
        {nuevo.replace('CREATE TABLE drug_alias', 'CREATE TABLE drug_alias_new', 1)};
        insert into drug_alias_new select * from drug_alias;
        drop table drug_alias;
        alter table drug_alias_new rename to drug_alias;
        create index if not exists idx_alias_norm on drug_alias(alias_norm);
        commit;
        pragma foreign_keys=on;
    """)


def _con_nombre_es(db: sqlite3.Connection) -> set[int]:
    """`drug_id` que hoy ya muestran algo en castellano: alias `es` (de
    cualquier fuente) o mapa del DNMA. Mismo criterio que `search_drugs`."""
    con_alias = {r[0] for r in db.execute(
        "select distinct drug_id from drug_alias where lang='es'")}
    con_dnma = {r[0] for r in db.execute(
        "select distinct drug_id from dnma_substance_map where drug_id is not null")}
    return con_alias | con_dnma


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default="data/recetalia_interactions.db")
    p.add_argument("--dicc-atc", default="data/aemps/DICCIONARIO_ATC.xml")
    p.add_argument("--dicc-principios", default="data/aemps/DICCIONARIO_PRINCIPIOS_ACTIVOS.xml")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    for f in (args.db, args.dicc_atc, args.dicc_principios):
        if not os.path.exists(f):
            raise SystemExit(f"falta {f}")

    db = sqlite3.connect(args.db)
    canonicals = {did: c for did, c in db.execute("select drug_id, canonical from drug")}
    indice = indice_canonico(canonicals)
    nombres = nombres_candidatos(args.dicc_atc, args.dicc_principios)
    logger.info("Nombres candidatos de la AEMPS: %d", len(nombres))

    asignaciones = asignar_nombres(nombres, indice)
    logger.info("Esqueletos con match: %d fármacos", len(asignaciones))

    antes = _con_nombre_es(db)
    curados = {r[0] for r in db.execute(
        "select distinct drug_id from drug_alias where lang='es' and source<>'aemps'")}
    # Sin las filas propias: se borran abajo antes de insertar. Contarlas como
    # "existentes" hacía que una segunda corrida borrara las 967 y escribiera
    # sólo las nuevas (medido 2026-09-25: 967 -> 14).
    existentes = {(r[0], r[1]) for r in db.execute(
        "select drug_id, alias_norm from drug_alias "
        "where not (source='aemps' and lang='es')")}

    filas: list[tuple[int, str, str]] = []
    for drug_id, nombre in asignaciones.items():
        if drug_id in curados:
            continue
        an = normalize(nombre)
        if (drug_id, an) in existentes:
            continue
        filas.append((drug_id, nombre, an))

    total = len(canonicals)
    ganan = {did for did, _, _ in filas} - antes
    despues = antes | ganan
    sin_nombre_despues = total - len(despues)

    logger.info("=== %d fármacos ganan nombre en castellano (%d -> %d con nombre) ===",
                len(ganan), len(antes), len(despues))
    logger.info("Siguen sin nombre en castellano: %d de %d", sin_nombre_despues, total)

    ejemplos = sorted(
        ((canonicals[did], nombre) for did, nombre, _ in filas if did in ganan),
        key=lambda t: t[0],
    )[:15]
    for canonical, nombre in ejemplos:
        logger.info("   %-40s -> %s", canonical, nombre)

    if args.dry_run:
        logger.info("dry-run: no se escribió nada")
        return 0

    migrar_source(db)
    borradas = db.execute("delete from drug_alias where source='aemps' and lang='es'").rowcount
    if borradas:
        logger.info("Reemplazando %d filas 'aemps' previas", borradas)
    db.executemany(
        "insert or ignore into drug_alias (drug_id, alias, alias_norm, lang, source) "
        "values (?,?,?,'es','aemps')",
        filas,
    )
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.execute(
        "insert or replace into meta (key, value) values ('aemps_nombres_es_at', ?)", (ahora,))
    db.commit()
    logger.info("Escritas %d filas.", len(filas))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
