#!/usr/bin/env python3
"""Monografías: ficha técnica oficial de la AEMPS (CIMA) por composición, para `GET /monografia`.

## Qué es y de dónde sale

Para cada COMPOSICIÓN (conjunto de principios activos: `paracetamol`, `ibuprofeno+paracetamol`) que exista en el
DNMA uruguayo, una ficha técnica española de REFERENCIA de CIMA (https://cima.aemps.es/cima/rest), con sus
secciones 4.1–4.6 y 4.8 textuales (HTML saneado, texto sin tocar). CIMA es dato abierto de la AEMPS
(https://sede.aemps.gob.es/datos-abiertos/): reutilizable citando la fuente; el aviso legal no permite
transformar los contenidos, por eso no se resume ni se traduce nada. Ver README § Licencias.

## Universo

Los nombres de `dnma_substance_map.sustancia_dsc`. Por cada uno, todas las presentaciones comercializadas de CIMA
que lo contienen (`/medicamentos?practiv1=…&comerc=1`); la composición de cada presentación sale de `vtm.nombre`
("paracetamol + ibuprofeno"). Se conservan las composiciones cuyos componentes están TODOS en el DNMA: una
combinación que no existe en Uruguay no aporta.

## Referencia

Entre las presentaciones de una composición: con ficha técnica segmentada (`docs[tipo=1].secc`), preferir vía oral,
y a igualdad el menor número de registro (criterio estable entre corridas). De la referencia: `/medicamento` (ATC
de nivel 5 y su grupo de nivel 3) y `/docSegmentado/contenido/1` (todas las secciones en una llamada; exige
`Accept: application/json`, sin ese header CIMA no devuelve JSON — medido 2026-11-05).

## Corrida

    uv run python -m scripts.fetch_aemps_monografias [--limit N]

Throttle entre requests, reintentos con backoff; un error en una composición queda como `estado='error'` y no
corta la corrida. Idempotente. El runtime nunca llama a CIMA (AGENTS.md § ETL y runtime).
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone

import httpx

from app.services.monografia import agrupar_secciones, clave_composicion

logger = logging.getLogger("fetch_aemps_monografias")

DEFAULT_DB = "data/recetalia_interactions.db"
CIMA = "https://cima.aemps.es/cima/rest"
FUENTE = "Ficha técnica AEMPS (CIMA, cima.aemps.es)"

_SCHEMA = """
create table if not exists monografia (
    composicion        text primary key,
    principios_activos text not null,          -- json: nombres tal como los da la AEMPS (vtm)
    atc_codigo         text,
    atc_nombre         text,
    atc_grupo          text,                   -- nivel 3 del ATC: "acción terapéutica"
    nregistro          text,
    nombre_ref         text,
    url_ficha          text,
    fecha_ficha        text,
    estado             text not null check (estado in ('ok','sin_referencia','error')),
    detalle            text,
    fetched_at         text not null,
    source             text not null default 'aemps'
);
create table if not exists monografia_seccion (
    composicion text not null references monografia(composicion) on delete cascade,
    seccion     text not null,
    titulo      text not null,
    html        text not null,
    orden       integer not null,
    primary key (composicion, seccion)
);
"""


class CimaClient:
    """Cliente mínimo de CIMA con throttle y reintentos. Inyectable en los tests."""

    def __init__(self, pausa: float = 0.3, reintentos: int = 3, timeout: float = 30.0):
        self.pausa, self.reintentos = pausa, reintentos
        self.http = httpx.Client(base_url=CIMA, timeout=timeout,
                                 headers={"Accept": "application/json", "User-Agent": "Consilio-ETL"})

    def _get(self, path: str, params: dict):
        for intento in range(1, self.reintentos + 1):
            time.sleep(self.pausa)
            try:
                r = self.http.get(path, params=params)
                r.raise_for_status()
                return r.json() if r.content else None
            except (httpx.HTTPError, ValueError) as e:
                if intento == self.reintentos:
                    raise
                logger.warning("CIMA %s %s: %s (reintento %d)", path, params, e, intento)
                time.sleep(2 ** intento)

    def presentaciones(self, principio: str) -> list[dict]:
        out, pagina = [], 1
        while True:
            d = self._get("/medicamentos", {"practiv1": principio, "comerc": 1, "pagina": pagina}) or {}
            res = d.get("resultados") or []
            out += res
            if not res or len(out) >= (d.get("totalFilas") or 0):
                return out
            pagina += 1

    def medicamento(self, nregistro: str) -> dict:
        return self._get("/medicamento", {"nregistro": nregistro}) or {}

    def secciones(self, nregistro: str) -> list[dict]:
        return self._get("/docSegmentado/contenido/1", {"nregistro": nregistro}) or []


def componentes(vtm_nombre: str) -> list[str]:
    return [c.strip() for c in (vtm_nombre or "").split("+") if c.strip()]


def _ficha(p: dict) -> dict | None:
    return next((d for d in p.get("docs") or [] if d.get("tipo") == 1 and d.get("secc")), None)


def elegir_referencia(presentaciones: list[dict]) -> dict | None:
    candidatas = [p for p in presentaciones if p.get("comerc") and _ficha(p)]
    if not candidatas:
        return None

    def orden(p):
        oral = any("ORAL" in (v.get("nombre") or "").upper() for v in p.get("viasAdministracion") or [])
        nreg = str(p.get("nregistro") or "")
        return (0 if oral else 1, int(nreg) if nreg.isdigit() else 10**12, nreg)

    return min(candidatas, key=orden)


def composiciones(cima, nombres_dnma: list[str]) -> dict[str, dict]:
    """clave → {'principios': [...], 'presentaciones': [...]} para las composiciones 100 % DNMA."""
    universo = {clave_composicion([n]) for n in nombres_dnma} - {""}
    out: dict[str, dict] = {}
    vistos: set[str] = set()
    for nombre in sorted(set(nombres_dnma)):
        for p in cima.presentaciones(nombre):
            nreg = str(p.get("nregistro"))
            if nreg in vistos:
                continue
            vistos.add(nreg)
            comp = componentes((p.get("vtm") or {}).get("nombre"))
            if not comp or any(clave_composicion([c]) not in universo for c in comp):
                continue
            clave = clave_composicion(comp)
            g = out.setdefault(clave, {"principios": comp, "presentaciones": []})
            g["presentaciones"].append(p)
    return out


def _atc(med: dict) -> tuple[str | None, str | None, str | None]:
    atcs = med.get("atcs") or []
    n5 = max(atcs, key=lambda a: a.get("nivel") or 0, default=None)
    n3 = next((a for a in atcs if a.get("nivel") == 3), None)
    grupo = n3.get("nombre") if n3 else None
    if grupo and grupo.isupper():
        grupo = grupo[:1] + grupo[1:].lower()
    return (n5 or {}).get("codigo"), (n5 or {}).get("nombre"), grupo


def guardar(db: sqlite3.Connection, clave: str, principios: list[str], estado: str, *, ref: dict | None = None,
            med: dict | None = None, secciones: list[dict] | None = None, detalle: str | None = None) -> None:
    ahora = datetime.now(timezone.utc).isoformat()
    atc = _atc(med or {})
    ficha = _ficha(ref) if ref else None
    fecha = (datetime.fromtimestamp(ficha["fecha"] / 1000, tz=timezone.utc).date().isoformat()
             if ficha and ficha.get("fecha") else None)
    nreg = str(ref.get("nregistro")) if ref else None
    db.execute("delete from monografia_seccion where composicion = ?", (clave,))
    db.execute(
        """insert or replace into monografia (composicion, principios_activos, atc_codigo, atc_nombre, atc_grupo,
               nregistro, nombre_ref, url_ficha, fecha_ficha, estado, detalle, fetched_at)
           values (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (clave, json.dumps(principios, ensure_ascii=False), *atc, nreg, (ref or {}).get("nombre"),
         f"https://cima.aemps.es/cima/dochtml/ft/{nreg}/FichaTecnica.html" if nreg else None,
         fecha, estado, detalle, ahora))
    for i, s in enumerate(secciones or []):
        db.execute("insert into monografia_seccion (composicion, seccion, titulo, html, orden) values (?,?,?,?,?)",
                   (clave, s["seccion"], s["titulo"], s["html"], i))


def cargar(db: sqlite3.Connection, cima, limit: int | None = None) -> dict[str, int]:
    db.executescript(_SCHEMA)
    nombres = [r[0] for r in db.execute("select sustancia_dsc from dnma_substance_map")]
    comps = composiciones(cima, nombres)
    logger.info("Composiciones con todos sus componentes en el DNMA: %d", len(comps))
    cuenta = {"ok": 0, "sin_referencia": 0, "error": 0}
    for n, (clave, g) in enumerate(sorted(comps.items())):
        if limit is not None and n >= limit:
            break
        ref = elegir_referencia(g["presentaciones"])
        if ref is None:
            guardar(db, clave, g["principios"], "sin_referencia")
            cuenta["sin_referencia"] += 1
        else:
            try:
                nreg = str(ref["nregistro"])
                secciones = agrupar_secciones(cima.secciones(nreg))
                med = cima.medicamento(nreg)
                estado = "ok" if secciones else "sin_referencia"
                guardar(db, clave, g["principios"], estado, ref=ref, med=med, secciones=secciones,
                        detalle=None if secciones else "ficha sin secciones 4.x")
                cuenta[estado] += 1
            except Exception as e:  # una composición rota no corta la corrida
                guardar(db, clave, g["principios"], "error", ref=ref, detalle=str(e)[:300])
                cuenta["error"] += 1
        db.commit()
    ahora = datetime.now(timezone.utc).isoformat()
    db.execute("insert or replace into meta (key, value) values ('monografias_at', ?)", (ahora,))
    db.execute("insert or replace into meta (key, value) values ('monografias_fuente', ?)", (FUENTE,))
    db.commit()
    return cuenta


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--limit", type=int, default=None, help="sólo las primeras N composiciones (prueba)")
    args = p.parse_args()
    db = sqlite3.connect(args.db)
    cuenta = cargar(db, CimaClient(), args.limit)
    logger.info("=== RESULTADO === %s", cuenta)
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
