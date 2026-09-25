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
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiosqlite

from app.nlp.nombres import skeleton

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


def _token_corto(s: str) -> bool:
    """¿Alguno de los tokens normalizados tiene <=2 caracteres?

    Medido 2026-09-25: 'vitamina c' resolvía por esqueleto a Phylloquinone
    (vitamina K). `skeleton()` mapea k->c, así que 'vitamina c' y 'vitamina k'
    caen en el mismo 'vitamin c'. Además un token de una sola letra puede
    desaparecer del todo: 'Vitamin A' y 'Vitamin E' quedan las dos en
    'vitamin', sin rastro de la letra. Las letras sueltas son justo lo que
    distingue a las vitaminas entre sí, y el esqueleto no las respeta -así
    que con un token así no se puede confiar en el esqueleto, ni para
    resolver un nombre ni para que un alias/sustancia del DNMA aporte al
    índice.
    """
    return any(len(tok) <= 2 for tok in normalize(s).split())


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
        self._respaldo: dict | None = None

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
        self._respaldo = None

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
        hit = idx["dnma"].get(n)
        if hit or _token_corto(name):
            # Con un token corto el esqueleto no es confiable (ver
            # `_token_corto`): mejor no resolver que resolver mal.
            return hit
        return idx["skel"].get(skeleton(name))

    async def _indice_respaldo(self) -> dict[str, dict]:
        if self._respaldo is not None:
            return self._respaldo
        conn = await self._c()
        # `_c()` se llama ANTES de tomar `self._lock`, no adentro: `_c()`
        # puede disparar `connect()`, que toma el MISMO lock, y `asyncio.Lock`
        # no es reentrante. Si `_c()` se llamara dentro del `async with`, la
        # corrutina se autobloquearía esperando un lock que ella misma tiene
        # tomado.
        async with self._lock:
            if self._respaldo is not None:
                return self._respaldo
            dnma: dict[str, int] = {}
            # Dos niveles, medidos sobre la base real (2026-09-25): de 2.151
            # esqueletos construidos desde `drug_alias`, 112 resultan ambiguos
            # (>1 drug_id). De esos, 107 (95,5%) son SÓLO por alias entre
            # paréntesis que marcan vía/forma ("Diclofenac (ophthalmic)",
            # "Diclofenac (topical)"): `skeleton()` borra el paréntesis y las
            # tres formulaciones caen en el mismo esqueleto "diclofenac",
            # aunque son `drug_id` distintos con perfil de interacción propio.
            # Los otros 5 son homónimos genuinos sin paréntesis en ningún
            # alias (`vitamin`, `vitamin d`, `iodid i`, `interferon alf n`,
            # `iobenguan i`) y tienen que seguir sin resolver.
            #
            # Además, ni el alias/sustancia ni el nombre buscado pueden tener
            # un token de <=2 caracteres (ver `_token_corto`): son las letras
            # sueltas que distinguen vitaminas entre sí, y `skeleton()` las
            # borra o las confunde. Tras excluirlos, no queda ningún homónimo
            # NATURAL en la base real (los 5 de arriba tenían todos un token
            # corto); el guard de un solo candidato se sigue probando con un
            # caso armado a mano (`test_homonimo_sin_tokens_cortos...`).
            #
            # Por eso el índice separa "base" (alias sin paréntesis + DNMA,
            # que no trae vía) de "vía" (alias con paréntesis). Un esqueleto
            # con vía SÓLO se usa si la base no tiene NINGÚN candidato para
            # ese esqueleto — así una receta sin vía ("diclofenaco") cae en el
            # sistémico, que es lo que manda, sin arbitrar entre formulaciones
            # cuando la base ya tenía alguna (ambigua o no). Dentro de cada
            # nivel sigue rigiendo la regla de UN solo drug_id: seguir ambiguo
            # (los 5 homónimos) bloquea igual que antes.
            skel_base: dict[str, set[int]] = defaultdict(set)
            skel_via: dict[str, set[int]] = defaultdict(set)
            try:
                async with conn.execute(
                    "select sustancia_dsc, drug_id from dnma_substance_map "
                    "where drug_id is not null"
                ) as cur:
                    for r in await cur.fetchall():
                        # El respaldo por DNMA normalizado no exige tokens
                        # largos: no pasa por `skeleton()`, así que la
                        # confusión k->c y las letras que desaparecen no le
                        # aplican.
                        dnma.setdefault(normalize(r[0]), r[1])
                        if not _token_corto(r[0]):
                            skel_base[skeleton(r[0])].add(r[1])
            except aiosqlite.OperationalError:
                logger.warning(
                    "Sin dnma_substance_map: el respaldo por DNMA queda vacío")
            async with conn.execute("select alias, drug_id from drug_alias") as cur:
                for r in await cur.fetchall():
                    if _token_corto(r["alias"]):
                        continue
                    destino = skel_via if "(" in r["alias"] else skel_base
                    destino[skeleton(r["alias"])].add(r["drug_id"])
            skel: dict[str, int] = {
                s: next(iter(ids)) for s, ids in skel_base.items()
                if s and len(ids) == 1
            }
            for s, ids in skel_via.items():
                if s and s not in skel_base and len(ids) == 1:
                    skel[s] = next(iter(ids))
            self._respaldo = {"dnma": dnma, "skel": skel}
            return self._respaldo

    async def canonicals_for(self, drug_ids: list[int]) -> dict[int, str]:
        if not drug_ids:
            return {}
        conn = await self._c()
        ph = ",".join("?" * len(drug_ids))
        async with conn.execute(
            f"select drug_id, canonical from drug where drug_id in ({ph})",
            tuple(drug_ids),
        ) as cur:
            return {r["drug_id"]: r["canonical"] for r in await cur.fetchall()}

    # `name_es` es para MOSTRAR: el canónico está en inglés y esta interfaz es
    # para un médico uruguayo. Precedencia (ver `docs/2026-09-25-castellano-y-
    # colores.md`): alias `es` curado a mano (`source` distinto de 'aemps') >
    # DNMA (grafía del vademécum uruguayo, la que el médico espera leer) >
    # alias `es` de la AEMPS. Se queda en NULL cuando no sabemos: inventar una
    # traducción de un fármaco es peor que el inglés.
    _NAME_ES_SQL = """coalesce(
                        (select es.alias from drug_alias es
                          where es.drug_id = d.drug_id and es.lang = 'es'
                            and es.source <> 'aemps' limit 1),
                        (select m.sustancia_dsc from dnma_substance_map m
                          where m.drug_id = d.drug_id limit 1),
                        (select es.alias from drug_alias es
                          where es.drug_id = d.drug_id and es.lang = 'es'
                            and es.source = 'aemps' limit 1)
                      )"""

    async def search_drugs(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Busca fármacos por prefijo de alias o de sustancia DNMA, para el
        autocompletado.

        Ordena por si el término empieza con lo tecleado antes que por si sólo
        lo contiene: quien escribe "war" espera warfarina primero, no
        clorhidrato de algo-war. El DNMA hoy sólo alimentaba `name_es` (para
        mostrar); acá se suma como fuente de BÚSQUEDA, así que "amlodipino"
        encuentra el fármaco aunque no tenga (todavía) alias en castellano.
        Se combina en Python, sobre el índice que ya arma `_indice_respaldo`,
        para no pagar dos veces `normalize()` en SQL ni duplicar fármacos que
        matchean por las dos vías.
        """
        q = normalize(query)
        if len(q) < 2:
            return []
        conn = await self._c()
        async with conn.execute(
            f"""select d.drug_id, d.canonical, d.rxcui, {self._NAME_ES_SQL} as name_es,
                       min(case when a.alias_norm like ? escape '\\' then 0 else 1 end) as rank
                  from drug_alias a
                  join drug d on d.drug_id = a.drug_id
                 where a.alias_norm like ? escape '\\'
                 group by d.drug_id, d.canonical, d.rxcui, name_es""",
            (f"{_like(q)}%", f"%{_like(q)}%"),
        ) as cur:
            rows = await cur.fetchall()
        # drug_id -> (rank, canonical, rxcui, name_es)
        candidatos: dict[int, tuple[int, str, str | None, str | None]] = {
            r["drug_id"]: (r["rank"], r["canonical"], r["rxcui"], r["name_es"]) for r in rows
        }

        idx = await self._indice_respaldo()
        dnma_rank: dict[int, int] = {}
        for norm, drug_id in idx["dnma"].items():
            if drug_id in candidatos or q not in norm:
                continue
            r = 0 if norm.startswith(q) else 1
            if drug_id not in dnma_rank or r < dnma_rank[drug_id]:
                dnma_rank[drug_id] = r

        if dnma_rank:
            ph = ",".join("?" * len(dnma_rank))
            async with conn.execute(
                f"""select d.drug_id, d.canonical, d.rxcui, {self._NAME_ES_SQL} as name_es
                      from drug d where d.drug_id in ({ph})""",
                tuple(dnma_rank),
            ) as cur:
                for r in await cur.fetchall():
                    candidatos[r["drug_id"]] = (
                        dnma_rank[r["drug_id"]], r["canonical"], r["rxcui"], r["name_es"])

        ordenados = sorted(
            candidatos.items(), key=lambda kv: (kv[1][0], len(kv[1][1]), kv[1][1]))[:limit]
        return [{"drug_id": did, "name": canonical, "rxcui": rxcui, "name_es": _titulo(name_es)}
                for did, (_, canonical, rxcui, name_es) in ordenados]

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
