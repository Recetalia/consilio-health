"""GET /monografia — ficha técnica oficial (AEMPS) de un principio activo o combinación.

Información de referencia para quien prescribe: indicaciones, posología, contraindicaciones, advertencias,
interacciones, embarazo y lactancia, reacciones adversas. Textual, de la ficha técnica española de referencia de
esa composición, con su atribución: no se resume ni se reescribe (ver `scripts/fetch_aemps_monografias.py`).

Nunca responde con un silencio que parezca "no hay nada clínico que decir": si no hay ficha, `disponible=false`
con el motivo.
"""
from __future__ import annotations

import json
import os

from fastapi import APIRouter, Query, Request

from app.clients import recetalia_db
from app.main import limiter

router = APIRouter()

SEARCH_RATE = os.environ.get("CONSILIO_SEARCH_RATE", "300/minute")

AVISO = ("Ficha técnica de la AEMPS (España) del principio activo, como referencia. Puede diferir del producto "
         "registrado en Uruguay. No sustituye el criterio clínico.")


@router.get("/monografia")
@limiter.limit(SEARCH_RATE)
async def monografia(
    request: Request,
    sustancias: str = Query(..., min_length=2, max_length=400,
                            description="Principios activos separados por coma: 'paracetamol,ibuprofeno'"),
):
    nombres = [n.strip() for n in sustancias.split(",") if n.strip()][:8]
    if not nombres:
        return {"disponible": False, "composicion": "", "motivo": "sin_sustancias"}

    fila = await recetalia_db.client.monografia(nombres)
    if fila is None:
        return {"disponible": False, "composicion": "", "motivo": "sin_datos"}
    if fila.get("estado") != "ok":
        motivo = {"desconocida": "sin_referencia"}.get(fila["estado"], fila["estado"])
        return {"disponible": False, "composicion": fila["composicion"], "motivo": motivo}

    return {
        "disponible": True,
        "composicion": fila["composicion"],
        "principios_activos": json.loads(fila["principios_activos"] or "[]"),
        "atc": ({"codigo": fila["atc_codigo"], "nombre": fila["atc_nombre"], "grupo": fila["atc_grupo"]}
                if fila.get("atc_codigo") else None),
        "secciones": fila["secciones"],
        "fuente": {
            "nombre_ref": fila["nombre_ref"],
            "nregistro": fila["nregistro"],
            "url_ficha": fila["url_ficha"],
            "fecha_ficha": fila["fecha_ficha"],
            "organismo": "AEMPS — Agencia Española de Medicamentos y Productos Sanitarios (CIMA)",
            "aviso": AVISO,
        },
    }
