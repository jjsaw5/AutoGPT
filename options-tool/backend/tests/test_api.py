"""FastAPI integration smoke test — uses the default Mock provider."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import reset_provider_cache
from app.main import app


def test_health() -> None:
    reset_provider_cache()
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_root_returns_educational_banner() -> None:
    reset_provider_cache()
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert "Educational" in body["banner"]
    assert "Paper trading" in body["banner"]


def test_analyze_returns_setup_for_default_mock() -> None:
    reset_provider_cache()
    client = TestClient(app)
    resp = client.post("/api/analyze", json={"ticker": "SPY", "bias": "neutral"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "SPY"
    assert "Educational" in body["banner"]
    # Mock base_iv=0.30 with history range 0.18-0.55 -> IVR ~32, condor band.
    assert body["setup"] is not None
    assert body["setup"]["strategy"] in {"iron_condor", "skip"}


def test_unified_analyze_returns_all_five_strategists() -> None:
    reset_provider_cache()
    client = TestClient(app)
    resp = client.post("/api/unified-analyze", json={"ticker": "SPY", "bias": "neutral"})
    assert resp.status_code == 200
    body = resp.json()
    names = {r["name"] for r in body["results"]}
    assert names == {"sosnoff", "thorp", "saliba", "high_volume", "zero_dte"}
    for r in body["results"]:
        assert r["headline"]
    assert "Educational" in body["banner"]
