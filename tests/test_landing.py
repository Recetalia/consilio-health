"""Landing pública: se sirve sin API key y no abre nada más.

`TestClient(app)` sin `with` no corre el lifespan: no hace falta la base para
servir estáticos, y las rutas de API se rechazan en el middleware antes de
tocarla.
"""

import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client():
    with patch.dict(os.environ, {"API_KEY": "test-key"}):
        yield TestClient(app)


def test_landing_publica_sin_api_key(client):
    r = client.get("/landing/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Abrir Consilio" in r.text
    # Los botones llevan a PREPRODUCCIÓN (decisión de Pablo 2026-10-02): PROD no es demo pública.
    assert "https://consiliopre.medicinainteligente.ai/" in r.text
    assert "app.consilio.medicinainteligente.ai" not in r.text


def test_landing_sin_barra_redirige(client):
    r = client.get("/landing", follow_redirects=False)
    assert r.status_code in (301, 302, 307, 308)
    assert r.headers["location"].endswith("/landing/")


@pytest.mark.parametrize("asset", ["landing.css", "landing.js"])
def test_assets_de_la_landing_publicos(client, asset):
    assert client.get(f"/landing/{asset}").status_code == 200


@pytest.mark.parametrize("method,path", [
    ("post", "/interactions"),
    ("post", "/contraindications"),
    ("get", "/drugs/search?q=aspirina"),
    ("get", "/conditions/search?q=renal"),
    ("post", "/admin/cache/clear"),
])
def test_api_sigue_exigiendo_key(client, method, path):
    r = getattr(client, method)(path, **({"json": {}} if method == "post" else {}))
    assert r.status_code == 401


def test_prefijo_landing_no_abre_rutas_parecidas(client):
    # "/landing-algo" no empieza con "/landing/": no debe quedar público.
    assert client.get("/landingx").status_code == 401


def test_assets_referenciados_llevan_cache_bust():
    # Cloudflare cachea .js/.css/.svg 4 h: sin ?v= un deploy sirve lo viejo.
    html = (ROOT / "app/landing/index.html").read_text()
    # Rutas relativas desde 2026-10-01 (landing portable): landing.css, landing.js, assets/...
    refs = re.findall(r'(?:href|src)="((?:landing\.(?:css|js)|assets/)[^"]+)"', html)
    assert refs, "la landing no referencia assets propios"
    assert all("?v=" in r for r in refs), [r for r in refs if "?v=" not in r]


def _root_vars(css: str) -> dict[str, str]:
    block = re.search(r":root\s*\{(.*?)\}", css, re.S).group(1)
    block = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    return {k: v.strip() for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block)}


def test_tokens_de_la_landing_iguales_a_los_de_la_app():
    """La landing copia los tokens de app/web/style.css: que no diverjan."""
    app_vars = _root_vars((ROOT / "app/web/style.css").read_text())
    landing_vars = _root_vars((ROOT / "app/landing/landing.css").read_text())
    assert landing_vars
    distintos = {k: (v, app_vars.get(k)) for k, v in landing_vars.items() if app_vars.get(k) != v}
    assert not distintos, f"tokens desincronizados (landing, app): {distintos}"


def test_contacto_va_a_medicina_inteligente():
    html = (ROOT / "app/landing/index.html").read_text()
    mailtos = re.findall(r'href="mailto:([^"?]+)', html)
    assert mailtos and set(mailtos) == {"hello@medicinainteligente.ai"}, mailtos


# ---- Landing portable: se monta en medicinainteligente.ai/consilio/ y en
# consilio.medicinainteligente.ai/ (2026-10-01, pedido de medicinainteligente). Bajo
# un prefijo, cualquier ruta que empiece con "/" sale del prefijo y rompe la página.

LANDING = ROOT / "app" / "landing"
_REF = re.compile(r'(?:href|src|content|action)="([^"]*)"|fetch\(\s*["\'`]([^"\'`]*)|url\(([^)]*)\)')


def _refs(texto):
    for m in _REF.finditer(texto):
        ref = next(g for g in m.groups() if g is not None).strip("'\"")
        if ref:
            yield ref


@pytest.mark.parametrize("archivo", ["index.html", "landing.js", "landing.css"])
def test_landing_sin_rutas_absolutas(archivo):
    texto = (LANDING / archivo).read_text(encoding="utf-8")
    absolutas = [r for r in _refs(texto) if r.startswith("/") and not r.startswith("//")]
    assert absolutas == [], f"{archivo} tiene rutas absolutas: {absolutas}"


def test_landing_recursos_relativos_existen():
    html = (LANDING / "index.html").read_text(encoding="utf-8")
    locales = {r.split("?")[0] for r in re.findall(r'(?:href|src)="([^"]*)"', html)
               if not re.match(r"^(https?:|mailto:|#|data:|tel:)", r) and r not in ("", "./")}
    faltan = [r for r in sorted(locales) if r != "data/summary" and not (LANDING / r).is_file()]
    assert faltan == [], f"recursos referenciados que no existen en app/landing: {faltan}"


def test_landing_canonical_en_sitio_madre():
    html = (LANDING / "index.html").read_text(encoding="utf-8")
    assert '<link rel="canonical" href="https://medicinainteligente.ai/consilio/">' in html
    assert 'property="og:url" content="https://medicinainteligente.ai/consilio/"' in html


def test_cifras_tambien_bajo_landing_sin_key(client):
    # La landing pide `data/summary` relativo: bajo /landing/ (y bajo cualquier prefijo
    # que el borde mapee a /landing/) tiene que responder igual que /data/summary.
    from app.api import data as data_api

    async def falso(request):
        return {"interactions": {"distinct_pairs": 1}}

    with patch.object(data_api, "data_summary", falso):
        r = client.get("/landing/data/summary")
    assert r.status_code == 200
    assert r.json()["interactions"]["distinct_pairs"] == 1
