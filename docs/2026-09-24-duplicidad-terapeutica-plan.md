# Duplicidad terapéutica — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consilio detecta duplicidad terapéutica (misma sustancia en dos productos, y clase con cupo) sin alertar combinaciones intencionales, con procedencia y supresiones visibles; Recetalia le manda los productos agrupados.

**Architecture:** Un ETL (`scripts/cross_aemps_duplicidad.py`) convierte las 1.593 reglas de la AEMPS en membresías `drug_class(drug_id, class_id)` con clase = ATC4 del ancla, descartando combinados. En tiempo de consulta, un evaluador puro (`app/services/duplicity_checker.py`) cuenta productos por sustancia y por clase, aplica `data/duplicidad_cupos.json` y devuelve alertas y supresiones. `/interactions` acepta `products` y suma los campos a la respuesta.

**Tech Stack:** Python 3.12, FastAPI, pydantic v2, aiosqlite, pytest (`asyncio_mode = "auto"`); JS vanilla (UI); Java 21 / Spring Boot 3.3 (Recetalia).

**Spec:** [2026-09-24-duplicidad-terapeutica-design.md](2026-09-24-duplicidad-terapeutica-design.md)

**Convenciones del repo:** comentarios y docstrings en castellano, explicando el *porqué* y citando lo medido. Tests con nombres en castellano (`test_...`). Todo comando se corre desde `consilio/` salvo que diga otra cosa. Suite: `.venv/bin/python -m pytest -q` (142 pasan antes de empezar).

---

## Mapa de archivos

| Archivo | Acción | Responsabilidad |
|---|---|---|
| `app/nlp/nombres.py` | crear | `skeleton()`: forma común INN castellano/inglés. Movido desde el script. |
| `scripts/cross_aemps_interactions.py` | modificar | Importa `skeleton` de `app.nlp.nombres` (re-exporta). |
| `app/clients/recetalia_db.py` | modificar | Respaldo de nombres en `drug_id_by_name`; `classes_for`, `canonicals_for`. |
| `scripts/cross_aemps_duplicidad.py` | crear | ETL reglas AEMPS → `drug_class`. Detector de combinados. |
| `data/duplicidad_cupos.json` | crear | Cupos/excepciones curados (primer lote vacío). |
| `app/services/duplicity_checker.py` | crear | `evaluar()` puro + `chequear()` (resolución + DB) + carga de cupos. |
| `app/api/schemas.py` | modificar | `ProductIn`, `products`, campos de duplicidad en la respuesta. |
| `app/services/interaction_checker.py` | modificar | `check(drug_names, products=None)` suma duplicidad. |
| `app/api/interactions.py` | modificar | Pasa `products`. |
| `tests/regression/casos_duplicidad.json` | crear | Casos clínicos con esperado. |
| `scripts/eval_duplicidad.py` | crear | Métrica: aciertos/fallos por caso (la corre la routine). |
| `app/web/app.js` | modificar | `cardDuplicidad`, filtros, conteo, portapapeles. |
| `README.md` | modificar | Paso nuevo en el orden del ETL. |
| Recetalia `feat/consilio-interacciones` | modificar | Manda `products`, mapea duplicidades, arregla `putIfAbsent`. |

---

### Task 1: Mover `skeleton` a `app/nlp/nombres.py`

**Files:**
- Create: `app/nlp/nombres.py`
- Modify: `scripts/cross_aemps_interactions.py:59-62,99-117`
- Test: `tests/test_nombres.py`

- [ ] **Step 1: Test que falla**

```python
# tests/test_nombres.py
"""El esqueleto junta la grafía castellana y la inglesa de un mismo INN."""
from app.nlp.nombres import skeleton


def test_castellano_e_ingles_caen_en_el_mismo_esqueleto():
    assert skeleton("Domperidona") == skeleton("Domperidone") == "domperidon"
    assert skeleton("diclofenaco") == skeleton("Diclofenac")
    assert skeleton("Disopiramida") == skeleton("Disopyramide")


def test_el_script_sigue_exportando_skeleton():
    import sys
    sys.path.insert(0, "scripts")
    from cross_aemps_interactions import skeleton as s
    assert s is skeleton
```

- [ ] **Step 2: Correr y ver que falla**

Run: `.venv/bin/python -m pytest tests/test_nombres.py -q`
Expected: FAIL `ModuleNotFoundError: No module named 'app.nlp.nombres'`

- [ ] **Step 3: Crear el módulo** (copia exacta de lo que hoy vive en el script)

```python
# app/nlp/nombres.py
"""Comparación de nombres de fármaco entre castellano e inglés.

Vive en `app/` y no en `scripts/` porque ahora lo usan los dos: el ETL para
cruzar la AEMPS, y la resolución de nombres en tiempo de consulta, que recibe
las sustancias del DNMA en castellano (`diclofenaco`) contra alias en inglés.
"""
from __future__ import annotations

import re
import unicodedata

# Correspondencias sistemáticas entre el INN castellano y el inglés. Se aplican
# a los DOS lados, así que no importa cuál de las dos grafías es la "correcta":
# importa que las dos caigan en la misma.
_SKEL_SUBS = (
    ("ph", "f"), ("th", "t"), ("ch", "c"), ("qu", "c"), ("ou", "u"),
    ("ae", "e"), ("oe", "e"), ("y", "i"), ("k", "c"), ("w", "v"),
)


def skeleton(s: str) -> str:
    """Forma común a la grafía castellana e inglesa de un mismo INN.

    `Domperidona` y `Domperidone` → `domperidon`.
    `Disopiramida` y `Disopyramide` → `disopiramid`.
    """
    s = unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z ]+", " ", s).strip()
    for a, b in _SKEL_SUBS:
        s = s.replace(a, b)
    s = re.sub(r"(.)\1+", r"\1", s)
    palabras = []
    for w in s.split():
        w = re.sub(r"e$", "", w)
        w = re.sub(r"[ao]$", "", w)
        if w:
            palabras.append(w)
    return " ".join(palabras)
```

- [ ] **Step 4: El script importa de ahí.** En `scripts/cross_aemps_interactions.py` borrar `_SKEL_SUBS` (líneas 56-62, con su comentario) y la función `skeleton` entera (99-117). Después de `from datetime import datetime, timezone` agregar:

```python
import sys

# `app/` no está en el path cuando se corre `python scripts/...`.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app.nlp.nombres import skeleton  # noqa: E402  (re-exportado: lo usan otros scripts)
```

- [ ] **Step 5: Correr** `.venv/bin/python -m pytest tests/test_nombres.py tests/regression -q` → PASS (los de regresión siguen verdes: `Resolver` usa el mismo `skeleton`).

- [ ] **Step 6: Commit**

```bash
git add app/nlp/nombres.py scripts/cross_aemps_interactions.py tests/test_nombres.py
git commit -m "mover skeleton a app/nlp/nombres: lo va a usar la resolución en consulta"
```

---

### Task 2: Nombres en castellano — respaldo en `drug_id_by_name`

Medido: `diclofenaco` no resuelve; `amlodipino` sólo por el mapa del DNMA.

**Files:**
- Modify: `app/clients/recetalia_db.py:120-151` (init/close), `:197-204` (`drug_id_by_name`)
- Test: `tests/regression/test_nombres_castellano.py`

- [ ] **Step 1: Test que falla** (contra la base real, fixture igual al de `test_aemps_cross.py`)

```python
# tests/regression/test_nombres_castellano.py
"""Recetalia manda las sustancias del DNMA en castellano; tienen que resolver.

Medido 2026-09-24: `diclofenaco` no resolvía por `drug_alias` y `amlodipino`
sólo aparecía en `dnma_substance_map`. Sin resolver no hay interacción ni
duplicidad: el fármaco queda afuera en silencio.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

DB_PATH = Path(os.environ.get("INTERACTION_DB_PATH", "data/recetalia_interactions.db"))


@pytest.fixture
async def db():
    if not DB_PATH.exists():
        pytest.skip("falta la base")
    from app.clients import recetalia_db
    await recetalia_db.client.close()
    recetalia_db.client.db_path = str(DB_PATH)
    yield recetalia_db.client
    await recetalia_db.client.close()


async def _canon(db, nombre):
    did = await db.drug_id_by_name(nombre)
    assert did, f"{nombre} no resolvió"
    return (await db.canonicals_for([did]))[did]


async def test_por_esqueleto(db):
    assert await _canon(db, "diclofenaco") == "Diclofenac"


async def test_por_mapa_del_dnma(db):
    assert await _canon(db, "amlodipino") == "Amlodipine"


async def test_lo_que_ya_resolvia_no_cambia(db):
    assert await _canon(db, "LOSARTAN POTASICO") == "Losartan"
    assert await _canon(db, "paracetamol") == "Acetaminophen"


async def test_un_nombre_inexistente_sigue_sin_resolver(db):
    assert await db.drug_id_by_name("zzzz no existe") is None
```

- [ ] **Step 2: Correr** `.venv/bin/python -m pytest tests/regression/test_nombres_castellano.py -q` → FAIL (`canonicals_for` no existe).

- [ ] **Step 3: Implementar.** En `RecetaliaDatabase.__init__` agregar `self._respaldo: dict | None = None`; en `close()` agregar `self._respaldo = None` (el índice es de ESA base: los tests cambian `db_path`). Agregar el import `from collections import defaultdict` y `from app.nlp.nombres import skeleton`. Reemplazar `drug_id_by_name` por:

```python
    async def drug_id_by_name(self, name: str) -> int | None:
        """Alias exacto; si no, el nombre del DNMA; si no, el esqueleto INN.

        Los dos respaldos existen porque Recetalia manda castellano y los alias
        son mayormente inglés. El esqueleto se acepta sólo si apunta a UN
        fármaco: con dos candidatos no hay match, hay elección arbitraria.
        """
        conn = await self._c()
        n = normalize(name)
        async with conn.execute(
            "select drug_id from drug_alias where alias_norm = ? limit 1", (n,)
        ) as cur:
            row = await cur.fetchone()
        if row:
            return row["drug_id"]
        idx = await self._indice_respaldo()
        return idx["dnma"].get(n) or idx["skel"].get(skeleton(name))

    async def _indice_respaldo(self) -> dict[str, dict]:
        if self._respaldo is not None:
            return self._respaldo
        conn = await self._c()
        dnma: dict[str, int] = {}
        skel: dict[str, set[int]] = defaultdict(set)
        try:
            async with conn.execute(
                "select sustancia_dsc, drug_id from dnma_substance_map "
                "where drug_id is not null"
            ) as cur:
                for r in await cur.fetchall():
                    dnma.setdefault(normalize(r[0]), r[1])
                    skel[skeleton(r[0])].add(r[1])
        except aiosqlite.OperationalError:
            logger.warning("Sin dnma_substance_map: el respaldo por DNMA queda vacío")
        async with conn.execute("select alias, drug_id from drug_alias") as cur:
            for r in await cur.fetchall():
                skel[skeleton(r[0])].add(r[1])
        self._respaldo = {
            "dnma": dnma,
            "skel": {s: next(iter(ids)) for s, ids in skel.items() if s and len(ids) == 1},
        }
        return self._respaldo

    async def canonicals_for(self, drug_ids: list[int]) -> dict[int, str]:
        if not drug_ids:
            return {}
        conn = await self._c()
        ph = ",".join("?" * len(drug_ids))
        async with conn.execute(
            f"select drug_id, canonical from drug where drug_id in ({ph})", tuple(drug_ids)
        ) as cur:
            return {r["drug_id"]: r["canonical"] for r in await cur.fetchall()}
```

- [ ] **Step 4: Correr** el test nuevo y la suite entera: `.venv/bin/python -m pytest -q` → todo PASS. Si algún test existente cambia porque ahora un nombre resuelve, leer el caso: si el match nuevo es correcto, actualizar el esperado citando esta tarea; si es incorrecto, el esqueleto es demasiado laxo para ese nombre → parar y reportar.

- [ ] **Step 5: Commit**

```bash
git add app/clients/recetalia_db.py tests/regression/test_nombres_castellano.py
git commit -m "resolver sustancias en castellano: respaldo por DNMA y por esqueleto único"
```

---

### Task 3: ETL `cross_aemps_duplicidad.py` → tabla `drug_class`

**Files:**
- Create: `scripts/cross_aemps_duplicidad.py`
- Test: `tests/test_cross_aemps_duplicidad.py` (puro), `tests/regression/test_duplicidad_clases.py` (base real)

- [ ] **Step 1: Tests puros que fallan**

```python
# tests/test_cross_aemps_duplicidad.py
"""Detector de combinados y clase del ancla, sin base."""
import sys

sys.path.insert(0, "scripts")
from cross_aemps_duplicidad import clase_de, es_codigo_combinado  # noqa: E402

NOMBRES = {
    "C09AA": "Inhibidores de la ECA, monofarmacos",
    "C09AA02": "Enalapril",
    "C09AA05": "Ramipril",
    "C09BA": "Inhibidores de la ECA y diureticos",
    "C09BA02": "Enalapril y diureticos",
    "C09BA05": "Ramipril y diureticos",
    "N02BE": "Anilidas",
    "N02BE01": "Paracetamol",
    "N02BE51": "Paracetamol, combinaciones excluyendo psicolepticos",
    "N02BE71": "Paracetamol, combinaciones con psicolepticos",
    "A02BC": "Inhibidores de la bomba de protones",
    "A02BC01": "Omeprazol",
    "N04BA": "Dopa y derivados de la dopa",
    "N04BA01": "Levodopa",
    "N04BA02": "Levodopa e inhibidor de la decarboxilasa",
    "N04BA03": "Levodopa, inhibidor de la decarboxilasa e inhibidor de la COMT",
}


def test_la_clase_es_el_atc4_del_ancla():
    assert clase_de("N05BA01") == "N05BA"
    assert clase_de("C09AA") == "C09AA"
    assert clase_de("J01C") == "J01C"


def test_n4_monofarmaco_no_es_combinado_aunque_diga_inhibidores_de():
    assert not es_codigo_combinado("C09AA", NOMBRES)
    assert not es_codigo_combinado("A02BC", NOMBRES)


def test_n4_de_combinados_es_combinado():
    assert es_codigo_combinado("C09BA", NOMBRES)


def test_anilidas_no_es_combinado_aunque_casi_todos_sus_hijos_lo_sean():
    """El nombre no dice combinación: hace falta que lo digan nombre E hijos."""
    assert not es_codigo_combinado("N02BE", NOMBRES)


def test_n5():
    assert es_codigo_combinado("C09BA02", NOMBRES)
    assert es_codigo_combinado("N02BE51", NOMBRES)
    assert not es_codigo_combinado("N02BE01", NOMBRES)


def test_lista_explicita_de_falsos():
    assert not es_codigo_combinado("N04BA", NOMBRES)
```

- [ ] **Step 2: Correr** `.venv/bin/python -m pytest tests/test_cross_aemps_duplicidad.py -q` → FAIL (módulo no existe).

- [ ] **Step 3: Implementar el script**

```python
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

Reseedable: borra sus propias filas antes de escribir.
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

DDL = """
create table if not exists drug_class (
    drug_id    integer not null references drug(drug_id),
    class_id   text    not null,          -- ATC4 del ancla (o N3 si el ancla es N3)
    class_desc text    not null,
    source     text    not null,
    note       text,
    primary key (drug_id, class_id, source)
);
create index if not exists idx_dc_drug on drug_class(drug_id);
"""

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
    """
    if len(code) >= 7:
        return es_combinacion(nombres.get(code, ""))
    if code in _NO_COMBINADO:
        return False
    if not _COMBINACION_CLASE.search(_ascii(nombres.get(code, ""))):
        return False
    hijos = [n for c, n in nombres.items() if len(c) >= 7 and c.startswith(code)]
    return bool(hijos) and sum(es_combinacion(h) for h in hijos) / len(hijos) >= 0.5


def quitar_combinados(res: Resolver, nombres: dict[str, str]) -> None:
    """La expansión por prefijo no puede entrar por un ATC de combinado."""
    por_clase: dict[str, set[int]] = collections.defaultdict(set)
    for did, atc in res.drug_atc.items():
        for p in (x.strip() for x in atc.split(",")):
            if p and not es_codigo_combinado(p, nombres):
                por_clase[p].add(did)
    res.por_clase = por_clase


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

    db = sqlite3.connect(args.db)
    nombres = cargar_atc_names(args.dicc_atc)
    res = Resolver(db, nombres)
    quitar_combinados(res, nombres)
    reglas = json.load(open(args.reglas, encoding="utf-8"))["duplicidades"]

    filas: dict[tuple[int, str], tuple] = {}
    modos: collections.Counter = collections.Counter()
    descartadas = 0
    for r in reglas:
        a, b = r["atc_a"].strip(), r["atc_b"].strip()
        if es_codigo_combinado(a, nombres) or es_codigo_combinado(b, nombres):
            descartadas += 1
            continue
        cid = clase_de(a)
        desc = nombres.get(cid) or r["desc"].strip()
        for code in (a, b):
            ids, modo = res.resolver(code)
            modos[modo] += 1
            for did in ids:
                filas[(did, cid)] = (did, cid, desc, "aemps", f"match {modo} · {code}")

    por_clase = collections.Counter(cid for _, cid in filas)
    logger.info("=== %d membresías · %d fármacos · %d clases (%d con ≥2 miembros) ===",
                len(filas), len({d for d, _ in filas}), len(por_clase),
                sum(1 for n in por_clase.values() if n >= 2))
    logger.info("Reglas descartadas por combinado: %d de %d", descartadas, len(reglas))
    logger.info("Resolución de códigos: %s", dict(modos.most_common()))

    if args.dry_run:
        logger.info("dry-run: no se escribió nada")
        return

    db.executescript(DDL)
    borradas = db.execute("delete from drug_class where source='aemps'").rowcount
    if borradas:
        logger.info("Reemplazando %d filas previas", borradas)
    db.executemany(
        "insert into drug_class (drug_id, class_id, class_desc, source, note) "
        "values (?,?,?,?,?)", list(filas.values()))
    db.execute("insert or replace into meta (key, value) values ('aemps_duplicidad_at', ?)",
               (datetime.now(timezone.utc).isoformat(timespec="seconds"),))
    db.commit()
    logger.info("Escritas %d filas", len(filas))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Correr** los tests puros → PASS.

- [ ] **Step 5: Correr el ETL en seco y anotar los números.**

Run: `PYTHONPATH=scripts .venv/bin/python scripts/cross_aemps_duplicidad.py --dry-run`
Expected: líneas `=== N membresías · … clases …`, `Reglas descartadas por combinado: …`. **Copiar esas tres líneas** a la sección "Datos de partida" del spec con la fecha y el comando (regla de hallazgos medidos).

- [ ] **Step 6: Correr de verdad** `PYTHONPATH=scripts .venv/bin/python scripts/cross_aemps_duplicidad.py`

- [ ] **Step 7: Test de regresión sobre la base**

```python
# tests/regression/test_duplicidad_clases.py
"""Las membresías que deciden si el módulo sirve o se ignora.

Cada assert es un falso positivo medido o un caso que tiene que alertar.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

DB_PATH = Path(os.environ.get("INTERACTION_DB_PATH", "data/recetalia_interactions.db"))


@pytest.fixture
def cx():
    if not DB_PATH.exists():
        pytest.skip("falta la base")
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    if not c.execute("select 1 from sqlite_master where name='drug_class'").fetchone():
        pytest.skip("drug_class no cargada: correr scripts/cross_aemps_duplicidad.py")
    yield c
    c.close()


def clases(cx, canonical):
    return {r[0] for r in cx.execute(
        "select class_id from drug_class dc join drug d using(drug_id) "
        "where d.canonical = ?", (canonical,))}


def test_benzodiacepinas_comparten_clase(cx):
    assert "N05BA" in clases(cx, "Diazepam") & clases(cx, "Lorazepam")


def test_isrs_comparten_clase(cx):
    assert "N06AB" in clases(cx, "Sertraline") & clases(cx, "Fluoxetine")


def test_ieca_aca_y_tiazida_no_comparten_clase(cx):
    """El falso positivo canónico: combinación intencional de primera línea."""
    e, a, h = clases(cx, "Enalapril"), clases(cx, "Amlodipine"), clases(cx, "Hydrochlorothiazide")
    assert not (e & a) and not (e & h) and not (a & h), (e, a, h)


def test_la_tiazida_no_entra_a_los_ara2_por_el_atc_del_combinado(cx):
    assert not (clases(cx, "Losartan") & clases(cx, "Hydrochlorothiazide"))
```

Run: `.venv/bin/python -m pytest tests/regression/test_duplicidad_clases.py -q` → PASS. Si alguno falla, **no** tocar el assert: imprimir las filas (`select * from drug_class where drug_id=…`) y ver qué regla/código lo metió (columna `note`).

- [ ] **Step 8: Commit** (la base no se versiona)

```bash
git add scripts/cross_aemps_duplicidad.py tests/test_cross_aemps_duplicidad.py tests/regression/test_duplicidad_clases.py docs/2026-09-24-duplicidad-terapeutica-design.md
git commit -m "ETL de duplicidad: reglas AEMPS -> drug_class, clase = ATC4 del ancla, sin combinados"
```

---

### Task 4: Lectura de clases en `RecetaliaDatabase`

**Files:**
- Modify: `app/clients/recetalia_db.py` (después de `population_alerts_for`, ~`:390`)
- Test: `tests/regression/test_duplicidad_clases.py` (agregar)

- [ ] **Step 1: Test que falla** — agregar al final de `tests/regression/test_duplicidad_clases.py`:

```python
@pytest.fixture
async def db():
    if not DB_PATH.exists():
        pytest.skip("falta la base")
    from app.clients import recetalia_db
    await recetalia_db.client.close()
    recetalia_db.client.db_path = str(DB_PATH)
    yield recetalia_db.client
    await recetalia_db.client.close()


async def test_classes_for(db):
    d = await db.drug_id_by_name("diazepam")
    out = await db.classes_for([d])
    assert out is not None
    assert ("N05BA" in {c for c, _ in out[d]}), out
```

- [ ] **Step 2: Correr** → FAIL (`classes_for` no existe).

- [ ] **Step 3: Implementar**

```python
    async def classes_for(self, drug_ids: list[int]) -> dict[int, list[tuple[str, str]]] | None:
        """Clases de duplicidad por fármaco. `None` si la tabla no existe.

        `None` y `{}` no son lo mismo: el primero es "no se evaluó" (ETL sin
        correr) y el llamador lo tiene que decir; el segundo es "se evaluó y
        ningún fármaco tiene clase".
        """
        if not drug_ids:
            return {}
        conn = await self._c()
        ph = ",".join("?" * len(drug_ids))
        try:
            async with conn.execute(
                f"select drug_id, class_id, class_desc from drug_class "
                f"where drug_id in ({ph}) order by class_id", tuple(drug_ids)
            ) as cur:
                rows = await cur.fetchall()
        except aiosqlite.OperationalError:
            return None
        out: dict[int, list[tuple[str, str]]] = {}
        for r in rows:
            out.setdefault(r["drug_id"], []).append((r["class_id"], r["class_desc"]))
        return out
```

- [ ] **Step 4: Correr** → PASS.

- [ ] **Step 5: Commit**

```bash
git add app/clients/recetalia_db.py tests/regression/test_duplicidad_clases.py
git commit -m "classes_for: membresías de duplicidad, None si la tabla no está"
```

---

### Task 5: Evaluador puro `duplicity_checker.evaluar` + cupos

**Files:**
- Create: `app/services/duplicity_checker.py`, `data/duplicidad_cupos.json`
- Test: `tests/test_duplicity_checker.py`

- [ ] **Step 1: Tests que fallan**

```python
# tests/test_duplicity_checker.py
"""Evaluador de duplicidad, sin base: productos resueltos + membresías + cupos."""
from app.services.duplicity_checker import Producto, evaluar

SIN_CUPOS = {"clases": {}, "excepciones": []}
CANON = {1: "Acetaminophen", 2: "Codeine", 3: "Diazepam", 4: "Lorazepam",
         5: "Enalapril", 6: "Insulin glargine", 7: "Insulin aspart"}
CLASES = {1: [("N02BE", "Anilidas")], 3: [("N05BA", "Benzodiazepinas")],
          4: [("N05BA", "Benzodiazepinas")], 5: [("C09AA", "IECA")],
          6: [("A10AB", "Insulinas")], 7: [("A10AB", "Insulinas")]}


def P(pid, *pares):
    return Producto(id=pid, sustancias=tuple(n for n, _ in pares),
                    drug_ids=tuple(d for _, d in pares))


def test_misma_sustancia_en_dos_productos_es_capa_1():
    out = evaluar([P("p1", ("paracetamol", 1)), P("p2", ("paracetamol", 1), ("codeina", 2))],
                  CLASES, SIN_CUPOS, CANON)
    [d] = out["duplicities"]
    assert d["layer"] == "substance" and d["severity"] == "major"
    assert d["products"] == ["p1", "p2"] and d["cupo"] == 0
    # la de clase N02BE la explica la de sustancia: no se repite
    assert not [x for x in out["duplicities"] if x["layer"] == "class"]


def test_sustancias_del_mismo_producto_no_se_comparan():
    out = evaluar([P("p1", ("diazepam", 3), ("lorazepam", 4))], CLASES, SIN_CUPOS, CANON)
    assert out["duplicities"] == []


def test_dos_de_la_misma_clase_es_capa_2():
    out = evaluar([P("p1", ("diazepam", 3)), P("p2", ("lorazepam", 4))], CLASES, SIN_CUPOS, CANON)
    [d] = out["duplicities"]
    assert (d["layer"], d["class_id"], d["count"], d["cupo"]) == ("class", "N05BA", 2, 1)
    assert d["severity"] == "moderate" and d["source"] == "aemps"
    assert d["substances"] == ["diazepam", "lorazepam"]


def test_cupo_curado_suprime_y_lo_dice():
    cupos = {"clases": {"N05BA": {"cupo": 2, "motivo": "m", "referencia": "r",
                                  "validado": False}}, "excepciones": []}
    out = evaluar([P("p1", ("diazepam", 3)), P("p2", ("lorazepam", 4))], CLASES, cupos, CANON)
    assert out["duplicities"] == []
    [s] = out["duplicities_suppressed"]
    assert s["motivo"] == "m" and s["referencia"] == "r" and s["validado"] is False


def test_clase_desactivada_suprime():
    cupos = {"clases": {"N05BA": {"desactivada": True, "motivo": "amplia",
                                  "validado": False}}, "excepciones": []}
    out = evaluar([P("p1", ("diazepam", 3)), P("p2", ("lorazepam", 4))], CLASES, cupos, CANON)
    assert out["duplicities"] == [] and out["duplicities_suppressed"][0]["motivo"] == "amplia"


def test_excepcion_por_grupos():
    cupos = {"clases": {}, "excepciones": [{
        "clase": "A10AB", "grupos": [["Insulin glargine"], ["Insulin aspart"]],
        "motivo": "basal + bolo", "referencia": "x", "validado": False}]}
    uno_de_cada = evaluar([P("p1", ("glargina", 6)), P("p2", ("aspart", 7))], CLASES, cupos, CANON)
    assert uno_de_cada["duplicities"] == []
    assert uno_de_cada["duplicities_suppressed"][0]["motivo"] == "basal + bolo"


def test_no_resuelto_se_declara():
    out = evaluar([P("p1", ("xx", None)), P("p2", ("diazepam", 3))], CLASES, SIN_CUPOS, CANON)
    assert out["duplicity_not_evaluated"] == ["xx"]


def test_sin_tabla_de_clases_avisa_y_hace_capa_1():
    out = evaluar([P("p1", ("paracetamol", 1)), P("p2", ("paracetamol", 1))], None, SIN_CUPOS, CANON)
    assert out["duplicities"][0]["layer"] == "substance"
    assert out["duplicity_warnings"]
```

- [ ] **Step 2: Correr** `.venv/bin/python -m pytest tests/test_duplicity_checker.py -q` → FAIL (módulo no existe).

- [ ] **Step 3: Crear `data/duplicidad_cupos.json`**

```json
{
  "_nota": "Cupos y excepciones de duplicidad curados a mano. Ver docs/2026-09-24-duplicidad-terapeutica-design.md, Capa 3. Primer lote vacío a propósito: cada entrada sale de un caso real que falle, con validado=false hasta que la revise alguien con criterio farmacéutico.",
  "clases": {},
  "excepciones": []
}
```

- [ ] **Step 4: Implementar el evaluador**

```python
# app/services/duplicity_checker.py
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


def _alerta(**kw: Any) -> dict[str, Any]:
    return kw


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
            out["duplicities"].append(_alerta(
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
        alerta = _alerta(
            layer="class", class_id=cid, class_desc=desc, products=list(miembros),
            substances=sorted({n for m in miembros.values() for n in m.values()}),
            count=len(miembros), cupo=cupo, severity="moderate", source="aemps", rule=cid)

        motivo = None
        if cfg.get("desactivada"):
            motivo = cfg
        elif len(miembros) <= cupo:
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
            if None in gs or len(gs) != 1 or (g := gs.pop()) in usados:
                ok = False
                break
            usados.add(g)
        if ok:
            return exc
    return None
```

- [ ] **Step 5: Correr** los tests → PASS.

- [ ] **Step 6: Commit**

```bash
git add app/services/duplicity_checker.py data/duplicidad_cupos.json tests/test_duplicity_checker.py
git commit -m "evaluador de duplicidad: sustancia (cupo 0) y clase con cupo, supresiones con motivo"
```

---

### Task 6: `chequear()` — de nombres a evaluación, contra la base

**Files:**
- Modify: `app/services/duplicity_checker.py` (al final)
- Test: `tests/regression/test_duplicidad_casos.py`, `tests/regression/casos_duplicidad.json`

- [ ] **Step 1: Casos clínicos**

```json
[
  {"nombre": "paracetamol solo + paracetamol/codeína", "productos": [["paracetamol"], ["paracetamol", "codeina"]], "esperado": {"capa": "substance"}},
  {"nombre": "dos AINEs", "productos": [["ibuprofeno"], ["diclofenaco"]], "esperado": {"capa": "class"}},
  {"nombre": "dos benzodiacepinas", "productos": [["diazepam"], ["lorazepam"]], "esperado": {"capa": "class", "clase": "N05BA"}},
  {"nombre": "dos IBP", "productos": [["omeprazol"], ["pantoprazol"]], "esperado": {"capa": "class"}},
  {"nombre": "dos ISRS", "productos": [["sertralina"], ["fluoxetina"]], "esperado": {"capa": "class", "clase": "N06AB"}},
  {"nombre": "dos anti-H2", "productos": [["ranitidina"], ["famotidina"]], "esperado": {"capa": "class"}},
  {"nombre": "IECA + ACA + tiazida (intencional)", "productos": [["enalapril"], ["amlodipino"], ["hidroclorotiazida"]], "esperado": null},
  {"nombre": "ARA II + tiazida (intencional)", "productos": [["losartan"], ["hidroclorotiazida"]], "esperado": null},
  {"nombre": "AAS + clopidogrel (doble antiagregación)", "productos": [["acido acetilsalicilico"], ["clopidogrel"]], "esperado": null}
]
```

Guardar como `tests/regression/casos_duplicidad.json`.

- [ ] **Step 2: Test parametrizado que falla**

```python
# tests/regression/test_duplicidad_casos.py
"""Casos clínicos de duplicidad contra la base real.

Es la misma lista que corre `scripts/eval_duplicidad.py` como métrica: un caso
que se rompe acá es un falso positivo o un falso negativo en producción.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.services.duplicity_checker import cumple, chequear

DB_PATH = Path(os.environ.get("INTERACTION_DB_PATH", "data/recetalia_interactions.db"))
CASOS = json.load(open(Path(__file__).parent / "casos_duplicidad.json", encoding="utf-8"))


@pytest.fixture
async def db():
    if not DB_PATH.exists():
        pytest.skip("falta la base")
    from app.clients import recetalia_db
    await recetalia_db.client.close()
    recetalia_db.client.db_path = str(DB_PATH)
    yield recetalia_db.client
    await recetalia_db.client.close()


@pytest.mark.parametrize("caso", CASOS, ids=[c["nombre"] for c in CASOS])
async def test_caso(db, caso):
    productos = [{"id": f"p{i}", "substances": s} for i, s in enumerate(caso["productos"])]
    out = await chequear(db, productos)
    assert not out["duplicity_not_evaluated"], f"no resolvieron: {out['duplicity_not_evaluated']}"
    ok, motivo = cumple(out, caso["esperado"])
    assert ok, motivo
```

- [ ] **Step 3: Correr** → FAIL (`chequear` no existe).

- [ ] **Step 4: Implementar** — al final de `app/services/duplicity_checker.py`:

```python
async def chequear(db: Any, productos: list[dict[str, Any]],
                   cupos: dict[str, Any] | None = None) -> dict[str, Any]:
    """Productos como llegan por la API → evaluación. `db` es un RecetaliaDatabase."""
    resueltos: list[Producto] = []
    for p in productos:
        subs = tuple(p["substances"])
        ids = tuple([await db.drug_id_by_name(s) for s in subs])
        resueltos.append(Producto(id=str(p["id"]), sustancias=subs, drug_ids=ids,
                                  route=p.get("route")))
    drug_ids = sorted({d for p in resueltos for d in p.drug_ids if d is not None})
    clases = await db.classes_for(drug_ids)
    canonicos = await db.canonicals_for(drug_ids)
    return evaluar(resueltos, clases, cupos or cargar_cupos(), canonicos)


def cumple(out: dict[str, Any], esperado: dict[str, Any] | None) -> tuple[bool, str]:
    """¿La evaluación da lo esperado? Lo usan el test y la métrica."""
    alertas = out["duplicities"]
    if esperado is None:
        if alertas:
            return False, f"falso positivo: {[(a['layer'], a['class_id']) for a in alertas]}"
        return True, ""
    capa = [a for a in alertas if a["layer"] == esperado["capa"]]
    if esperado.get("suprimida"):
        capa = [a for a in out["duplicities_suppressed"] if a["layer"] == esperado["capa"]]
    if not capa:
        return False, f"falso negativo: se esperaba capa {esperado['capa']}, vino {alertas}"
    if esperado.get("clase") and esperado["clase"] not in {a["class_id"] for a in capa}:
        return False, f"clase esperada {esperado['clase']}, vino {[a['class_id'] for a in capa]}"
    return True, ""
```

- [ ] **Step 5: Correr** `.venv/bin/python -m pytest tests/regression/test_duplicidad_casos.py -v`. Expected: PASS los 9. Si un caso falla:
  - `no resolvieron` → problema de nombres (Task 2), no de duplicidad: reportar el nombre.
  - falso positivo/negativo → leer `note` en `drug_class` para ese fármaco y ver qué regla lo metió. **No** agregar un cupo para taparlo sin reportarlo: es justo lo que el spec prohíbe.

- [ ] **Step 6: Commit**

```bash
git add app/services/duplicity_checker.py tests/regression/test_duplicidad_casos.py tests/regression/casos_duplicidad.json
git commit -m "duplicidad contra la base: chequear() y 9 casos clínicos de referencia"
```

---

### Task 7: Métrica `scripts/eval_duplicidad.py`

**Files:**
- Create: `scripts/eval_duplicidad.py`

- [ ] **Step 1: Implementar**

```python
#!/usr/bin/env python3
"""Métrica de duplicidad: corre los casos clínicos y dice cuántos acierta.

Es lo que corre la routine semanal: un refresco de fuentes que rompe un caso
aparece acá antes que en una receta. Sale con código 1 si falla alguno.

    .venv/bin/python scripts/eval_duplicidad.py [--json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app.clients import recetalia_db  # noqa: E402
from app.services.duplicity_checker import chequear, cumple  # noqa: E402

CASOS = os.path.join(os.path.dirname(__file__), "..", "tests", "regression",
                     "casos_duplicidad.json")


async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    casos = json.load(open(CASOS, encoding="utf-8"))
    filas = []
    for c in casos:
        prods = [{"id": f"p{i}", "substances": s} for i, s in enumerate(c["productos"])]
        out = await chequear(recetalia_db.client, prods)
        ok, motivo = cumple(out, c["esperado"])
        if out["duplicity_not_evaluated"]:
            ok, motivo = False, f"no resolvieron: {out['duplicity_not_evaluated']}"
        filas.append({"caso": c["nombre"], "ok": ok, "motivo": motivo})
    await recetalia_db.client.close()
    aciertos = sum(f["ok"] for f in filas)
    if args.json:
        print(json.dumps({"aciertos": aciertos, "total": len(filas), "casos": filas},
                         ensure_ascii=False, indent=2))
    else:
        for f in filas:
            print(("OK  " if f["ok"] else "FALLA ") + f["caso"] + (f"  — {f['motivo']}" if f["motivo"] else ""))
        print(f"\n{aciertos}/{len(filas)} casos")
    return 0 if aciertos == len(filas) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [ ] **Step 2: Correr** `.venv/bin/python scripts/eval_duplicidad.py` → `9/9 casos`, exit 0.

- [ ] **Step 3: Commit**

```bash
git add scripts/eval_duplicidad.py
git commit -m "métrica de duplicidad: casos clínicos con aciertos por caso, exit 1 si falla"
```

---

### Task 8: Contrato de `/interactions` — `products` y campos de duplicidad

**Files:**
- Modify: `app/api/schemas.py:10-13,62-70`, `app/services/interaction_checker.py:24-67`, `app/api/interactions.py:23-24`
- Test: `tests/test_interaction_checker.py` (fixture + tests), `tests/test_api.py` (un test de contrato)

- [ ] **Step 1: Tests que fallan.** En `tests/test_interaction_checker.py`, dentro de `patch_clients`, antes del `return`, agregar (para que los tests viejos no toquen la base):

```python
    dup = AsyncMock(return_value={"duplicities": [], "duplicities_suppressed": [],
                                  "duplicity_not_evaluated": [], "duplicity_warnings": []})
    monkeypatch.setattr(interaction_checker.duplicity_checker, "chequear", dup)
```

y `"duplicity": dup` en el dict devuelto. Agregar al final:

```python
async def test_sin_products_cada_nombre_es_un_producto(patch_clients):
    patch_clients["rxnorm"].side_effect = ["1", "2"]
    await interaction_checker.check(["A", "B"])
    args = patch_clients["duplicity"].call_args.args
    assert args[1] == [{"id": "A", "substances": ["A"]}, {"id": "B", "substances": ["B"]}]


async def test_products_se_pasan_y_la_respuesta_trae_duplicidad(patch_clients):
    patch_clients["rxnorm"].side_effect = ["1", "2"]
    patch_clients["duplicity"].return_value = {
        "duplicities": [{"layer": "substance"}], "duplicities_suppressed": [],
        "duplicity_not_evaluated": [], "duplicity_warnings": []}
    prods = [{"id": "p1", "substances": ["paracetamol"]},
             {"id": "p2", "substances": ["paracetamol", "codeina"]}]
    out = await interaction_checker.check(["paracetamol", "codeina"], products=prods)
    assert patch_clients["duplicity"].call_args.args[1] == prods
    assert out["duplicities"] == [{"layer": "substance"}]
    assert out["safe"] is False


async def test_si_la_duplicidad_falla_las_interacciones_salen_igual(patch_clients):
    patch_clients["rxnorm"].side_effect = ["1", "2"]
    patch_clients["duplicity"].side_effect = RuntimeError("boom")
    out = await interaction_checker.check(["A", "B"])
    assert out["duplicities"] == [] and out["duplicity_warnings"]
```

- [ ] **Step 2: Correr** `.venv/bin/python -m pytest tests/test_interaction_checker.py -q` → FAIL.

- [ ] **Step 3: Schemas.** En `app/api/schemas.py` reemplazar `InteractionsRequest` por:

```python
class ProductIn(BaseModel):
    """Un producto recetado y sus sustancias. Sin esto un combinado llega
    desarmado y la misma sustancia en dos productos es invisible."""
    id: Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)]
    substances: list[Annotated[str, StringConstraints(min_length=1, max_length=200,
                                                      strip_whitespace=True)]] = Field(
        ..., min_length=1, max_length=20)
    # Aceptada desde ya; la regla tópico/sistémico se escribe cuando Recetalia la mande.
    route: str | None = Field(None, max_length=50)


class InteractionsRequest(BaseModel):
    drugs: list[Annotated[str, StringConstraints(min_length=1, max_length=200,
                                                 strip_whitespace=True)]] = Field(
        default_factory=list, examples=[["ibuprofen", "warfarin"]])
    products: list[ProductIn] | None = Field(None, max_length=50)

    @model_validator(mode="after")
    def _al_menos_dos(self):
        # Compatible hacia atrás: sin `products`, `drugs` sigue exigiendo 2.
        if self.products:
            if not self.drugs:
                vistos: list[str] = []
                for p in self.products:
                    vistos += [s for s in p.substances if s not in vistos]
                self.drugs = vistos
            if len(self.products) < 2 and len(self.drugs) < 2:
                raise ValueError("hacen falta al menos dos productos o dos sustancias")
        elif len(self.drugs) < 2:
            raise ValueError("drugs necesita al menos dos elementos")
        return self
```

Agregar `model_validator` al import de pydantic. En `InteractionsResponse` agregar, después de `coverage_summary`:

```python
    """Duplicidad terapéutica. Ver docs/2026-09-24-duplicidad-terapeutica-design.md."""
    duplicities: list[dict] = Field(default_factory=list)
    """Lo que NO se alertó por un cupo o una excepción, con el motivo."""
    duplicities_suppressed: list[dict] = Field(default_factory=list)
    duplicity_not_evaluated: list[str] = Field(default_factory=list)
    duplicity_warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Checker.** En `app/services/interaction_checker.py`: agregar `duplicity_checker` al import de `app.services` (`from app.services import duplicity_checker`), y reemplazar `check` por:

```python
async def check(drug_names: list[str],
                products: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Interacciones por par + duplicidad terapéutica por producto."""
    if products is None:
        # Sin agrupación, cada nombre es un producto: la capa de sustancia no
        # puede ver un combinado, pero la de clase sí funciona.
        products = [{"id": n, "substances": [n]} for n in drug_names]
    dup = await _duplicidad(products)

    if len(drug_names) < 2:
        return {
            "interactions": [],
            "safe": not dup["duplicities"],
            "error": None,
            "coverage_summary": dict(_EMPTY_COVERAGE),
            **dup,
        }
```

y al final de la función cambiar el `return` por:

```python
    return {
        "interactions": interactions,
        "safe": len(interactions) == 0 and not dup["duplicities"],
        "error": None,
        "coverage_summary": coverage,
        **dup,
    }


async def _duplicidad(products: list[dict[str, Any]]) -> dict[str, Any]:
    vacio = {"duplicities": [], "duplicities_suppressed": [],
             "duplicity_not_evaluated": [], "duplicity_warnings": []}
    if len(products) < 2:
        return vacio
    try:
        return await duplicity_checker.chequear(recetalia_db.client, products)
    except Exception:
        # Que falle la duplicidad no puede tumbar las interacciones; se dice.
        logger.warning("Chequeo de duplicidad falló", exc_info=True)
        return {**vacio, "duplicity_warnings": [
            "No se pudo evaluar la duplicidad terapéutica en esta consulta."]}
```

- [ ] **Step 5: Endpoint.** En `app/api/interactions.py:24`:

```python
    result = await interaction_checker.check(
        body.drugs,
        products=[p.model_dump() for p in body.products] if body.products else None)
```

- [ ] **Step 6: Test de contrato del endpoint.** Buscar en `tests/test_api.py` cómo se llama a `/interactions` (cliente y mock de `interaction_checker.check`) y agregar, con el mismo patrón:
  - un POST con sólo `products` (dos productos) → 200, y el mock recibió `products` con los dos ids;
  - un POST con `{"drugs": ["a"]}` → 422 (el mínimo de 2 sigue vigente).

- [ ] **Step 7: Correr la suite entera** `.venv/bin/python -m pytest -q` → todo PASS.

- [ ] **Step 8: Commit**

```bash
git add app/api/schemas.py app/services/interaction_checker.py app/api/interactions.py tests/test_interaction_checker.py tests/test_api.py
git commit -m "/interactions acepta products y devuelve duplicidad (compatible hacia atrás)"
```

---

### Task 9: UI — tarjeta de duplicidad

**Files:**
- Modify: `app/web/app.js` (`construirFiltros` `:587`, `render` `:704-727`, portapapeles `:929`; nueva `cardDuplicidad` después de `cardInteraccion` `:854`)

- [ ] **Step 1: `construirFiltros`.** Cambiar la primera línea para que las duplicidades cuenten en los filtros:

```js
  const hallazgos = [
    ...(inter?.interactions || []),
    ...(inter?.duplicities || []),
  ];
```

- [ ] **Step 2: `render`, columna 1.** Después de `html += found.map(cardInteraccion).join("");` agregar:

```js
    const dups = (inter.duplicities || []).filter((d) =>
      pasaFiltroPaciente([d.class_desc, ...(d.substances || [])], d.severity, d.source));
    ocultos += (inter.duplicities || []).length - dups.length;
    html += dups.map((d) => cardDuplicidad(d, false)).join("");
    // Lo suprimido se muestra plegado: se evaluó y se decidió no alertar.
    const sup = inter.duplicities_suppressed || [];
    if (sup.length && !hayFiltro()) {
      html += `<details class="suprimidas"><summary>${sup.length}
        ${sup.length === 1 ? "duplicidad no alertada" : "duplicidades no alertadas"}
        por una excepción curada</summary>${sup.map((d) => cardDuplicidad(d, true)).join("")}</details>`;
    }
    if (!hayFiltro()) {
      (inter.duplicity_not_evaluated || []).forEach((n) => {
        html += `<div class="empty-state"><strong>${escapeHtml(n)}</strong> no se pudo
          identificar, así que no se evaluó su duplicidad.</div>`;
      });
      (inter.duplicity_warnings || []).forEach((w) => {
        html += `<div class="aviso-perfil">${escapeHtml(w)}</div>`;
      });
    }
```

- [ ] **Step 3: `cardDuplicidad`**, después de `cardInteraccion`:

```js
/* Duplicidad terapéutica. Dice qué regla la disparó —misma sustancia o clase de
   la AEMPS— y, si se suprimió, por qué: la procedencia es lo que VIDAL no da. */
function cardDuplicidad(d, suprimida) {
  const sev = suprimida ? "minor" : (SEV[d.severity] ? d.severity : "moderate");
  const titulo = d.layer === "substance"
    ? "Misma sustancia en dos productos"
    : `Duplicidad de clase: ${escapeHtml(d.class_desc || d.class_id)}`;
  const detalle = d.layer === "substance"
    ? `${escapeHtml(d.substances.map(mostrar).join(", "))} aparece en ${d.count} productos distintos.`
    : `${d.count} productos de la misma clase (${escapeHtml(d.substances.map(mostrar).join(", "))});
       el máximo sin alerta es ${d.cupo}.`;
  return `
    <article class="finding ${sev}">
      <div class="finding-head">
        <span class="pair">${titulo}</span>
        <span class="badge ${sev}">${suprimida ? "No alertada" : "Duplicidad"}</span>
      </div>
      <p class="evidence">${detalle}</p>
      ${suprimida ? `<p class="manejo"><strong>Por qué no se alertó:</strong>
          ${escapeHtml(d.motivo || "")}${d.referencia ? ` (${escapeHtml(d.referencia)})` : ""}
          ${d.validado ? "" : " — excepción pendiente de validación farmacéutica."}</p>` : ""}
      <p class="meta">${d.layer === "substance" ? "Regla propia de Consilio"
        : `${FUENTE.aemps} — grupo ${escapeHtml(d.class_id)}`}</p>
    </article>`;
}
```

- [ ] **Step 4: Portapapeles.** Después del `forEach` de `inter?.interactions` (`:934`):

```js
  (inter?.duplicities || []).forEach((d) => {
    L.push(`[DUPLICIDAD] ${d.layer === "substance" ? "misma sustancia" : d.class_desc}: ` +
           d.substances.map(mostrar).join(", "));
  });
```

- [ ] **Step 5: Verificar en el navegador** (delegar la parte de Chrome a un subagente, regla del CLAUDE.md global). Levantar:
  `API_KEY=test-local CONSILIO_SEARCH_RATE=3000/minute nohup .venv/bin/python -m uvicorn app.main:app --port 8101 --log-level warning &`
  En http://localhost:8101/ui/index.html (key en localStorage `consilio_api_key=test-local`): diazepam + lorazepam → tarjeta "Duplicidad de clase"; enalapril + amlodipino + hidroclorotiazida → ninguna tarjeta de duplicidad; los filtros de gravedad cuentan la duplicidad. Matar el server: `kill $(pgrep -f "uvicorn app.main:app --port 8101")`.

- [ ] **Step 6: Commit**

```bash
git add app/web/app.js
git commit -m "UI: tarjeta de duplicidad con procedencia, supresiones plegadas y no evaluados"
```

---

### Task 10: README — orden del ETL

- [ ] **Step 1:** En `README.md`, en la lista del orden del ETL (líneas ~75-84), agregar al final los pasos que faltan, en este orden: `fetch_drug_atc.py`, `fetch_mesh_tree.py`, `build_condition_xref.py`, `cross_aemps_interactions.py`, `cross_aemps_geriatria.py`, `cross_aemps_duplicidad.py` (los tres últimos con `PYTHONPATH=scripts`), y una línea: "Métrica de duplicidad: `.venv/bin/python scripts/eval_duplicidad.py`".
- [ ] **Step 2: Commit** `git commit -am "README: orden completo del ETL y métrica de duplicidad"`

---

### Task 11: Recetalia — mandar productos y mapear duplicidades

Repo: `recetalia-api-rest`, rama `feat/consilio-interacciones` (**no** mergear: regla del workspace). El checkout principal está en otra rama → usar worktree:

```bash
cd ../recetalia-api-rest
git worktree add ../recetalia-api-rest-consilio feat/consilio-interacciones
cd ../recetalia-api-rest-consilio
```

Paquete base: `src/main/java/com/recetalia/api/application` (abreviado `…`).

**Files:**
- Create: `…/infrastructure/adapter/consilio/dto/ConsilioProduct.java`, `…/infrastructure/adapter/consilio/dto/ConsilioDuplicity.java`
- Modify: `…/dto/ConsilioInteractionsRequest.java`, `…/dto/ConsilioInteractionsResponse.java`, `…/ConsilioPort.java`, `…/impl/ConsilioPortImpl.java`, `…/dto/response/DrugInteractionCheckResponse.java`, `…/service/impl/DrugInteractionServiceImpl.java`
- Test: `src/test/java/…/service/DrugInteractionServiceImplTest.java`

- [ ] **Step 1: Tests que fallan** en `DrugInteractionServiceImplTest` (seguir el armado de mocks que ya usa el archivo para `dnmaDatabaseService` y `consilioPort`; el puerto pasa a recibir `List<ConsilioProduct>`):
  1. `laMismaSustanciaEnDosProductosVaComoDuplicidad`: productos AMP:1 (`PARACETAMOL`) y AMP:2 (`PARACETAMOL + CODEINA`); el mock del puerto devuelve una `ConsilioDuplicity` con `layer="substance"`, `products=["AMP:1","AMP:2"]`. Esperado: `out.getDuplicidades()` tiene 1, con `productos` = refs de AMP:1 y AMP:2 y `capa="substance"`; y el puerto recibió dos `ConsilioProduct` con ids `AMP:1`/`AMP:2` y sustancias `[PARACETAMOL]` / `[PARACETAMOL, CODEINA]`.
  2. `unaInteraccionConSustanciaRepetidaSeReportaParaCadaProducto`: AMP:1 (`WARFARINA`), AMP:2 (`IBUPROFENO`), AMP:3 (`IBUPROFENO + X`); Consilio devuelve warfarina–ibuprofeno. Esperado: **2** hallazgos (1–2 y 1–3). Hoy sale 1 por el `putIfAbsent`.

Run: `./mvnw -q test -Dtest=DrugInteractionServiceImplTest` → FAIL (no compila).

- [ ] **Step 2: DTOs**

```java
// ConsilioProduct.java
package com.recetalia.api.application.infrastructure.adapter.consilio.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/** Un producto recetado y sus sustancias: sin la agrupación, Consilio no ve
 *  la misma sustancia en dos productos (paracetamol solo + en combinado). */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
@Data
@NoArgsConstructor
@AllArgsConstructor
public class ConsilioProduct {
    private String id;
    private List<String> substances;
}
```

```java
// ConsilioDuplicity.java
package com.recetalia.api.application.infrastructure.adapter.consilio.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.Data;

import java.util.List;

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
@JsonIgnoreProperties(ignoreUnknown = true)
@Data
public class ConsilioDuplicity {
    private String layer;          // substance | class
    private String classId;
    private String classDesc;
    private List<String> products; // ids que mandamos: "AMP:123"
    private List<String> substances;
    private Integer count;
    private Integer cupo;
    private String severity;
    private String source;
    private String motivo;         // sólo en las suprimidas
    private String referencia;
}
```

`ConsilioInteractionsRequest`: reemplazar el campo por `private List<ConsilioProduct> products;` (javadoc: "Productos con sus sustancias. Consilio deriva los nombres y arma los pares."). `ConsilioInteractionsResponse`: agregar `private List<ConsilioDuplicity> duplicities;` y `private List<ConsilioDuplicity> duplicitiesSuppressed;`.

- [ ] **Step 3: Puerto.** `ConsilioPort.check(List<ConsilioProduct> products)`. En `ConsilioPortImpl`: la guarda pasa a `if (products == null || products.isEmpty()) return Optional.empty();` y la entidad a `new ConsilioInteractionsRequest(products)`.

- [ ] **Step 4: Respuesta Recetalia.** En `DrugInteractionCheckResponse` agregar:

```java
    private List<Duplicidad> duplicidades = new ArrayList<>();
    /** Evaluadas y no alertadas por una excepción curada, con el motivo. */
    private List<Duplicidad> duplicidadesNoAlertadas = new ArrayList<>();

    @Data
    public static class Duplicidad {
        private String capa;            // substance | class
        private String clase;
        private String claseDescripcion;
        private List<ProductoRef> productos;
        private List<String> sustancias;
        private String severidad;
        private String fuente;
        private String motivo;
        private String referencia;
    }
```

- [ ] **Step 5: Servicio.** En `DrugInteractionServiceImpl.check`:
  - reemplazar `Map<String, String> productByName` + `putIfAbsent` por `Map<String, List<String>> productsByName` (`computeIfAbsent(lower, k -> new ArrayList<>()).add(key)`, sin repetir key);
  - armar `List<ConsilioProduct> toSend` con `new ConsilioProduct(key, subs)` por cada producto resuelto; la guarda `names.size() < 2` pasa a `toSend.size() < 2 && names.size() < 2`;
  - `consilioPort.check(toSend)`;
  - el mapeo de hallazgos itera `for keyA : productsByName(A)` × `for keyB : productsByName(B)`, saltea `keyA.equals(keyB)`, y no repite el par (usar un `Set<String>` con `keyA + "|" + keyB` ordenado);
  - después, mapear `duplicities` y `duplicitiesSuppressed` con:

```java
    private DrugInteractionCheckResponse.Duplicidad toDuplicidad(
            ConsilioDuplicity d, Map<String, DrugInteractionCheckRequest.Producto> productByKey) {
        DrugInteractionCheckResponse.Duplicidad out = new DrugInteractionCheckResponse.Duplicidad();
        out.setCapa(d.getLayer());
        out.setClase(d.getClassId());
        out.setClaseDescripcion(d.getClassDesc());
        List<DrugInteractionCheckResponse.ProductoRef> refs = new ArrayList<>();
        for (String key : d.getProducts() == null ? List.<String>of() : d.getProducts()) {
            refs.add(ref(productByKey.get(key), null));
        }
        out.setProductos(refs);
        out.setSustancias(d.getSustancias());
        out.setSeveridad(d.getSeverity());
        out.setFuente(d.getSource());
        out.setMotivo(d.getMotivo());
        out.setReferencia(d.getReferencia());
        return out;
    }
```

  (ojo: el getter del DTO es `getSubstances()`; corregir `d.getSustancias()` → `d.getSubstances()` al pegar).

- [ ] **Step 6: Correr** `./mvnw -q test -Dtest='DrugInteractionServiceImplTest,ConsilioContractTest'` → PASS. Si `ConsilioContractTest` usa un payload grabado, agregarle `duplicities` con un elemento y verificar que deserializa (snake_case: la lección del javadoc de `ConsilioInteractionsResponse`).

- [ ] **Step 7: Suite** `./mvnw -q test` → sin fallas nuevas respecto de la rama (anotar las que ya fallaban antes, si las hay).

- [ ] **Step 8: Commit + push de la rama** (push de rama de trabajo, sin merge)

```bash
git add -A src
git commit -m "Consilio: mandar productos agrupados, mapear duplicidades, no perder productos con sustancia repetida"
git push origin feat/consilio-interacciones
```

---

### Task 12: Deploy al `.98` y verificación

Server: `ssh root@138.197.150.98`, directorio `/opt/recetalia/consilio/`. **El nginx no tiene curl ni wget**: probar desde `mi-landing` con node.

- [ ] **Step 1: Suite local verde** `.venv/bin/python -m pytest -q` y `scripts/eval_duplicidad.py` → 9/9.
- [ ] **Step 2: Push de la rama** `git push -u origin feat/duplicidad`.
- [ ] **Step 3: Actualizar el código en el server.** Ver cómo llegó el código la vez anterior (`ssh root@138.197.150.98 'cd /opt/recetalia/consilio && git status -sb 2>&1 | head -3; ls'`). Si es un clon git: `git fetch && git checkout feat/duplicidad && git pull`. Si no: `rsync -az --exclude .venv --exclude data --exclude .git ./ root@138.197.150.98:/opt/recetalia/consilio/` (**sin** `--delete`: ver memoria "gotchas del deploy al .98").
- [ ] **Step 4: Base y cupos.** `rsync -az data/recetalia_interactions.db data/duplicidad_cupos.json root@138.197.150.98:/opt/recetalia/consilio/data/` — antes, `ssh … 'cp data/recetalia_interactions.db data/recetalia_interactions.db.bak-2026-09-24'` y `df -h /` (disco al 85%: si pasa de 90%, parar y avisar).
- [ ] **Step 5: Rebuild** `ssh root@138.197.150.98 'cd /opt/recetalia/consilio && docker compose -f deploy/docker-compose.98.yml up -d --build'` (confirmar el nombre del compose con `ls deploy/` en el server; la vez anterior fue `docker compose up -d --build` desde ese directorio). La base se abre `immutable=1`: el restart es obligatorio.
- [ ] **Step 6: Verificar**

```bash
ssh root@138.197.150.98 'docker exec mi-landing node -e "
fetch(\"http://consilio:8000/interactions\",{method:\"POST\",headers:{\"Content-Type\":\"application/json\",\"X-API-Key\":process.argv[1]},
body:JSON.stringify({products:[{id:\"p1\",substances:[\"diazepam\"]},{id:\"p2\",substances:[\"lorazepam\"]}]})})
.then(r=>r.json()).then(j=>console.log(JSON.stringify(j.duplicities)))" "$(grep ^API_KEY /opt/recetalia/consilio/deploy/.env | cut -d= -f2)"'
```

Expected: una duplicidad `layer: "class"`, `class_id: "N05BA"`. Repetir con enalapril/amlodipino/hidroclorotiazida → `[]`. Y `/health` ok.

- [ ] **Step 7: Registrar** en el spec (sección nueva "Despliegue") la fecha, el commit desplegado y las dos respuestas verificadas; commit + push.
