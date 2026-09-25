"""Autenticación por API key.

Dos cambios respecto del upstream, los dos de seguridad:

1. **No falla abierta.** Antes, si `API_KEY` no estaba seteada el middleware
   dejaba pasar todo con un comentario que decía "auth disabled". Un despliegue
   que olvide la variable queda completamente abierto y nada lo delata: el
   servicio responde normal. Ahora, sin key configurada se rechaza todo con 503,
   salvo los health checks. Un servicio que no arranca se arregla en minutos;
   uno abierto puede vivir meses.

   `CONSILIO_ALLOW_NO_API_KEY=1` permite correr sin key en desarrollo, y lo
   loguea como advertencia en cada arranque para que nadie lo herede sin verlo.

2. **Comparación en tiempo constante.** `!=` sobre strings corta en el primer
   byte distinto, lo que filtra información aprovechable para adivinar la clave.
"""

import logging
import os
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# Rutas sin autenticación: las necesita el orquestador para saber si el
# contenedor está vivo, y no exponen datos. `/data/summary` alimenta la sección
# pública "Los datos": sólo conteos agregados y fechas de actualización, nada
# que responda a una consulta clínica.
PUBLIC_PATHS = {"/health", "/health/data", "/data/summary",
                "/openapi.json", "/docs", "/redoc", "/"}
# Los estáticos de la interfaz no llevan key: son HTML, CSS y JS, no datos. La
# key la exigen igual los endpoints que la interfaz consume.
PUBLIC_PREFIXES = ("/ui/",)

_warned = False


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        global _warned
        api_key = os.environ.get("API_KEY", "")
        path = request.url.path

        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)

        if not api_key:
            if os.environ.get("CONSILIO_ALLOW_NO_API_KEY") == "1":
                if not _warned:
                    logger.warning(
                        "Corriendo SIN API key (CONSILIO_ALLOW_NO_API_KEY=1). "
                        "Sólo para desarrollo: cualquiera puede consultar.")
                    _warned = True
                return await call_next(request)
            logger.error("API_KEY no está configurada: se rechaza todo.")
            return JSONResponse(
                status_code=503,
                content={"detail": "Servicio mal configurado: falta API_KEY"},
            )

        provided = request.headers.get("X-API-Key", "")
        if not secrets.compare_digest(provided, api_key):
            return JSONResponse(
                status_code=401,
                content={"detail": "API key inválida o ausente"},
            )

        return await call_next(request)
