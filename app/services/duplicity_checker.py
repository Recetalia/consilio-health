"""Duplicidad terapéutica: misma sustancia, o misma clase por encima del cupo.

Dos capas en consulta (la tercera, cupos y excepciones, es dato curado):

1. **Sustancia**: el mismo fármaco en dos productos distintos. Cupo 0, grave.
   Cubre el paracetamol dentro de un combinado, que ningún prefijo ATC ve.
2. **Clase**: más productos de una clase que su cupo (1 por defecto). Las
   clases salen de la AEMPS (`scripts/cross_aemps_duplicidad.py`), cada
   fármaco con un rol 'ancla' o 'miembro' dentro de la clase.

Una regla AEMPS significa "un producto de atc_b duplica a atc_a": los
fármacos de atc_b son MIEMBROS de la clase del ancla, no anclas en sí. Con
membresía plana (sin este rol) medimos falsos positivos reales: prednisona +
dexametasona alertaban también bajo H02AA "Mineralocorticoides" (ninguno de
los dos es el ancla de esa clase, ambos llegan ahí como miembro de la regla
de otro fármaco), y alendronato + risedronato alertaban 4 veces (G03XC,
H05AA, H05BA, M05BA) por ser miembros de las cuatro. Por eso una clase sólo
alerta si al menos uno de sus productos aporta un fármaco con rol 'ancla' en
esa clase, y si dos o más clases alertarían sobre el mismo conjunto exacto de
productos se emite una sola (la de menor `class_id`), listando el resto en
`other_classes`.

Sustancias del MISMO producto nunca se comparan entre sí: el médico no puede
separarlas. Y lo que no se alerta por un cupo o una excepción se devuelve
aparte con el motivo: que el médico vea que se evaluó, no un silencio.

El número que ordena todo: el 80 % de las alertas de duplicidad se ignoran y
un tercio eran combinaciones intencionales. El módulo vale lo que valga su tasa
de falsos positivos.
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

DEFAULT_CUPOS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "duplicidad_cupos.json")

AVISO_SIN_CLASES = ("La base no tiene clases de duplicidad cargadas: sólo se "
                    "evaluó la misma sustancia en dos productos.")


@dataclass(frozen=True)
class Producto:
    id: str
    sustancias: tuple[str, ...]
    drug_ids: tuple[int | None, ...]   # mismo orden que `sustancias`; None = no resuelta
    route: str | None = None


@lru_cache(maxsize=None)
def _leer_cupos(path: str) -> dict[str, Any]:
    """Lectura de disco, cacheada por ruta. `cargar_cupos` devuelve una copia
    de este resultado para que nadie mute el cache compartido."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {"clases": data.get("clases", {}), "excepciones": data.get("excepciones", [])}


def cargar_cupos(path: str | None = None) -> dict[str, Any]:
    # la ruta se resuelve en cada llamada (no al importar el módulo) para que
    # `CONSILIO_DUPLICIDAD_CUPOS` pueda cambiar entre tests o entre requests.
    if path is None:
        path = os.environ.get("CONSILIO_DUPLICIDAD_CUPOS", DEFAULT_CUPOS_PATH)
    return copy.deepcopy(_leer_cupos(path))


def evaluar(
    productos: list[Producto],
    clases_por_drug: dict[int, list[tuple[str, str, str]]] | None,
    cupos: dict[str, Any],
    canonicos: dict[int, str],
) -> dict[str, Any]:
    """`clases_por_drug[drug_id]` es una lista de `(class_id, class_desc, rol)`,
    con `rol` en `{"ancla", "miembro"}`. Ver el docstring del módulo: sin esa
    distinción, cualquier miembro de una regla AEMPS parecía duplicarse con
    cualquier otro."""
    out: dict[str, Any] = {"duplicities": [], "duplicities_suppressed": [],
                           "duplicity_not_evaluated": [], "duplicity_warnings": []}

    orden: dict[str, int] = {}
    for p in productos:
        if p.id in orden:
            raise ValueError(f"id de producto repetido: {p.id!r}")
        orden[p.id] = len(orden)

    no_resueltas: list[str] = []
    # drug_id -> {product_id: nombre con que llegó}
    por_droga: dict[int, dict[str, str]] = {}
    for p in productos:
        for nombre, did in zip(p.sustancias, p.drug_ids, strict=True):
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
                rule="misma-sustancia", other_classes=[]))

    if clases_por_drug is None:
        out["duplicity_warnings"].append(AVISO_SIN_CLASES)
        return out

    # --- capa 2: clase -------------------------------------------------------
    # class_id -> (desc, {product_id: {drug_id: nombre}})
    por_clase: dict[str, tuple[str, dict[str, dict[int, str]]]] = {}
    roles_por_clase: dict[str, dict[int, str]] = {}  # class_id -> {drug_id: rol}
    for did, prods in por_droga.items():
        for cid, desc, rol in clases_por_drug.get(did, []):
            _, miembros = por_clase.setdefault(cid, (desc, {}))
            roles = roles_por_clase.setdefault(cid, {})
            if roles.get(did) != "ancla":  # ancla nunca la pisa un miembro posterior
                roles[did] = rol
            for pid, nombre in prods.items():
                miembros.setdefault(pid, {})[did] = nombre

    for cid, (desc, miembros) in sorted(por_clase.items()):
        if len(miembros) < 2:
            continue
        drogas = {d for m in miembros.values() for d in m}
        # sin ningún fármaco "ancla" de la clase entre los productos, la
        # coincidencia es de miembros de otras reglas AEMPS: no es duplicidad.
        if not any(roles_por_clase[cid].get(d) == "ancla" for d in drogas):
            continue
        productos_clase = set(miembros)
        # si un solo drug_id ya cubre (por capa 1) a TODOS los productos de la
        # clase, la alerta de clase no suma información: es el mismo aviso.
        if any(productos_clase <= set(por_droga[d]) for d in drogas):
            continue
        cfg = cupos["clases"].get(cid, {})
        desactivada = bool(cfg.get("desactivada"))
        cupo = None if desactivada else int(cfg.get("cupo", 1))
        products_en_orden = sorted(miembros, key=lambda pid: orden[pid])
        alerta = dict(
            layer="class", class_id=cid, class_desc=desc, products=products_en_orden,
            substances=sorted({n for m in miembros.values() for n in m.values()}),
            count=len(miembros), cupo=cupo, severity="moderate", source="aemps", rule=cid,
            other_classes=[])

        if desactivada or (cupo is not None and len(miembros) <= cupo):
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

    _fusionar_por_conjunto_de_productos(out["duplicities"])
    return out


def _fusionar_por_conjunto_de_productos(duplicities: list[dict]) -> None:
    """Si dos o más alertas de clase (ya filtradas, no suprimidas) comparten
    EXACTAMENTE el mismo conjunto de productos, son la misma duplicidad vista
    desde reglas AEMPS distintas (el caso alendronato+risedronato: 4 clases,
    2 productos). Se deja una sola, la de menor `class_id`, y el resto pasa a
    `other_classes`. Muta `duplicities` in place; conserva el orden original."""
    grupos: dict[frozenset[str], list[dict]] = {}
    otros: list[dict] = []
    for d in duplicities:
        if d["layer"] != "class":
            otros.append(d)
            continue
        grupos.setdefault(frozenset(d["products"]), []).append(d)

    clases_finales = []
    for entradas in grupos.values():
        principal, *resto = entradas  # ya en orden de class_id ascendente
        if resto:
            principal["other_classes"] = [
                {"class_id": e["class_id"], "class_desc": e["class_desc"]} for e in resto]
        clases_finales.append(principal)

    duplicities[:] = otros + clases_finales


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
