#!/bin/bash
set -e

# Arranque de producción.
#
# La base de conocimiento NO está horneada en la imagen: se monta en /app/data
# (ver el comentario del Dockerfile — es una decisión legal además de práctica).
# Si falta, es mejor fallar acá con un mensaje que arrancar y servir "sin
# interacciones conocidas" para todo, que se lee igual que "es seguro".

echo "[PROD] Consilio arrancando…"

DB="${INTERACTION_DB_PATH:-/app/data/recetalia_interactions.db}"
if [ ! -r "$DB" ]; then
  echo "[PROD] FATAL: no se puede leer la base en $DB." >&2
  echo "[PROD] Montá el volumen con la base construida por scripts/build_recetalia_db.py." >&2
  exit 1
fi
echo "[PROD] Base: $DB ($(du -h "$DB" | cut -f1))"

exec "$@"
