# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.9-python3.12-bookworm-slim AS builder

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock .python-version ./

# WITH_ML=1 trae torch + transformers + el modelo zero-shot: unos 3 GB de
# imagen. Sólo hacen falta para clasificar la severidad de un prospecto de
# openFDA consultado EN VIVO, o sea para pares que no están en nuestra base;
# los 4.433 que sí están ya vienen clasificados por el ETL. Sin el modelo,
# `severity_classifier` cae a un fallback por regex y marca el hallazgo como
# `uncertain`, que es lo que ya hace ante cualquier error.
#
# Por eso el default es 0: en un host con el disco ajustado, 3 GB de torch
# para una ruta de respaldo es un mal negocio. `--build-arg WITH_ML=1` lo trae.
ARG WITH_ML=0

# Install dependencies only (locked, no project code yet).
RUN if [ "$WITH_ML" = "1" ]; then \
      uv sync --no-install-project --no-dev --extra ml; \
    else \
      uv sync --no-install-project --no-dev; \
    fi

# Copy application code and install the project
COPY app/ app/
RUN if [ "$WITH_ML" = "1" ]; then uv sync --no-dev --extra ml; else uv sync --no-dev; fi

# --- Application base stage ---
FROM python:3.12-slim AS app-base

WORKDIR /app

# Copy built virtualenv from builder
COPY --from=builder /app/.venv /app/.venv

# La base de conocimiento NO va en la imagen: se monta en /app/data.
#
# Dos razones. Una legal: hornear el .db derivado de DDInter en una imagen que
# se distribuye es justamente el acto que gobierna su cláusula NonCommercial.
# Una práctica: la base la construye nuestro ETL (scripts/build_recetalia_db.py)
# y se actualiza en otro ciclo que el código.
#
# Si falta, el arranque falla a propósito: es mejor que la revisión no levante
# a que sirva con cobertura degradada en silencio.
VOLUME ["/app/data"]

ENV PATH="/app/.venv/bin:$PATH"
ENV HF_HOME=/app/models
ENV TRANSFORMERS_CACHE=/app/models
ENV INTERACTION_DB_PATH=/app/data/recetalia_interactions.db

# Pre-download the severity classifier so the image is self-contained.
# Layer is cached until venv or model ID changes.
# In local dev, docker-compose mounts a volume over /app/models.
# The OpenMed NER model was dropped with /analyze (Recetalia fork): this service
# only resolves interactions, it does not read prescription text.
ARG WITH_ML=0
RUN if [ "$WITH_ML" = "1" ]; then \
      python -c "from transformers import pipeline; \
        pipeline('zero-shot-classification', model='MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli')"; \
    else \
      echo "[build] sin modelo ML: severity_classifier cae a regex y marca uncertain"; \
    fi

# App code comes last — most frequently changing layer
COPY --from=builder /app/app /app/app
COPY scripts/ /app/scripts/

RUN chmod +x /app/scripts/prod-startup.sh /app/scripts/ci-startup.sh

# Create a non-root user for security
RUN groupadd -r consilio && useradd -r -g consilio consilio && \
    chown -R consilio:consilio /app

USER consilio

# --- Runtime stage ---
FROM app-base AS runtime

EXPOSE 8000

ENTRYPOINT ["/app/scripts/prod-startup.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
