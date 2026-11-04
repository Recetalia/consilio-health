#!/usr/bin/env python3
"""Nombres en castellano de los códigos CIE-10, desde la CIE-10-ES oficial.

## El problema

El autocompletado de patologías mostraba los nombres de ICD-10-CM en inglés
(`E27.9 Disorder of adrenal gland, unspecified`). La regla del proyecto es que
el castellano salga de una fuente oficial, nunca de una traducción automática
(ver `docs/2026-09-25-castellano-y-colores.md`).

## La fuente

**CIE-10-ES Diagnósticos, 6ª edición (2026)**, Ministerio de Sanidad de España:
`Diagnosticos_Tabla_Referencia_CIE10ES_2026.xlsx`, hoja `ES2026 Completa +
Marcadores` (102.448 códigos, finales y no finales). Es la traducción española
oficial de ICD-10-CM —la misma clasificación que usa Consilio—, así que los
códigos coinciden uno a uno, incluidos los de 6-7 caracteres (`M10.311`) que la
CIE-10 de la OMS no tiene.

Descarga: https://www.sanidad.gob.es/estadEstudios/estadisticas/normalizacion/CIE10/2026/Diagnosticos_Tabla_Referencia_CIE10ES_2026.xlsx
Licencia: aviso legal de sanidad.gob.es — reutilizable, también con fines
comerciales, citando la fuente y la fecha de última actualización y sin
desnaturalizar el contenido (verificado 2026-11-04). Ver README § Licencias.

Cobertura medida (2026-11-04) contra la base de Consilio: 551/552 anclajes
`icd10cm` y 3.210/3.231 descendientes. Lo que falta son altas CMS FY2026 que la
edición española todavía no trae (`G35.A`, `C50.A0`…): quedan con el nombre en
inglés, nunca con uno inventado.

## Qué escribe

`name_es` y `name_es_norm` (minúsculas, sin tildes, para buscar sin depender de
cómo se tipee) en `condition` (filas `icd10%`) y en `icd10_descendant`. No toca
`name`, ni códigos, ni ningún vínculo con alertas: el nombre es sólo lo que se
muestra.

Los anclajes de tipo rango que son un capítulo entero (`G00-G99`) toman el
título del capítulo (`ENFERMEDADES DEL SISTEMA NERVIOSO (G00-G99)`). Capítulos y
bloques se pasan a minúsculas con inicial mayúscula y sin el rango repetido
(`Enfermedades del sistema nervioso`), porque el código ya va al lado.

## Orden

Correr DESPUÉS de `load_icd10_descendientes`: ese script borra y recarga
`icd10_descendant`, y con eso se lleva los nombres en castellano.

Requiere `openpyxl` sólo para el ETL: `uv run --with openpyxl python -m scripts.load_cie10es`.
"""
from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("load_cie10es")

DEFAULT_XLSX = Path("data/cie10es/Diagnosticos_Tabla_Referencia_CIE10ES_2026.xlsx")
DEFAULT_DB = "data/recetalia_interactions.db"
SHEET = "ES2026 Completa + Marcadores"
FUENTE = "CIE-10-ES Diagnósticos 6ª ed. 2026 (Ministerio de Sanidad de España)"

_RANGO_EN_TITULO = re.compile(r"\(([A-Z][0-9]{2}(?:-[A-Z][0-9]{2})?)\)\s*$")


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes ni diéresis, espacios colapsados. Misma regla en el ETL y en la búsqueda."""
    sin_marcas = "".join(c for c in unicodedata.normalize("NFD", texto or "")
                         if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sin_marcas.lower()).strip()


def titulo_capitulo(descripcion: str) -> str:
    """`ENFERMEDADES DEL SISTEMA NERVIOSO (G00-G99)` → `Enfermedades del sistema nervioso`."""
    base = _RANGO_EN_TITULO.sub("", descripcion).strip()
    return base[:1].upper() + base[1:].lower()


def nombres_desde_filas(filas) -> dict[str, str]:
    """Código → descripción. Las filas de capítulo (`Cap.06`) aportan su rango (`G00-G99`)."""
    nombres: dict[str, str] = {}
    for codigo, descripcion in filas:
        if not codigo or not descripcion:
            continue
        codigo = str(codigo).strip().upper()
        descripcion = str(descripcion).strip()
        if codigo.startswith("CAP."):
            m = _RANGO_EN_TITULO.search(descripcion)
            if m:
                nombres.setdefault(m.group(1), titulo_capitulo(descripcion))
            continue
        # Los bloques (`E00-E07`) vienen en mayúsculas y repiten el rango: mismo formato que los capítulos.
        nombres[codigo] = titulo_capitulo(descripcion) if "-" in codigo else descripcion
    return nombres


def leer_xlsx(path: Path) -> dict[str, str]:
    import openpyxl  # sólo el ETL lo necesita
    wb = openpyxl.load_workbook(path, read_only=True)
    filas = ((r[0], r[1]) for i, r in enumerate(wb[SHEET].iter_rows(values_only=True)) if i > 0)
    return nombres_desde_filas(filas)


def _asegurar_columnas(db: sqlite3.Connection, tabla: str) -> None:
    existentes = {r[1] for r in db.execute(f"pragma table_info({tabla})")}
    for col in ("name_es", "name_es_norm"):
        if col not in existentes:
            db.execute(f"alter table {tabla} add column {col} text")


def aplicar(db: sqlite3.Connection, nombres: dict[str, str]) -> dict[str, tuple[int, int]]:
    """Escribe los nombres. Devuelve, por tabla, (filas con nombre en castellano, filas totales)."""
    resultado = {}
    for tabla, where in (("condition", "code_system like 'icd10%'"), ("icd10_descendant", "1=1")):
        _asegurar_columnas(db, tabla)
        codigos = [r[0] for r in db.execute(f"select code from {tabla} where {where}")]
        con = 0
        for codigo in codigos:
            es = nombres.get(codigo.strip().upper())
            db.execute(f"update {tabla} set name_es = ?, name_es_norm = ? where code = ? and {where}",
                       (es, normalizar(es) if es else None, codigo))
            con += es is not None
        resultado[tabla] = (con, len(codigos))
    return resultado


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--xlsx", default=str(DEFAULT_XLSX), type=Path)
    args = p.parse_args()

    if not args.xlsx.exists():
        logger.error("No existe la planilla CIE-10-ES: %s (bajarla de la URL del docstring)", args.xlsx)
        return 1

    nombres = leer_xlsx(args.xlsx)
    logger.info("Códigos CIE-10-ES leídos: %d", len(nombres))

    db = sqlite3.connect(args.db)
    try:
        db.execute("select 1 from icd10_descendant limit 1")
    except sqlite3.OperationalError:
        logger.error("Falta icd10_descendant: correr antes scripts.load_icd10_descendientes")
        return 1
    resultado = aplicar(db, nombres)
    db.execute("insert or replace into meta (key, value) values ('cie10es_loaded_at', ?)",
               (datetime.now(timezone.utc).isoformat(),))
    db.execute("insert or replace into meta (key, value) values ('cie10es_fuente', ?)", (FUENTE,))
    db.commit()
    for tabla, (con, total) in resultado.items():
        logger.info("%s: %d/%d con nombre en castellano", tabla, con, total)
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
