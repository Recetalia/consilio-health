#!/usr/bin/env python3
"""Cruzar las reglas de interacción de la AEMPS contra nuestros fármacos.

Es lo único que encontramos con **mecanismo y manejo clínico escritos en
castellano**, y hasta ahora ninguna de las 164.668 interacciones de la base
tenía ni una cosa ni la otra: salían con gravedad y sin explicación.

La AEMPS codifica sus 2.426 reglas en ATC, no en RxNorm. El puente tiene dos
carriles, porque las reglas vienen en dos niveles distintos:

* **Regla de molécula** (ATC nivel 5, `N06AB04`). Nuestro `drug.atc` es de
  nivel 4, así que un prefijo NO alcanza: `N06AB04` es citalopram, pero
  `N06AB` son todos los ISRS, y atribuirle a la sertralina una alerta que es
  del citalopram es inventar. Se resuelve por **nombre**, usando el
  diccionario ATC de la AEMPS que trae los 6.025 códigos de nivel 5 con su
  nombre en castellano.
* **Regla de clase** (ATC nivel 2 a 4, `C09A`). Ahí el prefijo sí es correcto:
  la regla habla de la clase entera.

El nombre en castellano no matchea contra nuestros alias en inglés
(`Domperidona` ≠ `Domperidone`), así que se compara por **esqueleto**: se
normalizan las dos grafías a una forma común (`ph`→`f`, `th`→`t`, `y`→`i`,
colapso de dobles, caída de la vocal final). Aplicado a los dos lados, las
diferencias sistemáticas entre el INN castellano y el inglés desaparecen.

## Por qué el ATC valida pero no veta

Medido: de los códigos que el esqueleto resuelve, cuatro tienen el ATC en
desacuerdo —`L01XE23` para dabrafenib en la AEMPS contra `L01EC` en el
nuestro—. **No son falsos positivos: es deriva de edición del ATC**, que la
OMS reorganizó. Por eso el guarda se aplica sólo a los matches laxos (primera
palabra, inversión de `X de Y`, clase de un solo fármaco), que sí son
propensos a equivocarse. Un match exacto de esqueleto sobre el nombre completo
se acepta solo.

Reseedable: borra sus propias filas antes de escribir. No toca las de nadie.
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

import sys

# `app/` no está en el path cuando se corre `python scripts/...`.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app.nlp.nombres import skeleton  # noqa: E402  (re-exportado: lo usan otros scripts)

logger = logging.getLogger("cross_aemps")

# El diccionario repite el código dentro de la descripción, y no siempre con el
# mismo separador: hay `A03FA03 - Domperidona` y `B01AF01- Rivaroxaban`.
_CODE_PREFIX = re.compile(r"^\s*[A-Z]\d{2}[A-Z]{0,2}\d{0,2}\s*-\s*")

# Los nombres de sales no son INN: `cloruro de potasio` y `potassium chloride`
# no se diferencian por un sufijo sino por la palabra entera, así que el
# esqueleto no los junta. Son pocos y cerrados; se traducen.
_LEXICO_SAL = {
    "potasio": "potassium", "sodio": "sodium", "calcio": "calcium",
    "magnesio": "magnesium", "litio": "lithium", "hierro": "iron",
    "zinc": "zinc", "aluminio": "aluminium",
    "cloruro": "chloride", "bicarbonato": "bicarbonate", "carbonato": "carbonate",
    "citrato": "citrate", "gluconato": "gluconate", "acetato": "acetate",
    "fosfato": "phosphate", "sulfato": "sulfate", "nitrato": "nitrate",
    "yoduro": "iodide", "bromuro": "bromide", "lactato": "lactate",
    "tartrato": "tartrate", "maleato": "maleate", "succinato": "succinate",
    "fumarato": "fumarate", "acido": "acid",
}


# Un ATC de producto combinado —`metformina y pioglitazona`, `ibuprofeno,
# combinaciones`— NO se puede colapsar a uno de sus ingredientes por la primera
# palabra: la regla suele hablar del OTRO. Medido: `A10BD05` (metformina y
# pioglitazona) caía en Metformina y producía el absurdo "evitar su utilización…
# hay alternativas más seguras como metformina".
_COMBINACION = re.compile(
    r"\b(y|e|and|con)\b|combinacion|combinaciones|asociad|inhibidores de",
    re.IGNORECASE)


def es_combinacion(nombre: str) -> bool:
    n = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    return bool(_COMBINACION.search(n))


def desc_limpia(v: str) -> str:
    return _CODE_PREFIX.sub("", v).strip()


def severidad(recomendacion: str) -> str:
    """La AEMPS sólo publica interacciones problemáticas: no hay `minor`.

    De las 27 recomendaciones distintas, todas abren con una de dos fórmulas.
    """
    r = unicodedata.normalize("NFKD", recomendacion.lower())
    r = r.encode("ascii", "ignore").decode()
    return "major" if "contraindicada" in r else "moderate"


def cargar_atc_names(path: str) -> dict[str, str]:
    xml = open(path, encoding="utf-8-sig").read()
    out = {}
    for code, desc in re.findall(
            r"<codigoatc>([^<]+)</codigoatc>\s*<descatc>([^<]*)</descatc>", xml):
        out[code] = desc_limpia(desc.split(" - ", 1)[1] if " - " in desc else desc)
    return out


class Resolver:
    """ATC de la AEMPS → `drug_id` nuestros, con el modo de match."""

    def __init__(self, db: sqlite3.Connection, atc_name: dict[str, str]):
        self.atc_name = atc_name
        self.drug_atc = {r[0]: (r[1] or "") for r in db.execute("select drug_id, atc from drug")}
        self.skel: dict[str, set[int]] = collections.defaultdict(set)
        for alias, did in db.execute("select alias, drug_id from drug_alias"):
            self.skel[skeleton(alias)].add(did)
        # El mapa del DNMA es la otra fuente de nombres en castellano que ya
        # tenemos resuelta a `drug_id`: se aprovecha.
        for dsc, did in db.execute(
                "select sustancia_dsc, drug_id from dnma_substance_map "
                "where drug_id is not null"):
            self.skel[skeleton(dsc)].add(did)
        self.skel.pop("", None)

        # Índice por primera palabra: la AEMPS dice `Medroxiprogesterona` y
        # nuestro canónico es `Medroxyprogesterone acetate`. Sólo se usa en el
        # carril laxo, donde el ATC tiene que respaldar el match.
        self.skel_1a: dict[str, set[int]] = collections.defaultdict(set)
        for s, ids in self.skel.items():
            self.skel_1a[s.split()[0]] |= ids

        self.por_clase: dict[str, set[int]] = collections.defaultdict(set)
        for did, atc in self.drug_atc.items():
            for p in atc.split(","):
                if p.strip():
                    self.por_clase[p.strip()].add(did)

        self.rechazos: list[tuple[str, str]] = []

    def _atc_coherente(self, did: int, code: str) -> bool | None:
        """`None` si el fármaco no tiene ATC y no se puede verificar."""
        atc = self.drug_atc.get(did) or ""
        if not atc:
            return None
        return any(code.startswith(p.strip()) for p in atc.split(",") if p.strip())

    def _laxos(self, nombre: str) -> set[int]:
        """Candidatos de menor confianza. Todos pasan después por el ATC."""
        # Un producto combinado no se resuelve a un ingrediente: ver la nota de
        # `_COMBINACION`. Se prefiere no tener la regla a tenerla mal atribuida.
        if es_combinacion(nombre):
            return set()
        variantes = [nombre]
        if " de " in nombre.lower():                  # `cloruro de potasio`
            a, b = nombre.lower().split(" de ", 1)
            variantes.append(f"{b} {a}")
        # `potasio cloruro` -> `potassium chloride`
        variantes += [" ".join(_LEXICO_SAL.get(w, w) for w in v.lower().split())
                      for v in list(variantes)]

        for v in variantes:
            s = skeleton(v)
            if not s:
                continue
            for cand in (self.skel.get(s), self.skel_1a.get(s)):
                if cand:
                    return set(cand)
            if " " in s:                              # `dabigatran etexilato`
                c = self.skel.get(s.split()[0]) or self.skel_1a.get(s.split()[0])
                if c:
                    return set(c)
        return set()

    def resolver(self, code: str) -> tuple[list[int], str]:
        if len(code) < 7:
            ids = {d for cl, ds in self.por_clase.items() if cl.startswith(code) for d in ds}
            return sorted(ids), ("clase" if ids else "sin-clase")

        nombre = self.atc_name.get(code, "")
        # 1) match exacto de esqueleto: se acepta sin pedirle nada al ATC.
        exactos = self.skel.get(skeleton(nombre), set())
        if len(exactos) == 1:
            return list(exactos), "molecula"
        if len(exactos) > 1:
            # Varios fármacos con el mismo esqueleto: ahí sí desempata el ATC.
            val = [d for d in exactos if self._atc_coherente(d, code) is True]
            if len(val) == 1:
                return val, "molecula"
            return [], "ambiguo"

        # 2) matches laxos: sólo valen si el ATC respalda a UNO solo. Con dos
        # candidatos válidos no hay match, hay elección arbitraria: el índice
        # por primera palabra devuelve todas las sales de potasio juntas, y
        # quedarse con la primera fue exactamente cómo `Potasio gluceptato`
        # terminó apuntando a `Potassium bicarbonate`.
        val = [d for d in self._laxos(nombre) if self._atc_coherente(d, code) is True]
        if len(val) == 1:
            return val, "molecula-laxa"
        if len(val) > 1:
            return [], "ambiguo"

        # 3) la clase nivel-4 tiene un solo fármaco: no hay a quién confundir.
        clase = self.por_clase.get(code[:5], set())
        if len(clase) == 1:
            return list(clase), "clase-unica"

        self.rechazos.append((code, nombre))
        return [], "sin-resolver"


def migrar_source(db: sqlite3.Connection) -> None:
    """Agregar 'aemps' al CHECK de `interaction.source`.

    SQLite no sabe alterar un CHECK: hay que reconstruir la tabla. Se hace una
    sola vez y es idempotente.
    """
    ddl = db.execute(
        "select sql from sqlite_master where type='table' and name='interaction'"
    ).fetchone()[0]
    if "'aemps'" in ddl:
        return
    logger.info("Migrando el CHECK de interaction.source para admitir 'aemps'")
    nuevo = ddl.replace("'ddinter','openfda','recetalia'",
                        "'aemps','ddinter','openfda','recetalia'")
    if nuevo == ddl:
        raise SystemExit("no se pudo reescribir el CHECK; revisar el DDL a mano")
    db.executescript(f"""
        pragma foreign_keys=off;
        begin;
        {nuevo.replace('CREATE TABLE interaction', 'CREATE TABLE interaction_new', 1)};
        insert into interaction_new select * from interaction;
        drop table interaction;
        alter table interaction_new rename to interaction;
        create index if not exists idx_ix_a on interaction(drug_a_id);
        create index if not exists idx_ix_b on interaction(drug_b_id);
        commit;
        pragma foreign_keys=on;
    """)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="data/recetalia_interactions.db")
    p.add_argument("--reglas", default="data/aemps/aemps_reglas.json")
    p.add_argument("--dicc-atc", default="data/aemps/DICCIONARIO_ATC.xml")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    for f in (args.db, args.reglas, args.dicc_atc):
        if not os.path.exists(f):
            raise SystemExit(f"falta {f}")

    db = sqlite3.connect(args.db)
    atc_name = cargar_atc_names(args.dicc_atc)
    logger.info("Diccionario ATC: %d códigos (%d de nivel 5)",
                len(atc_name), sum(1 for k in atc_name if len(k) >= 7))

    reglas = json.load(open(args.reglas, encoding="utf-8"))["interacciones"]
    res = Resolver(db, atc_name)

    # Un par puede venir de más de una regla: se queda la más grave, y los
    # efectos distintos se acumulan en vez de pisarse.
    pares: dict[tuple[int, int], dict] = {}
    modos = collections.Counter()
    for r in reglas:
        A, ma = res.resolver(r["atc_a"])
        B, mb = res.resolver(r["atc_b"])
        modos[(ma, mb)] += 1
        if not A or not B:
            continue
        sev = severidad(r["recomendacion"])
        for a in A:
            for b in B:
                if a == b:
                    continue
                k = (min(a, b), max(a, b))
                prev = pares.get(k)
                if prev is None:
                    pares[k] = {"severity": sev, "efectos": [r["efecto"]],
                                "manejos": [r["recomendacion"]],
                                "modo": f"{ma}/{mb}",
                                "atc": f"{r['atc_a']}+{r['atc_b']}"}
                    continue
                if sev == "major" and prev["severity"] != "major":
                    prev["severity"] = "major"
                if r["efecto"] not in prev["efectos"]:
                    prev["efectos"].append(r["efecto"])
                if r["recomendacion"] not in prev["manejos"]:
                    prev["manejos"].append(r["recomendacion"])

    logger.info("Reglas por modo de resolución:")
    for k, v in modos.most_common(8):
        logger.info("   %5d  %s", v, "/".join(k))
    logger.info("Códigos que no resolvieron: %d distintos", len(set(res.rechazos)))

    ya = {(a, b) for a, b in db.execute(
        "select drug_a_id, drug_b_id from interaction where source <> 'aemps'")}
    nuevos = len(set(pares) - ya)
    logger.info("=== %d pares · %d ya conocidos (ahora con texto) · %d NUEVOS ===",
                len(pares), len(pares) - nuevos, nuevos)

    if args.dry_run:
        logger.info("dry-run: no se escribió nada")
        return

    migrar_source(db)
    borradas = db.execute("delete from interaction where source='aemps'").rowcount
    if borradas:
        logger.info("Reemplazando %d filas 'aemps' previas", borradas)

    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # `evidence` queda en NULL a propósito: es el campo del que la interfaz saca
    # la descripción, y meterle un sello de fecha le ganaba al mecanismo, que es
    # el texto que el médico necesita leer. La procedencia ya la dice `source`, y
    # la fecha vive en `meta.aemps_cross_at`.
    db.executemany(
        "insert into interaction (drug_a_id, drug_b_id, severity, mechanism, "
        "management, source, note) values (?,?,?,?,?, 'aemps', ?)",
        [(a, b, v["severity"], " · ".join(v["efectos"]), " · ".join(v["manejos"]),
          f"match {v['modo']} · {v['atc']}")
         for (a, b), v in pares.items()])
    db.execute("insert or replace into meta (key, value) values ('aemps_cross_at', ?)", (ahora,))
    db.commit()

    con_texto = db.execute(
        "select count(*) from interaction where mechanism is not null and mechanism<>''"
    ).fetchone()[0]
    logger.info("Escritas %d filas. Interacciones con mecanismo en la base: %d",
                len(pares), con_texto)


if __name__ == "__main__":
    main()
