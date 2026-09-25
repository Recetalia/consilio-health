#!/usr/bin/env python3
"""Cargar las clases de duplicidad terapéutica de la AEMPS, cruzadas por ATC.

`aemps_extra.json` trae 1.593 reglas `{atc_a, atc_b, desc}`: "un producto de
`atc_b` duplica a `atc_a`". No traen cupo ni recomendación. Esto las convierte
en membresías `drug_class(drug_id, class_id)`; el cupo y las excepciones se
aplican en consulta (`app/services/duplicity_checker.py`).

## Clase = ATC4 del ancla, no el `desc`

Medido 2026-09-24: agrupar por `desc` junta enalapril y amlodipino bajo
"INHIBIDORES DE LA ECA Y BLOQUEANTES DE CANALES DE CALCIO", porque ese grupo
está anclado en un ATC de combinado. IECA + antagonista del calcio alertaría:
es el falso positivo canónico de este módulo. Con el ATC4 del ancla, diazepam
(N05BA01) y lorazepam (N05BA02) caen en N05BA, y enalapril, amlodipino e
hidroclorotiazida en tres clases distintas.

## Los combinados se descartan

Una regla con un código de combinado de cualquier lado habla de ingredientes:
eso lo cubre la capa de sustancia (el mismo principio activo en dos productos).
Y `drug.atc` trae los ATC de los combinados que contienen al fármaco —RxClass
se los asigna a cada ingrediente—: sin filtrarlos, la hidroclorotiazida entra a
los ARA II por `C09DX`. Ver `es_codigo_combinado` para cómo se decide.

## `rol`: ancla vs. miembro

Una regla `{atc_a, atc_b, desc}` significa "un producto de `atc_b` duplica a
`atc_a`", **no** "`atc_a` y `atc_b` son intercambiables entre sí". Los
fármacos que resuelven de `atc_a` son el `rol='ancla'` de la clase; los que
resuelven de `atc_b` son `rol='miembro'`. Dos miembros entre sí NO son
duplicidad en esa clase (lo serán en la suya si la AEMPS la define aparte).

Medido 2026-09-24 con la membresía plana (sin rol): prednisona y
dexametasona compartían H02AA ("Mineralocorticoides") **y** H02AB
("Glucocorticoides") —alertaban dos veces—, y alendronato/risedronato
compartían G03XC, H05AA, H05BA y M05BA —alertaban cuatro veces—. Las cuatro
son clases donde ambos fármacos entran como `atc_b` de reglas ancladas en
otro corticoide o bifosfonato: son miembros, no anclas, y la comparación
correcta (`prednisona`+`dexametasona` ancla en H02AB;
`alendronato`+`risedronato` ancla en M05BA) sigue alertando.

Si un fármaco es ancla y miembro de la misma clase (por reglas distintas),
gana `'ancla'`.

Reseedable: borra sus propias filas antes de escribir. La tabla ya existía
sin `rol`: si al migrar no está la columna, se recrea entera (`drop table` +
`create`) — es sólo nuestra (`source='aemps'`) y se re-siembra completa, así
que no hay dato que preservar. La migración, el borrado, la inserción y el
sello en `meta` corren dentro de una única transacción explícita: si algo
falla a mitad de camino no queda la tabla a medio recrear.
"""
from __future__ import annotations

import argparse
import collections
import json
import logging
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone

from cross_aemps_interactions import Resolver, cargar_atc_names, es_combinacion

logger = logging.getLogger("cross_duplicidad")

# Statements sueltos, no `executescript`: `executescript` hace un COMMIT
# implícito antes de correr, lo que rompería la transacción explícita que
# envuelve migración + borrado + inserción en `main`.
DDL_STATEMENTS = (
    """create table if not exists drug_class (
        drug_id    integer not null references drug(drug_id),
        class_id   text    not null,      -- ATC4 del ancla (o N3 si el ancla es N3)
        class_desc text    not null,
        source     text    not null,
        note       text,
        rol        text    not null,      -- 'ancla' (de atc_a) | 'miembro' (de atc_b); empate gana 'ancla'
        primary key (drug_id, class_id, source)
    )""",
    "create index if not exists idx_dc_drug on drug_class(drug_id)",
)


def migrar_ddl(db: sqlite3.Connection) -> None:
    """`rol` es columna nueva: si la tabla existe sin ella, se recrea entera."""
    cols = {r[1] for r in db.execute("pragma table_info(drug_class)")}
    if cols and "rol" not in cols:
        logger.info("drug_class sin columna 'rol': recreando la tabla")
        db.execute("drop table drug_class")
    for stmt in DDL_STATEMENTS:
        db.execute(stmt)


# `es_combinacion` incluye `inhibidores de` porque en nombres de MOLÉCULA marca
# "amoxicilina e inhibidores de la betalactamasa". En nombres de CLASE es falso:
# "Inhibidores de la bomba de protones". Medido: sobre 629 códigos N3/N4, la
# función sola marca 197, casi todos monofármacos.
_COMBINACION_CLASE = re.compile(
    r"\b(y|e|con)\b|combinacion|combinaciones|combinad|asociad|dosis fijas|secuenciales",
    re.IGNORECASE)

# Pasan los dos criterios y no son combinados. Medido 2026-09-24.
_NO_COMBINADO = {"N04BA", "B03BB", "M03BB"}


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def clase_de(atc_ancla: str) -> str:
    return atc_ancla[:5]


def es_codigo_combinado(code: str, nombres: dict[str, str]) -> bool:
    """N5: el nombre de la molécula dice combinación.

    N3/N4: el nombre dice combinación **y** la mayoría de sus N5 hijos lo son.
    Ninguno de los dos alcanza solo: "Anilidas" (N02BE) tiene casi todos los
    hijos combinados —el paracetamol en todas sus asociaciones— y es la clase
    del paracetamol; "Inhibidores de la ECA y diuréticos" lo dice el nombre y
    lo confirman los hijos.

    Pura y sin caché a propósito: la usan los tests directo, sin `main`.
    Para las ~629 llamadas N3/N4 repetidas sobre la base real, `main` la usa
    una vez por código a través de `codigos_combinados_n3n4` y reusa el
    resultado como `set`, en vez de cachear acá por identidad del dict (con
    `id()`, que Python puede reciclar entre objetos distintos y que no se
    invalida si el dict cambia — bug real, no hipotético).
    """
    if len(code) >= 7:
        return es_combinacion(nombres.get(code, ""))
    if code in _NO_COMBINADO:
        return False
    if not _COMBINACION_CLASE.search(_ascii(nombres.get(code, ""))):
        return False
    hijos = [n for c, n in nombres.items() if len(c) >= 7 and c.startswith(code)]
    return bool(hijos) and sum(es_combinacion(h) for h in hijos) / len(hijos) >= 0.5


def codigos_combinados_n3n4(nombres: dict[str, str]) -> set[str]:
    """Precalcula, una sola vez, qué códigos N3/N4 del diccionario son combinados.

    `es_codigo_combinado` recorre los ~6.025 N5 por cada código N3/N4: barato
    una vez, caro si se repite miles de veces sobre el mismo código a través
    de las reglas y de `drug.atc`. Se llama acá una vez por código (~629 en la
    base real) y el resultado se reusa como `set` durante toda la corrida.
    """
    return {c for c in nombres if len(c) < 7 and es_codigo_combinado(c, nombres)}


def es_combinado(code: str, nombres: dict[str, str], combinados_n3n4: set[str]) -> bool:
    """`es_codigo_combinado` con el N3/N4 ya resuelto: N5 se decide al vuelo
    (una regex sobre un string), N3/N4 sale del `set` precalculado."""
    if len(code) >= 7:
        return es_combinacion(nombres.get(code, ""))
    return code in combinados_n3n4


def quitar_combinados(res: Resolver, nombres: dict[str, str], combinados_n3n4: set[str]) -> None:
    """La expansión por prefijo no puede entrar por un ATC de combinado."""
    por_clase: dict[str, set[int]] = collections.defaultdict(set)
    for did, atc in res.drug_atc.items():
        for p in (x.strip() for x in atc.split(",")):
            if p and not es_combinado(p, nombres, combinados_n3n4):
                por_clase[p].add(did)
    res.por_clase = por_clase


def agregar_membresia(
    filas: dict[tuple[int, str], tuple],
    drug_id: int, class_id: str, class_desc: str, modo: str, code: str, rol: str,
) -> None:
    """Agrega una membresía a `filas`, respetando el desempate de rol.

    Un fármaco puede resolver como ancla de una regla y como miembro de otra
    en la misma clase; `'ancla'` nunca se pisa, sea cual sea el orden en que
    se procesen las reglas.
    """
    key = (drug_id, class_id)
    prev = filas.get(key)
    if prev is None or prev[5] != "ancla":
        filas[key] = (drug_id, class_id, class_desc, "aemps", f"match {modo} · {code}", rol)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="data/recetalia_interactions.db")
    p.add_argument("--reglas", default="data/aemps/aemps_extra.json")
    p.add_argument("--dicc-atc", default="data/aemps/DICCIONARIO_ATC.xml")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    for f in (args.db, args.reglas, args.dicc_atc):
        if not os.path.exists(f):
            raise SystemExit(f"falta {f}")

    # `isolation_level=None` = autocommit real: el módulo `sqlite3` no abre ni
    # cierra transacciones por su cuenta (y `executescript` ya no puede
    # colarnos un COMMIT implícito). El `BEGIN`/`COMMIT` de la escritura son
    # explícitos, más abajo.
    db = sqlite3.connect(args.db, isolation_level=None)
    nombres = cargar_atc_names(args.dicc_atc)
    combinados_n3n4 = codigos_combinados_n3n4(nombres)
    res = Resolver(db, nombres)
    quitar_combinados(res, nombres, combinados_n3n4)
    reglas = json.load(open(args.reglas, encoding="utf-8"))["duplicidades"]

    filas: dict[tuple[int, str], tuple] = {}
    modos: collections.Counter = collections.Counter()
    descartadas = 0
    for r in reglas:
        a, b = r["atc_a"].strip(), r["atc_b"].strip()
        if es_combinado(a, nombres, combinados_n3n4) or es_combinado(b, nombres, combinados_n3n4):
            descartadas += 1
            continue
        cid = clase_de(a)
        desc = nombres.get(cid) or r["desc"].strip()
        for code, rol in ((a, "ancla"), (b, "miembro")):
            ids, modo = res.resolver(code)
            modos[modo] += 1
            for did in ids:
                agregar_membresia(filas, did, cid, desc, modo, code, rol)

    por_clase = collections.Counter(cid for _, cid in filas)
    anclas = sum(1 for v in filas.values() if v[5] == "ancla")
    logger.info("=== %d membresías · %d fármacos · %d clases (%d con ≥2 miembros) ===",
                len(filas), len({d for d, _ in filas}), len(por_clase),
                sum(1 for n in por_clase.values() if n >= 2))
    logger.info("Por rol: %d ancla · %d miembro", anclas, len(filas) - anclas)
    logger.info("Reglas descartadas por combinado: %d de %d", descartadas, len(reglas))
    logger.info("Resolución de códigos: %s", dict(modos.most_common()))

    if args.dry_run:
        logger.info("dry-run: no se escribió nada")
        return

    # Migración + borrado + inserción + sello en `meta`, atómicos: si algo
    # falla a mitad de camino (p. ej. el `drop table` corrió pero el insert
    # no), el `ROLLBACK` deshace todo, no deja la tabla a medio recrear.
    db.execute("begin")
    try:
        migrar_ddl(db)
        borradas = db.execute("delete from drug_class where source='aemps'").rowcount
        if borradas:
            logger.info("Reemplazando %d filas previas", borradas)
        db.executemany(
            "insert into drug_class (drug_id, class_id, class_desc, source, note, rol) "
            "values (?,?,?,?,?,?)", list(filas.values()))
        db.execute("insert or replace into meta (key, value) values ('aemps_duplicidad_at', ?)",
                   (datetime.now(timezone.utc).isoformat(timespec="seconds"),))
    except Exception:
        db.execute("rollback")
        raise
    db.execute("commit")
    logger.info("Escritas %d filas", len(filas))


if __name__ == "__main__":
    main()
