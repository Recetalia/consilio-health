"""Cliente async del SQLite de Recetalia.

Reemplaza a `ddinter_db`, que leía la base cruda de DDInter. Ésta es nuestra:
además de los 160.235 pares heredados trae los derivados de openFDA, las
alertas fármaco-patología de MED-RT y el mapeo de sustancias del DNMA.

## Precedencia por procedencia

Ante dos filas para el mismo hecho gana la de mayor autoridad:

    recetalia  >  ddinter  >  openfda

`recetalia` es lo que revisó un farmacéutico y pisa a todo lo importado.
`ddinter` trae severidad estructurada de una base curada. `openfda` es una
inferencia sobre texto libre de prospecto: sirve donde no hay nada mejor, pero
no compite con las otras dos.

Esa precedencia es SQL, no convención: vive en `_PRECEDENCE` y se aplica en
cada búsqueda de par.
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
_PRECEDENCE = "case i.source when 'recetalia' then 0 when 'ddinter' then 1 else 2 end"

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


def _readonly_immutable_uri(db_path: str) -> str:
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
        """El mejor hecho conocido para el par, por precedencia de procedencia."""
        if drug_a == drug_b:
            return None
        lo, hi = (drug_a, drug_b) if drug_a < drug_b else (drug_b, drug_a)
        conn = await self._c()
        async with conn.execute(
            f"""select i.severity, i.mechanism, i.management, i.evidence, i.source,
                       i.reviewed_by, a.canonical as name_a, b.canonical as name_b
                from interaction i
                join drug a on a.drug_id = i.drug_a_id
                join drug b on b.drug_id = i.drug_b_id
                where i.drug_a_id = ? and i.drug_b_id = ?
                order by {_PRECEDENCE}
                limit 1""",
            (lo, hi),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return {
            "severity": (row["severity"] or "unknown").lower(),
            "mechanism": row["mechanism"],
            "management": row["management"],
            "evidence": row["evidence"],
            "source": row["source"],
            "reviewed_by": row["reviewed_by"],
            "drug_a_name": row["name_a"],
            "drug_b_name": row["name_b"],
            # openFDA es inferencia sobre texto libre; las otras dos no.
            "uncertain": row["source"] == "openfda",
        }

    async def lookup_by_rxcui(self, rxcui_a: str, rxcui_b: str) -> dict[str, Any] | None:
        ids = await self.drug_ids_by_rxcui([rxcui_a, rxcui_b])
        a, b = ids.get(rxcui_a), ids.get(rxcui_b)
        return await self.lookup_pair(a, b) if a and b else None

    async def lookup_by_name(self, name_a: str, name_b: str) -> dict[str, Any] | None:
        a = await self.drug_id_by_name(name_a)
        b = await self.drug_id_by_name(name_b)
        return await self.lookup_pair(a, b) if a and b else None

    # --- alertas fármaco-paciente -----------------------------------------

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
