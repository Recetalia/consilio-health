"""API endpoint tests.

Tests /interactions and /health endpoints directly.
/analyze requires the NER model loaded — tested via Docker or manual run.
"""

import os

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def mock_ddinter():
    """Mockea el cliente de la base en todos los módulos que lo importan."""
    mock = MagicMock()
    mock.health_check = AsyncMock(return_value=True)
    mock.connect = AsyncMock()
    mock.close = AsyncMock()
    mock.stats = AsyncMock(return_value={"drugs": 0, "interactions": 0})
    mock.lookup_by_rxcui = AsyncMock(return_value=None)
    mock.lookup_by_name = AsyncMock(return_value=None)
    with patch("app.services.interaction_checker.recetalia_db.client", mock), \
         patch("app.api.health.recetalia_db.client", mock), \
         patch("app.main.recetalia_db.client", mock):
        yield mock


@pytest.fixture
def mock_severity():
    """Mock severity_classifier in every module that imports it."""
    mock = MagicMock()
    mock.classify.return_value = ("moderate", False)
    mock.load_model = MagicMock()
    mock.is_loaded.return_value = True
    with patch("app.services.interaction_checker.severity_classifier", mock), \
         patch("app.main.severity_classifier", mock):
        yield mock


@pytest.fixture(autouse=True)
def api_key_env():
    """El middleware ya no falla abierto: sin API_KEY rechaza todo con 503."""
    with patch.dict(os.environ, {"API_KEY": "test-key"}):
        yield


@pytest.fixture
def client(mock_ddinter, mock_severity):
    from app.main import app
    # La key va por defecto en el cliente: probar el contrato de /interactions
    # no es probar la autenticación, que tiene sus propios tests en
    # tests/test_api_key.py.
    return TestClient(app, headers={"X-API-Key": "test-key"})


class TestInteractionsValidation:
    def test_interactions_rejects_empty_string_drug(self, client):
        """Empty strings in drugs list must be rejected with 422."""
        resp = client.post(
            "/interactions",
            json={"drugs": ["metformin", "", "lisinopril"]},
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 422

    def test_interactions_rejects_whitespace_only_drug(self, client):
        """Whitespace-only strings must be rejected after stripping."""
        resp = client.post(
            "/interactions",
            json={"drugs": ["  ", "metformin"]},
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 422

    def test_interactions_rejects_long_drug_name(self, client):
        """Drug names over 200 chars must be rejected."""
        resp = client.post(
            "/interactions",
            json={"drugs": ["a" * 201, "metformin"]},
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 422


def test_interaction_result_accepts_new_fields():
    from app.api.schemas import InteractionResult

    result = InteractionResult(
        drug_a="Warfarin",
        drug_b="Aspirin",
        rxcui_a="11289",
        rxcui_b="1191",
        severity="major",
        source="ddinter",
        description="",
        management="Consult a healthcare professional.",
        uncertain=False,
    )
    assert result.source == "ddinter"
    assert result.rxcui_a == "11289"


def test_interactions_response_includes_coverage_summary():
    from app.api.schemas import DDInterDataSource, InteractionsDataSources, InteractionsResponse

    response = InteractionsResponse(
        interactions=[],
        safe=True,
        error=None,
        data_sources=InteractionsDataSources(
            ddinter=DDInterDataSource(
                version="2.0",
                license="CC BY-NC-SA 4.0",
                attribution_url="https://ddinter2.scbdd.com/",
            ),
            severity_classifier="model-id",
        ),
        coverage_summary={"ddinter": 0, "openfda": 0, "unknown": 0},
    )
    assert response.coverage_summary == {"ddinter": 0, "openfda": 0, "unknown": 0}
    assert response.data_sources.ddinter.version == "2.0"


class TestInteractionsEndpoint:
    def test_known_interaction(self, client):
        with patch("app.api.interactions.interaction_checker.check", new=AsyncMock(return_value={
            "interactions": [{
                "drug_a": "ibuprofen",
                "drug_b": "warfarin",
                "rxcui_a": "5640",
                "rxcui_b": "11289",
                "severity": "major",
                "source": "ddinter",
                "description": "Interaction reported in DDInter 2.0.",
                "management": "Consult a healthcare professional for guidance.",
                "uncertain": False,
            }],
            "safe": False,
            "error": None,
            "coverage_summary": {"ddinter": 1, "openfda": 0, "unknown": 0},
        })):
            resp = client.post("/interactions", json={"drugs": ["ibuprofen", "warfarin"]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["safe"] is False
        assert len(data["interactions"]) >= 1
        assert data["interactions"][0]["severity"] in ["major", "moderate"]
        assert data["interactions"][0]["source"] == "ddinter"
        assert data["coverage_summary"]["ddinter"] == 1
        assert "data_sources" in data
        assert data["data_sources"]["ddinter"]["version"] == "2.0"
        assert "severity_classifier" in data["data_sources"]

    def test_no_interaction(self, client):
        with patch("app.api.interactions.interaction_checker.check", new=AsyncMock(return_value={
            "interactions": [],
            "safe": True,
            "error": None,
            "coverage_summary": {"ddinter": 0, "openfda": 0, "unknown": 1},
        })):
            resp = client.post("/interactions", json={"drugs": ["ibuprofen", "amoxicillin"]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["safe"] is True
        assert data["coverage_summary"]["unknown"] == 1

    def test_three_drugs(self, client):
        with patch("app.api.interactions.interaction_checker.check", new=AsyncMock(return_value={
            "interactions": [
                {"drug_a": "ibuprofen", "drug_b": "warfarin", "severity": "major", "source": "ddinter",
                 "description": "x", "management": "m", "uncertain": False},
                {"drug_a": "warfarin", "drug_b": "aspirin", "severity": "major", "source": "ddinter",
                 "description": "x", "management": "m", "uncertain": False},
            ],
            "safe": False,
            "error": None,
            "coverage_summary": {"ddinter": 2, "openfda": 0, "unknown": 1},
        })):
            resp = client.post("/interactions", json={"drugs": ["ibuprofen", "warfarin", "aspirin"]})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["interactions"]) >= 2

    def test_validation_requires_two_drugs(self, client):
        resp = client.post("/interactions", json={"drugs": ["ibuprofen"]})
        assert resp.status_code == 422

    def test_validation_requires_drugs_field(self, client):
        resp = client.post("/interactions", json={})
        assert resp.status_code == 422

    def test_products_only_reaches_checker(self, client):
        with patch("app.api.interactions.interaction_checker.check", new=AsyncMock(return_value={
            "interactions": [],
            "safe": True,
            "error": None,
            "coverage_summary": {"ddinter": 0, "openfda": 0, "unknown": 0},
            "duplicities": [],
            "duplicities_suppressed": [],
            "duplicity_not_evaluated": [],
            "duplicity_warnings": [],
        })) as mock_check:
            resp = client.post("/interactions", json={"products": [
                {"id": "p1", "substances": ["paracetamol"]},
                {"id": "p2", "substances": ["codeina"]},
            ]})
        assert resp.status_code == 200
        kwargs = mock_check.call_args.kwargs
        ids = [p["id"] for p in kwargs["products"]]
        assert ids == ["p1", "p2"]

    def test_validation_rejects_single_drug_without_products(self, client):
        resp = client.post("/interactions", json={"drugs": ["a"]})
        assert resp.status_code == 422

    def test_validation_rejects_repeated_product_ids(self, client):
        resp = client.post("/interactions", json={"products": [
            {"id": "p1", "substances": ["paracetamol"]},
            {"id": "p1", "substances": ["codeina"]},
        ]})
        assert resp.status_code == 422

    def test_validation_rejects_more_than_50_drugs(self, client):
        """Sin tope, `drugs` puede llegar con 1.000 sustancias derivadas de
        `products` y disparar ~500.000 pares en interaction_checker. El mock
        de `check` es defensivo: si la validación no corta, no queremos que
        el test dispare 500.000 pares de verdad."""
        with patch("app.api.interactions.interaction_checker.check", new=AsyncMock()):
            resp = client.post("/interactions", json={
                "drugs": [f"drug{i}" for i in range(51)]})
        assert resp.status_code == 422

    def test_validation_rejects_more_than_50_distinct_substances_from_products(self, client):
        # 3 productos muy por debajo del tope de `products` (50): lo que
        # tiene que cortar acá es el tope de sustancias DISTINTAS derivadas
        # (17*3 = 51), no el de productos.
        productos = [
            {"id": f"p{i}", "substances": [f"sustancia{i}_{j}" for j in range(17)]}
            for i in range(3)
        ]
        with patch("app.api.interactions.interaction_checker.check", new=AsyncMock()):
            resp = client.post("/interactions", json={"products": productos})
        assert resp.status_code == 422


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"

    def test_data_health_connected(self, client, mock_ddinter):
        mock_ddinter.health_check.return_value = True
        resp = client.get("/health/data")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["ddinter"] == "connected"

    def test_data_health_degraded(self, client, mock_ddinter):
        mock_ddinter.health_check.return_value = False
        resp = client.get("/health/data")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["ddinter"] == "unreachable"
