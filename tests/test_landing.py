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
    assert "https://app.consilio.medicinainteligente.ai/" in r.text


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
    refs = re.findall(r'(?:href|src)="(/(?:landing|ui)/[^"]+)"', html)
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
