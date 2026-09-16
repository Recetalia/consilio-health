"""Tests for API key middleware."""

import os
import pytest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient


def make_test_app() -> FastAPI:
    """Minimal app with middleware and stub routes (no NER model needed)."""
    from app.middleware.api_key import APIKeyMiddleware

    test_app = FastAPI()
    test_app.add_middleware(APIKeyMiddleware)

    @test_app.get("/health")
    def health():
        return {"status": "ok"}

    @test_app.get("/health/data")
    def health_data():
        return {"status": "ready"}

    @test_app.post("/analyze")
    def analyze():
        return {"drugs": [], "raw_text": "test"}

    @test_app.post("/interactions")
    def interactions():
        return {"interactions": [], "safe": True}

    return test_app


@pytest.fixture
def client_with_key():
    with patch.dict(os.environ, {"API_KEY": "test-secret-key"}):
        yield TestClient(make_test_app())


@pytest.fixture
def client_without_key():
    env = {k: v for k, v in os.environ.items() if k != "API_KEY"}
    with patch.dict(os.environ, env, clear=True):
        yield TestClient(make_test_app())


class TestAPIKeyMiddleware:
    def test_health_no_key_required(self, client_with_key):
        r = client_with_key.get("/health")
        assert r.status_code == 200

    def test_health_data_no_key_required(self, client_with_key):
        r = client_with_key.get("/health/data")
        assert r.status_code == 200

    def test_analyze_rejected_without_key(self, client_with_key):
        r = client_with_key.post("/analyze", json={"text": "ibuprofen"})
        assert r.status_code == 401

    def test_analyze_rejected_with_wrong_key(self, client_with_key):
        r = client_with_key.post(
            "/analyze",
            json={"text": "ibuprofen"},
            headers={"X-API-Key": "wrong"},
        )
        assert r.status_code == 401

    def test_analyze_accepted_with_correct_key(self, client_with_key):
        r = client_with_key.post(
            "/analyze",
            json={"text": "ibuprofen"},
            headers={"X-API-Key": "test-secret-key"},
        )
        assert r.status_code == 200

    def test_interactions_rejected_without_key(self, client_with_key):
        r = client_with_key.post("/interactions", json={"drugs": ["a", "b"]})
        assert r.status_code == 401

    def test_sin_api_key_rechaza_todo(self, client_without_key):
        """Sin API_KEY el servicio NO queda abierto: responde 503.

        El upstream dejaba pasar todo con un comentario que decía "auth
        disabled". Un despliegue que olvida la variable queda accesible y nada
        lo delata, porque el servicio responde normal. Un 503 se arregla en
        minutos; un servicio abierto puede vivir meses.
        """
        r = client_without_key.post("/interactions", json={"drugs": ["a", "b"]})
        assert r.status_code == 503
        assert "API_KEY" in r.json()["detail"]

    def test_sin_api_key_los_health_siguen_abiertos(self, client_without_key):
        """El orquestador tiene que poder saber si el contenedor está vivo."""
        assert client_without_key.get("/health").status_code == 200
        assert client_without_key.get("/health/data").status_code == 200

    def test_escotilla_de_desarrollo(self, client_without_key):
        """CONSILIO_ALLOW_NO_API_KEY=1 permite correr sin key en local."""
        with patch.dict(os.environ, {"CONSILIO_ALLOW_NO_API_KEY": "1"}):
            r = client_without_key.post("/interactions", json={"drugs": ["a", "b"]})
        assert r.status_code != 503
