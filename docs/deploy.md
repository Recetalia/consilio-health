# Deploy

Consilio corre en el `.98` (PRE/DEV, `138.197.150.98`) con su propio compose,
detrás del nginx de `deploy-recetalia`. **Se expone a internet** en dos dominios.
PROD (`.217`) todavía no lo tiene.

> El repo traía una auditoría de un pipeline GitHub Actions → Google Cloud Run.
> Era la infraestructura de la autora original, no la nuestra, y publicaba el
> `.db` de DDInter como release público — justo lo que su licencia gobierna. Se
> borró junto con los workflows que lo implementaban.

## Dominios

| Dominio | Qué sirve | vhost | DNS (Cloudflare) |
|---|---|---|---|
| `app.consilio.medicinainteligente.ai` | la app completa: UI en `/` + API | `deploy/47-consilio-app.conf` | `*.consilio`, DNS-only (gris) |
| `consilio.medicinainteligente.ai` | landing en `/`; API por compatibilidad | `deploy/46-consilio.conf` | proxeado (naranja) |

En `consilio.medicinainteligente.ai`:

- `/` → la landing (`app/landing/`, que FastAPI sirve en `/landing/`).
- Siguen yendo al motor, porque hay clientes externos (PONS) que usan este
  dominio: `/interactions`, `/contraindications`, `/drugs/`, `/conditions/`,
  `/data/`, `/health`, `/docs`, `/redoc`, `/openapi.json`, `/admin/`, `/ui/`.
- Cualquier otra ruta → `302 /`.

Indexación: la landing se indexa (es marketing). La app y la API llevan
`X-Robots-Tag: noindex` y `robots.txt` las bloquea, porque la base de
interacciones es CC BY-NC-SA. En el 46 el header va por variable: un
`add_header` dentro de un `location` anula todos los heredados del `server`.

`recetalia-api-rest` llama al motor por la red interna, `http://consilio:8000`,
sin pasar por ningún dominio.

## En el server

`/opt/recetalia/consilio/`, sin git:

- `docker-compose.yml` = copia de `deploy/docker-compose.98.yml`. Imagen
  `consilio:dev`, `WITH_ML=0` (sin torch), sin puertos publicados: se entra
  sólo por el nginx, redes `medicinainteligente-net` y `recetalia_recetalia-net`.
  **El `docker-compose.yml` del repo es otro** (publica el 8000): un rsync que
  no lo excluya lo pisa.
- `.env` con `API_KEY`. Sin ella el compose no levanta.
- `data/` montado `ro`: la base no viaja en la imagen.

Los vhosts viven en `/opt/recetalia/deploy-recetalia/nginx/conf.d/` (montado en
el contenedor `recetalia-nginx` como `/etc/nginx/user_conf.d/`). No están en el
repo `deploy-recetalia`: su `scripts/deploy.sh` los excluye del `rsync --delete`
(`RSYNC_KEEP_EXCLUDES`).

## Desplegar código

```bash
# desde la raíz del repo, en la Mac
ssh root@138.197.150.98 'df -h / && docker tag consilio:dev consilio:rollback-<fecha>'
# si el disco pasa el 85 %: docker builder prune -f  (sin -a; ver memoria de gotchas)
rsync -az --delete \
  --exclude docker-compose.yml --exclude .env --exclude 'data/' --exclude .venv \
  --exclude .git --exclude docs/ --exclude eval/ --exclude '*.bak-*' \
  ./ root@138.197.150.98:/opt/recetalia/consilio/
ssh root@138.197.150.98 'cd /opt/recetalia/consilio && docker compose build consilio && docker compose up -d consilio'
```

La base se sube aparte, sólo cuando cambia el ETL:
`rsync data/recetalia_interactions.db data/duplicidad_cupos.json root@138.197.150.98:/opt/recetalia/consilio/data/`
(backup previo en el server). El runtime la abre inmutable: hace falta reiniciar
el contenedor para verla.

**Cloudflare cachea `.js`/`.css`/`.svg` 4 h** en el dominio proxeado. La UI y la
landing referencian sus recursos con `?v=<versión>`: subirla en cada deploy que
toque `app/web/` o `app/landing/`.

## Instalar o cambiar un vhost

1. **Cert primero** (Let's Encrypt HTTP-01; funciona también con el registro
   proxeado): un vhost cuyo cert no existe tumba el `nginx -t`.
   ```bash
   docker exec recetalia-nginx sh -c 'certbot certonly --webroot -w /var/www/letsencrypt \
     -d <dominio> --email $CERTBOT_EMAIL --agree-tos --no-eff-email -n'
   ```
   La renovación la hace la imagen jonasal sola.
2. Backup del vhost que se pisa, con sufijo `.bak-<fecha>` (el deploy lo excluye).
3. Copiar el `.conf` a `/opt/recetalia/deploy-recetalia/nginx/conf.d/`.
4. **Symlink**, si el archivo es nuevo: jonasal no incluye `user_conf.d`, crea un
   symlink por archivo en `/etc/nginx/conf.d/` y sólo al arrancar. Sin él,
   `nginx -t` pasa en verde sin cargar el archivo.
   ```bash
   docker exec recetalia-nginx ln -s /etc/nginx/user_conf.d/<archivo> /etc/nginx/conf.d/
   docker exec recetalia-nginx nginx -t && docker exec recetalia-nginx nginx -s reload
   ```
5. Verificar que cargó: `docker exec recetalia-nginx nginx -T | grep 'server_name <dominio>'`.

## Verificar

```bash
curl -sI https://app.consilio.medicinainteligente.ai/          # 200, la UI
curl -s  https://consilio.medicinainteligente.ai/ | grep -c 'Abrir Consilio'   # landing
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://consilio.medicinainteligente.ai/interactions  # 401 sin key
curl -s https://consilio.medicinainteligente.ai/data/summary   # público
```

## Rollback

`docker tag consilio:rollback-<fecha> consilio:dev && docker compose up -d consilio`
(con `--no-build`); restaurar el `.bak-*` del vhost y `nginx -s reload`; para un
vhost nuevo, borrar su symlink de `/etc/nginx/conf.d/` antes del reload.

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

## Pendiente

1. **PROD (`.217`)**: sumarlo y apuntarle `EXTERNAL_API_CONSILIO` desde
   `recetalia-api-rest`.
2. **CI**: tests + build de imagen, sin deploy.
3. **Licencia de DDInter** (NonCommercial): bloquea PROD y cualquier
   publicación de la base como artefacto descargable.
