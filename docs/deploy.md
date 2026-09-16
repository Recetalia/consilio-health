# Deploy

Consilio se despliega con `docker compose` junto al resto del stack de
Recetalia, en la misma red interna. **No se expone a internet**: sólo lo alcanza
`recetalia-api-rest`, igual que `transversal-recetalia-api`.

> El repo traía una auditoría de un pipeline GitHub Actions → Google Cloud Run,
> con Workload Identity Federation y Artifact Registry. Era la infraestructura
> de la autora original, no la nuestra, y describía un flujo que además publicaba
> el `.db` de DDInter como release público — justo lo que su licencia gobierna.
> Se borró junto con los workflows que lo implementaban.

## Local

```bash
docker compose up --build
```

Requiere `API_KEY` en el entorno: el compose falla si no está, a propósito.
La base se monta desde `./data`, que **no** viaja en la imagen.

## Lo que falta definir

1. **Dónde corre.** El `.98` (PRE) primero; PROD (`.217`) después de validar.
   Hay que sumarlo al `docker-compose.yml` de `deploy-recetalia` y apuntarle
   `EXTERNAL_API_CONSILIO` desde `recetalia-api-rest`.
2. **Cómo llega la base al servidor.** El `.db` pesa ~14 MB y lo produce el ETL
   en una máquina de desarrollo. Opciones: `rsync` como parte del deploy, o un
   volumen que se actualice aparte. **Mientras DDInter siga siendo
   NonCommercial, no puede publicarse como artefacto descargable.**
3. **CI.** `ci-tests.yml` todavía apunta a Cloud Run y se auto-saltea sin los
   secrets de GCP. Hay que reescribirlo: tests + build de imagen, sin deploy.
4. **El peso de la imagen.** `torch` + DeBERTa la llevan a varios GB. Si el
   clasificador zero-shot no justifica ese costo en producción, sacarlo baja la
   imagen a ~200 MB y el fallback por regex sigue funcionando.

## Variables

| | |
|---|---|
| `API_KEY` | **obligatoria**. Sin ella el servicio responde 503 |
| `CONSILIO_ALLOW_NO_API_KEY=1` | escotilla de desarrollo; se loguea en cada arranque |
| `INTERACTION_DB_PATH` | default `/app/data/recetalia_interactions.db` |
| `CONSILIO_INTERACTIONS_RATE` | default `120/minute` |
| `CONSILIO_SEARCH_RATE` | default `300/minute` |
| `HF_HOME` | caché de modelos, para no re-descargar en cada arranque |

⚠️ El rate limit cuenta **por IP**, y detrás de un backend todas las requests
comparten la misma. El chequeo se dispara al agregar cada medicamento, no una
vez por receta: si se ajusta, hay que hacerlo pensando en médicos concurrentes,
no en recetas.
