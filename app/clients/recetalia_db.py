"""Cliente async del SQLite de Recetalia.

Reemplaza a `ddinter_db`, que leía la base cruda de DDInter. Ésta es nuestra:
además de los 160.235 pares heredados trae los derivados de openFDA, las
alertas fármaco-patología de MED-RT y el mapeo de sustancias del DNMA.

## Precedencia por procedencia

Ante dos filas para el mismo hecho gana la de mayor autoridad:

    recetalia  >  aemps  >  ddinter  >  openfda

`recetalia` es lo que revisó un farmacéutico y pisa a todo lo importado.
`aemps` es un regulador y es el único que trae mecanismo y manejo escritos.
`ddinter` trae severidad estructurada de una base curada. `openfda` es una
inferencia sobre texto libre de prospecto: sirve donde no hay nada mejor, pero
no compite con las otras.

Esa precedencia es SQL, no convención: vive en `_PRECEDENCE` y se aplica en
cada búsqueda de par.

## La gravedad NO sale de la precedencia

Es la única excepción, y está medida. De los 741 pares donde la AEMPS coincide
con una fuente previa, **215 los tiene DDInter como `major` y la AEMPS como
`desaconsejada`**, y al revés **29 los contraindica la AEMPS y DDInter los deja
en `moderate` o menos**. O sea que cualquiera de los dos órdenes se equivoca en
cientos de pares, y en la dirección peligrosa: avisar de menos.

Por eso la gravedad se resuelve aparte —**se toma la más alta y se dice quién
la dijo** (`severity_source`)— mientras el resto de la fila (texto, evidencia)
sigue saliendo de la precedencia. Bajar una contraindicación de un regulador a
"moderada" porque otra fuente opina distinto no es resolver un conflicto: es
esconderlo.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiosqlite

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "recetalia_interactions.db")
DB_PATH = os.environ.get("INTERACTION_DB_PATH", DEFAULT_DB_PATH)

# Menor número = más autoridad. Se usa como ORDER BY.
# La columna va calificada: `drug` también tiene `source`, y sin el prefijo el
# JOIN de lookup_pair falla con "ambiguous column name".
_PRECEDENCE = ("case i.source when 'recetalia' then 0 when 'aemps' then 1 "
               "when 'ddinter' then 2 else 3 end")

# Para elegir la gravedad más alta entre fuentes que no coinciden.
_SEVERITY_RANK = {"major": 3, "moderate": 2, "minor": 1, "unknown": 0}

_SALTS = (
    "potasico", "sodico", "calcico", "magnesico", "clorhidrato", "hidrocloruro",
    "bromhidrato", "sulfato", "maleato", "tartrato", "bitartrato", "succinato",
    "fumarato", "mesilato", "besilato", "acetato", "propionato", "valerato",
    "dipropionato", "furoato", "palmitato", "estearato", "estolato", "fosfato",
    "nitrato", "bromuro", "cloruro", "yoduro", "citrato", "trometamina",
    "gluconato", "lactato", "malato", "oxalato", "pamoato", "salicilato",
    "carbonato", "monosodico", "disodico", "dihidratado", "monohidrato",
    "anhidro", "micronizado",
)
_SALT_RE = re.compile(rf"\b(?:{'|'.join(_SALTS)})\b")


def normalize(name: str) -> str:
    """Misma normalización que usa el ETL al escribir `drug_alias.alias_norm`.

    Si las dos divergen, las búsquedas por nombre dejan de encontrar nada, así
    que cualquier cambio acá tiene que replicarse en `build_recetalia_db._norm`.
    """
    s = unicodedata.normalize("NFKD", name.lower()).encode("ascii", "ignore").decode()
    s = re.sub(r"\(.*?\)", " ", s)
    s = _SALT_RE.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _titulo(s: str | None) -> str | None:
    """Los nombres del DNMA vienen en mayúsculas y los manuales en minúscula.

    Se normaliza a capitalización de oración para que la lista no parezca un
    grito intercalado con susurros.
    """
    if not s:
        return None
    s = s.strip()
    return s[0].upper() + s[1:].lower() if s.isupper() or s.islower() else s


def _like(s: str) -> str:
    """Escapa los comodines de LIKE para que un `%` tecleado no matchee todo."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _readonly_immutable_uri(db_path: str) -> str:
    """URI de sólo lectura e inmutable.

    ⚠️ `immutable=1` le dice a SQLite que el archivo no cambia, así que saltea
    el bloqueo y cachea agresivamente. Eso lo hace rápido, pero significa que
    **un cambio del ETL no se ve hasta reiniciar el servicio**. Es el precio de
    tratar a la base como un artefacto de build, que es lo que es.
    """
    absolute = Path(db_path).resolve()
    return f"file:{quote(str(absolute), safe='/')}?mode=ro&immutable=1"


class RecetaliaDatabase:
    """Handle async de sólo lectura. Un proceso, una conexión."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._conn is not None:
            return
        async with self._lock:
            if self._conn is not None:
                return
            if not os.path.exists(self.db_path):
                logger.error("Base de interacciones no encontrada en %s", self.db_path)
                raise FileNotFoundError(f"Base de interacciones no encontrada: {self.db_path}")
            conn = await aiosqlite.connect(_readonly_immutable_uri(self.db_path), uri=True)
            conn.row_factory = aiosqlite.Row
            self._conn = conn
            logger.info("Conectado al SQLite de Recetalia en %s", self.db_path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _c(self) -> aiosqlite.Connection:
        if self._conn is None:
            await self.connect()
        assert self._conn is not None
        return self._conn

    async def health_check(self) -> bool:
        try:
            conn = await self._c()
            async with conn.execute("select count(*) from interaction limit 1") as cur:
                await cur.fetchone()
            return True
        except Exception as exc:
            logger.warning("Health check de la base falló: %s", exc)
            if self._conn is not None:
                try:
                    await self._conn.close()
                except Exception:
                    pass
                self._conn = None
            return False

    async def stats(self) -> dict[str, int]:
        conn = await self._c()
        out: dict[str, int] = {}
        for label, sql in (
            ("drugs", "select count(*) from drug"),
            ("interactions", "select count(*) from interaction"),
            ("conditions", "select count(*) from condition"),
            ("drug_condition_alerts", "select count(*) from drug_condition_alert"),
        ):
            async with conn.execute(sql) as cur:
                row = await cur.fetchone()
            out[label] = row[0] if row else 0
        return out

    # --- resolución de fármacos -------------------------------------------

    async def drug_ids_by_rxcui(self, rxcuis: list[str]) -> dict[str, int]:
        rxcuis = [r for r in rxcuis if r]
        if not rxcuis:
            return {}
        conn = await self._c()
        ph = ",".join("?" * len(rxcuis))
        async with conn.execute(
            f"select rxcui, drug_id from drug where rxcui in ({ph})", tuple(rxcuis)
        ) as cur:
            rows = await cur.fetchall()
        return {r["rxcui"]: r["drug_id"] for r in rows}

    async def drug_id_by_name(self, name: str) -> int | None:
        conn = await self._c()
        async with conn.execute(
            "select drug_id from drug_alias where alias_norm = ? limit 1",
            (normalize(name),),
        ) as cur:
            row = await cur.fetchone()
        return row["drug_id"] if row else None

    async def search_drugs(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Busca fármacos por prefijo de alias, para el autocompletado.

        Ordena por si el alias empieza con lo tecleado antes que por si sólo lo
        contiene: quien escribe "war" espera warfarina primero, no
        clorhidrato de algo-war.
        """
        q = normalize(query)
        if len(q) < 2:
            return []
        conn = await self._c()
        # `name_es` es para MOSTRAR: el canónico está en inglés y esta interfaz
        # es para un médico uruguayo. Sale del alias castellano si lo hay y si
        # no del mapa del DNMA, que trae la grafía del vademécum local —que es
        # justamente la que el médico espera leer—. Se queda en NULL cuando no
        # sabemos: inventar una traducción de un fármaco es peor que el inglés.
        async with conn.execute(
            """select distinct d.drug_id, d.canonical, d.rxcui,
                      coalesce(
                        (select es.alias from drug_alias es
                          where es.drug_id = d.drug_id and es.lang = 'es' limit 1),
                        (select m.sustancia_dsc from dnma_substance_map m
                          where m.drug_id = d.drug_id limit 1)
                      ) as name_es
               from drug_alias a
               join drug d on d.drug_id = a.drug_id
               where a.alias_norm like ? escape '\\'
               order by case when a.alias_norm like ? escape '\\' then 0 else 1 end,
                        length(d.canonical), d.canonical
               limit ?""",
            (f"%{_like(q)}%", f"{_like(q)}%", limit),
        ) as cur:
            rows = await cur.fetchall()
        return [{"drug_id": r["drug_id"], "name": r["canonical"], "rxcui": r["rxcui"],
                 "name_es": _titulo(r["name_es"])} for r in rows]

    async def search_conditions(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Busca patologías por código CIE-10 o por nombre, para el autocompletado.

        Devuelve sólo los **anclajes** del puente: los 552 códigos a los que hay
        alguna alerta colgada. Ofrecerle al médico un catálogo de 70.000 códigos
        de los cuales 69.500 no disparan nada sería prometer una evaluación que
        no existe.

        El médico puede igual escribir un código más específico que el anclaje
        (`N18.5` contra `N18`): eso lo resuelve `condition_ids_for_icd10` por
        truncación. Acá se le muestra dónde va a caer.
        """
        q = query.strip()
        if len(q) < 2:
            return []
        conn = await self._c()
        code_q = q.upper().replace(" ", "")
        async with conn.execute(
            """select c.condition_id, c.code, c.name,
                      (select count(*) from condition_xref x
                        join drug_condition_alert a on a.condition_id = x.to_id
                       where x.from_id = c.condition_id) as alertas
               from condition c
               where c.code_system like 'icd10%'
                 and (c.code like ? escape '\\' or c.name like ? escape '\\')
               order by case when c.code like ? escape '\\' then 0 else 1 end,
                        alertas desc, c.code
               limit ?""",
            (f"{_like(code_q)}%", f"%{_like(q)}%", f"{_like(code_q)}%", limit),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def drug_id_by_dnma(self, sustancia_id: str) -> int | None:
        conn = await self._c()
        async with conn.execute(
            "select drug_id from dnma_substance_map where sustancia_id = ?",
            (sustancia_id,),
        ) as cur:
            row = await cur.fetchone()
        return row["drug_id"] if row else None

    async def drug_name(self, drug_id: int) -> str | None:
        conn = await self._c()
        async with conn.execute(
            "select canonical from drug where drug_id = ?", (drug_id,)) as cur:
            row = await cur.fetchone()
        return row["canonical"] if row else None

    # --- interacciones ----------------------------------------------------

    async def lookup_pair(self, drug_a: int, drug_b: int) -> dict[str, Any] | None:
        """El mejor hecho conocido para el par.

        Se traen TODAS las filas del par —son pocas, una por fuente— porque hay
        tres decisiones distintas y no se resuelven igual:

        * la **fila base** (evidencia, procedencia) sale de `_PRECEDENCE`;
        * la **gravedad**, de la más alta entre fuentes (ver el docstring del
          módulo: la precedencia acá avisaría de menos);
        * el **texto** de mecanismo y manejo, del primero que lo tenga — hoy
          casi siempre la AEMPS, que es la única fuente que lo trae escrito.

        Cuando una de las tres no coincide con la fila base se dice de dónde
        salió, en vez de presentarlas como si fueran todas de la misma fuente.
        """
        if drug_a == drug_b:
            return None
        lo, hi = (drug_a, drug_b) if drug_a < drug_b else (drug_b, drug_a)
        conn = await self._c()
        async with conn.execute(
            f"""select i.severity, i.mechanism, i.management, i.evidence, i.source,
                       i.reviewed_by, i.note, a.canonical as name_a, b.canonical as name_b
                from interaction i
                join drug a on a.drug_id = i.drug_a_id
                join drug b on b.drug_id = i.drug_b_id
                where i.drug_a_id = ? and i.drug_b_id = ?
                order by {_PRECEDENCE}""",
            (lo, hi),
        ) as cur:
            rows = await cur.fetchall()
        if not rows:
            return None

        base = rows[0]
        peor = max(rows, key=lambda r: _SEVERITY_RANK.get(
            (r["severity"] or "unknown").lower(), 0))
        con_texto = next((r for r in rows if r["mechanism"] or r["management"]), None)

        out = {
            "severity": (peor["severity"] or "unknown").lower(),
            "mechanism": con_texto["mechanism"] if con_texto else None,
            "management": con_texto["management"] if con_texto else None,
            "evidence": base["evidence"],
            "source": base["source"],
            "reviewed_by": base["reviewed_by"],
            "drug_a_name": base["name_a"],
            "drug_b_name": base["name_b"],
            # openFDA es inferencia sobre texto libre; las otras no.
            "uncertain": base["source"] == "openfda",
        }
        if peor["source"] != base["source"]:
            out["severity_source"] = peor["source"]
        if con_texto is not None and con_texto["source"] != base["source"]:
            out["text_source"] = con_texto["source"]
        # Una regla de la AEMPS puede haber matcheado por clase y no por
        # molécula. Es menos específica, y el médico tiene derecho a saberlo.
        if con_texto is not None and con_texto["note"]:
            out["text_match"] = con_texto["note"]
        return out

    async def lookup_by_rxcui(self, rxcui_a: str, rxcui_b: str) -> dict[str, Any] | None:
        ids = await self.drug_ids_by_rxcui([rxcui_a, rxcui_b])
        a, b = ids.get(rxcui_a), ids.get(rxcui_b)
        return await self.lookup_pair(a, b) if a and b else None

    async def lookup_by_name(self, name_a: str, name_b: str) -> dict[str, Any] | None:
        a = await self.drug_id_by_name(name_a)
        b = await self.drug_id_by_name(name_b)
        return await self.lookup_pair(a, b) if a and b else None

    # --- alertas fármaco-paciente -----------------------------------------

    async def population_alerts_for(
        self, drug_ids: list[int], population: str = "elderly"
    ) -> list[dict[str, Any]]:
        """Alertas que dependen de a qué población pertenece el paciente.

        Van ordenadas con las no condicionadas primero: son las únicas que el
        motor puede afirmar. El resto sale como "verificar si…" porque la
        situación que las dispara —una comorbilidad, un valor de laboratorio—
        no está en la receta.
        """
        if not drug_ids:
            return []
        conn = await self._c()
        ph = ",".join("?" * len(drug_ids))
        async with conn.execute(
            f"""select d.canonical as drug, p.situacion, p.recomendacion,
                       p.condicionada, p.source, p.note
                from drug_population_alert p
                join drug d on d.drug_id = p.drug_id
                where p.drug_id in ({ph}) and p.population = ?
                order by p.condicionada, d.canonical""",
            (*drug_ids, population),
        ) as cur:
            rows = await cur.fetchall()
        return [{**dict(r), "condicionada": bool(r["condicionada"])} for r in rows]

    async def classes_for(
        self, drug_ids: list[int]
    ) -> dict[int, list[tuple[str, str, str]]] | None:
        """Clases de duplicidad por fármaco: (class_id, class_desc, rol).

        `None` si la tabla no existe. `None` y `{}` no son lo mismo: el primero
        es "no se evaluó" (ETL sin correr) y el llamador lo tiene que decir; el
        segundo es "se evaluó y ningún fármaco tiene clase".
        """
        if not drug_ids:
            return {}
        conn = await self._c()
        ph = ",".join("?" * len(drug_ids))
        try:
            async with conn.execute(
                f"select drug_id, class_id, class_desc, rol from drug_class "
                f"where drug_id in ({ph}) order by class_id", tuple(drug_ids)
            ) as cur:
                rows = await cur.fetchall()
        except aiosqlite.OperationalError:
            return None
        out: dict[int, list[tuple[str, str, str]]] = {}
        for r in rows:
            out.setdefault(r["drug_id"], []).append(
                (r["class_id"], r["class_desc"], r["rol"]))
        return out

    async def alerts_for(
        self, drug_ids: list[int], condition_ids: list[int]
    ) -> list[dict[str, Any]]:
        if not drug_ids or not condition_ids:
            return []
        conn = await self._c()
        dph = ",".join("?" * len(drug_ids))
        cph = ",".join("?" * len(condition_ids))
        async with conn.execute(
            f"""select d.canonical as drug, c.code_system, c.code, c.name as condition,
                       al.kind, al.rela, al.detail, al.source
                from drug_condition_alert al
                join drug d on d.drug_id = al.drug_id
                join condition c on c.condition_id = al.condition_id
                where al.drug_id in ({dph}) and al.condition_id in ({cph})
                order by case al.kind when 'contraindication' then 0 else 1 end,
                         d.canonical""",
            (*drug_ids, *condition_ids),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def condition_ids_for_icd10(self, codes: list[str]) -> dict[str, list[int]]:
        """Códigos CIE-10 del paciente → condiciones MeSH que activan.

        Los anclajes del puente vienen en tres formas —código exacto (`E86.9`),
        categoría (`N18`) y rango (`K70-K77`)— y hay que resolver las tres. Si
        sólo se buscara igualdad, un paciente con `N18.5` no dispararía la
        alerta anclada en `N18`: es el caso más grave de insuficiencia renal y
        se quedaría sin aviso.

        Todo local. El puente ya está construido en `condition_xref`; acá sólo
        se consulta.
        """
        if not codes:
            return {}
        conn = await self._c()
        out: dict[str, list[int]] = {}

        for raw in codes:
            code = (raw or "").strip().upper().replace(" ", "")
            if not code:
                continue
            # Candidatos: el código y todos sus ancestros por truncación.
            # N18.5 -> N18.5, N18, N1  (el punto no cuenta como nivel)
            plain = code.replace(".", "")
            candidates = {code, plain}
            for n in range(len(plain) - 1, 2, -1):
                candidates.add(plain[:n])
                if n > 3:
                    candidates.add(plain[:3] + "." + plain[3:n])
            ph = ",".join("?" * len(candidates))
            async with conn.execute(
                f"""select distinct x.to_id
                     from condition c join condition_xref x on x.from_id = c.condition_id
                    where c.code_system='icd10cm' and c.code in ({ph})""",
                tuple(candidates),
            ) as cur:
                hits = {r["to_id"] for r in await cur.fetchall()}

            # Rangos: 'K70-K77' cubre K70..K77. Se comparan los tres primeros
            # caracteres, que es el nivel en que el CIE-10 define sus bloques.
            head = plain[:3]
            if len(head) == 3 and head[1:].isdigit():
                async with conn.execute(
                    """select c.code, x.to_id from condition c
                        join condition_xref x on x.from_id = c.condition_id
                       where c.code_system='icd10cm' and c.code like '%-%'"""
                ) as cur:
                    for r in await cur.fetchall():
                        lo, _, hi = r["code"].partition("-")
                        if lo[:1] == head[:1] == hi[:1] and lo[1:3].isdigit() and hi[1:3].isdigit():
                            if int(lo[1:3]) <= int(head[1:3]) <= int(hi[1:3]):
                                hits.add(r["to_id"])
            if hits:
                out[raw] = sorted(await self._with_mesh_ancestors(hits))
        return out

    async def _with_mesh_ancestors(self, condition_ids: set[int]) -> set[int]:
        """Suma los ancestros MeSH de cada condición.

        Sin esto, `N18.5` llega a "Renal Insufficiency, Chronic" y se queda ahí,
        mientras la contraindicación de la metformina vive en "Renal
        Insufficiency" a secas. En CIE-10 `N18` y `N19` son HERMANOS y truncar
        no los conecta; en MeSH sí, y el número de árbol lo hace explícito:

            Renal Insufficiency, Chronic   C12.950.419.780.750
            Renal Insufficiency            C12.950.419.780      ← prefijo

        Ascender es, entonces, coincidencia de prefijo. Se sube sólo hacia
        arriba: un ancestro es más general que el diagnóstico del paciente, así
        que la alerta sigue aplicando. Bajar sería lo contrario —suponerle al
        paciente una enfermedad más específica de la que tiene— y eso no se hace.
        """
        if not condition_ids:
            return condition_ids
        conn = await self._c()
        ph = ",".join("?" * len(condition_ids))
        async with conn.execute(
            f"select tree from condition where condition_id in ({ph}) and tree is not null",
            tuple(condition_ids),
        ) as cur:
            trees = [t for r in await cur.fetchall() for t in (r["tree"] or "").split(",") if t]
        if not trees:
            return condition_ids

        out = set(condition_ids)
        # Los prefijos de cada árbol son exactamente sus ancestros.
        prefijos: set[str] = set()
        for t in trees:
            partes = t.split(".")
            for k in range(1, len(partes)):
                prefijos.add(".".join(partes[:k]))
        if not prefijos:
            return out
        ph2 = ",".join("?" * len(prefijos))
        async with conn.execute(
            f"""select condition_id, tree from condition
                 where code_system='mesh' and tree is not null""",
        ) as cur:
            for r in await cur.fetchall():
                for t in (r["tree"] or "").split(","):
                    if t and t in prefijos:
                        out.add(r["condition_id"])
                        break
        return out

    async def condition_ids_for_codes(
        self, codes: list[tuple[str, str]]
    ) -> dict[tuple[str, str], int]:
        """[(code_system, code)] -> condition_id.

        Traducir CIE-10 a MeSH NO pasa por acá: es trabajo del ETL
        (`build_condition_xref`). En runtime sólo se resuelve lo ya mapeado.
        """
        if not codes:
            return {}
        conn = await self._c()
        out: dict[tuple[str, str], int] = {}
        for system, code in codes:
            async with conn.execute(
                "select condition_id from condition where code_system=? and code=?",
                (system, code),
            ) as cur:
                row = await cur.fetchone()
            if row:
                out[(system, code)] = row["condition_id"]
        return out


client = RecetaliaDatabase()
