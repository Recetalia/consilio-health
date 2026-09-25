"""Duplicidad terapéutica: misma sustancia, o misma clase por encima del cupo.

Dos capas en consulta (la tercera, cupos y excepciones, es dato curado):

1. **Sustancia**: el mismo fármaco en dos productos distintos. Cupo 0, grave.
   Cubre el paracetamol dentro de un combinado, que ningún prefijo ATC ve.
2. **Clase**: más productos de una clase que su cupo (1 por defecto). Las
   clases salen de la AEMPS (`scripts/cross_aemps_duplicidad.py`).

Sustancias del MISMO producto nunca se comparan entre sí: el médico no puede
separarlas. Y lo que no se alerta por un cupo o una excepción se devuelve
aparte con el motivo: que el médico vea que se evaluó, no un silencio.

El número que ordena todo: el 80 % de las alertas de duplicidad se ignoran y
un tercio eran combinaciones intencionales. El módulo vale lo que valga su tasa
de falsos positivos.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

CUPOS_PATH = os.environ.get("CONSILIO_DUPLICIDAD_CUPOS", os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "duplicidad_cupos.json"))

AVISO_SIN_CLASES = ("La base no tiene clases de duplicidad cargadas: sólo se "
                    "evaluó la misma sustancia en dos productos.")


@dataclass(frozen=True)
class Producto:
    id: str
    sustancias: tuple[str, ...]
    drug_ids: tuple[int | None, ...]   # mismo orden que `sustancias`; None = no resuelta
    route: str | None = None


@lru_cache(maxsize=1)
def cargar_cupos(path: str = CUPOS_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {"clases": data.get("clases", {}), "excepciones": data.get("excepciones", [])}


def evaluar(
    productos: list[Producto],
    clases_por_drug: dict[int, list[tuple[str, str]]] | None,
    cupos: dict[str, Any],
    canonicos: dict[int, str],
) -> dict[str, Any]:
    out: dict[str, Any] = {"duplicities": [], "duplicities_suppressed": [],
                           "duplicity_not_evaluated": [], "duplicity_warnings": []}

    no_resueltas: list[str] = []
    # drug_id -> {product_id: nombre con que llegó}
    por_droga: dict[int, dict[str, str]] = {}
    for p in productos:
        for nombre, did in zip(p.sustancias, p.drug_ids):
            if did is None:
                if nombre not in no_resueltas:
                    no_resueltas.append(nombre)
                continue
            por_droga.setdefault(did, {}).setdefault(p.id, nombre)
    out["duplicity_not_evaluated"] = no_resueltas

    # --- capa 1: misma sustancia -------------------------------------------
    for did, prods in por_droga.items():
        if len(prods) >= 2:
            out["duplicities"].append(dict(
                layer="substance", class_id=None, class_desc=None,
                products=list(prods), substances=sorted(set(prods.values())),
                count=len(prods), cupo=0, severity="major", source="consilio",
                rule="misma-sustancia"))

    if clases_por_drug is None:
        out["duplicity_warnings"].append(AVISO_SIN_CLASES)
        return out

    # --- capa 2: clase -------------------------------------------------------
    # class_id -> (desc, {product_id: {drug_id: nombre}})
    por_clase: dict[str, tuple[str, dict[str, dict[int, str]]]] = {}
    for did, prods in por_droga.items():
        for cid, desc in clases_por_drug.get(did, []):
            _, miembros = por_clase.setdefault(cid, (desc, {}))
            for pid, nombre in prods.items():
                miembros.setdefault(pid, {})[did] = nombre

    for cid, (desc, miembros) in sorted(por_clase.items()):
        if len(miembros) < 2:
            continue
        drogas = {d for m in miembros.values() for d in m}
        if len(drogas) == 1:
            continue  # es la misma sustancia: ya la dijo la capa 1
        cfg = cupos["clases"].get(cid, {})
        cupo = int(cfg.get("cupo", 1))
        alerta = dict(
            layer="class", class_id=cid, class_desc=desc, products=list(miembros),
            substances=sorted({n for m in miembros.values() for n in m.values()}),
            count=len(miembros), cupo=cupo, severity="moderate", source="aemps", rule=cid)

        if cfg.get("desactivada") or len(miembros) <= cupo:
            motivo = cfg
        else:
            motivo = _excepcion(cid, miembros, cupos["excepciones"], canonicos)

        if motivo is None:
            out["duplicities"].append(alerta)
        else:
            out["duplicities_suppressed"].append({
                **alerta, "motivo": motivo.get("motivo"),
                "referencia": motivo.get("referencia"),
                "validado": bool(motivo.get("validado", False))})
    return out


def _excepcion(cid: str, miembros: dict[str, dict[int, str]],
               excepciones: list[dict], canonicos: dict[int, str]) -> dict | None:
    """Suprime sólo si TODOS los productos caen en algún grupo y ningún grupo
    tiene dos. Un producto fuera de los grupos cuenta como siempre."""
    for exc in excepciones:
        if exc.get("clase") != cid:
            continue
        grupo_de = {nombre: i for i, g in enumerate(exc.get("grupos", [])) for nombre in g}
        usados: set[int] = set()
        ok = True
        for m in miembros.values():
            gs = {grupo_de.get(canonicos.get(d, "")) for d in m}
            if None in gs or len(gs) != 1:
                ok = False
                break
            g = gs.pop()
            if g in usados:
                ok = False
                break
            usados.add(g)
        if ok:
            return exc
    return None
