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


def test_risk_dashboard_empty_by_default() -> None:
    reset_provider_cache()
    client = TestClient(app)
    resp = client.post(
        "/api/risk/dashboard",
        json={
            "account": {
                "cash": 100_000,
                "kelly_fraction": 0.25,
                "max_pct_per_trade": 0.05,
                "max_total_deployed_pct": 0.5,
            }
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["open_positions"] == 0
    assert body["greeks"]["delta"] == 0.0


def test_bankroll_status_returns_default_budgets() -> None:
    reset_provider_cache()
    client = TestClient(app)
    resp = client.post(
        "/api/bankroll/status",
        json={
            "account": {
                "cash": 100_000,
                "kelly_fraction": 0.25,
                "max_pct_per_trade": 0.05,
                "max_total_deployed_pct": 0.5,
            }
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    names = {a["name"] for a in body["allocations"]}
    assert names == {"sosnoff", "saliba", "thorp", "high_volume", "zero_dte"}
    assert body["total_cap"] == 50_000  # 50% of $100k


def test_backtest_run_returns_metrics_and_equity_curve() -> None:
    reset_provider_cache()
    client = TestClient(app)
    resp = client.post(
        "/api/backtest/run",
        json={
            "ticker": "SPY",
            "strategist": "saliba",
            "start": "2025-06-02",
            "end": "2025-07-15",
            "account": {
                "cash": 100_000,
                "kelly_fraction": 0.25,
                "max_pct_per_trade": 0.05,
                "max_total_deployed_pct": 0.5,
            },
            "fixed_contracts": 1,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert {"cagr", "max_drawdown", "sharpe", "sortino", "win_rate", "profit_factor", "trades"} <= set(
        body["metrics"].keys()
    )
    assert body["trade_count"] >= 1
    assert len(body["equity_curve"]) > 0


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
