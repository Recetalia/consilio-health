"""GET /monografia: lectura de la base y contrato del endpoint."""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.clients.recetalia_db import RecetaliaDatabase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.fetch_aemps_monografias import _SCHEMA  # noqa: E402


def _base(tmp_path, con_tablas=True) -> Path:
    path = tmp_path / "mono.db"
    db = sqlite3.connect(path)
    db.execute("create table interaction (id integer)")
    if con_tablas:
        db.executescript(_SCHEMA)
        db.execute("""insert into monografia values ('ibuprofeno+paracetamol', '["paracetamol","ibuprofeno"]',
                      'M01AE51', 'Ibuprofeno, combinaciones', 'Antiinflamatorios', '89654', 'ANTIDOL DUAL',
                      'https://cima.aemps.es/cima/dochtml/ft/89654/FichaTecnica.html', '2025-02-11', 'ok', null,
                      '2026-11-05', 'aemps')""")
        db.execute("insert into monografia_seccion values ('ibuprofeno+paracetamol','4.3','Contraindicaciones','<p>B</p>',1)")
        db.execute("insert into monografia_seccion values ('ibuprofeno+paracetamol','4.1','Indicaciones','<p>A</p>',0)")
        db.execute("""insert into monografia (composicion, principios_activos, estado, fetched_at)
                      values ('codeina', '["codeína"]', 'sin_referencia', '2026-11-05')""")
    db.commit()
    db.close()
    return path


async def test_cliente_encuentra_la_composicion_en_cualquier_orden_y_ordena_secciones(tmp_path):
    cliente = RecetaliaDatabase(db_path=str(_base(tmp_path)))
    try:
        m = await cliente.monografia(["Paracetamol", "IBUPROFENO"])
        assert m["estado"] == "ok" and m["nregistro"] == "89654"
        assert [s["seccion"] for s in m["secciones"]] == ["4.1", "4.3"]
        assert (await cliente.monografia(["metformina"]))["estado"] == "desconocida"
    finally:
        await cliente.close()


async def test_cliente_con_base_vieja_devuelve_none(tmp_path):
    cliente = RecetaliaDatabase(db_path=str(_base(tmp_path, con_tablas=False)))
    try:
        assert await cliente.monografia(["paracetamol"]) is None
    finally:
        await cliente.close()


@pytest.fixture
def client():
    mock = MagicMock()
    mock.health_check = AsyncMock(return_value=True)
    mock.connect = AsyncMock()
    mock.close = AsyncMock()
    with patch.dict(os.environ, {"API_KEY": "test-key"}), \
         patch("app.main.recetalia_db.client", mock), \
         patch("app.api.monografia.recetalia_db.client", mock):
        from app.main import app
        yield TestClient(app, headers={"X-API-Key": "test-key"}), mock


def test_endpoint_disponible_con_fuente_y_aviso(client):
    tc, mock = client
    mock.monografia = AsyncMock(return_value={
        "composicion": "paracetamol", "principios_activos": '["paracetamol"]', "atc_codigo": "N02BE01",
        "atc_nombre": "Paracetamol", "atc_grupo": "Otros analgesicos y antipireticos", "nregistro": "85780",
        "nombre_ref": "ANTIDOL 1 G", "url_ficha": "https://x", "fecha_ficha": "2025-02-11", "estado": "ok",
        "secciones": [{"seccion": "4.1", "titulo": "Indicaciones", "html": "<p>Dolor</p>"}]})
    r = tc.get("/monografia", params={"sustancias": "paracetamol"})
    assert r.status_code == 200
    j = r.json()
    assert j["disponible"] is True and j["atc"]["codigo"] == "N02BE01"
    assert j["fuente"]["nregistro"] == "85780" and "AEMPS" in j["fuente"]["organismo"]
    assert "Uruguay" in j["fuente"]["aviso"]
    mock.monografia.assert_awaited_with(["paracetamol"])


def test_endpoint_sin_referencia_es_explicito(client):
    tc, mock = client
    mock.monografia = AsyncMock(return_value={"composicion": "codeina", "estado": "sin_referencia"})
    j = tc.get("/monografia", params={"sustancias": "codeína"}).json()
    assert j == {"disponible": False, "composicion": "codeina", "motivo": "sin_referencia"}


def test_endpoint_base_sin_monografias(client):
    tc, mock = client
    mock.monografia = AsyncMock(return_value=None)
    assert tc.get("/monografia", params={"sustancias": "paracetamol"}).json()["motivo"] == "sin_datos"


def test_endpoint_exige_api_key(client):
    tc, _ = client
    r = TestClient(tc.app).get("/monografia", params={"sustancias": "paracetamol"})
    assert r.status_code in (401, 403)
