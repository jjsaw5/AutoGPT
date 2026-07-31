"""Store tests.

These run real SQL against local SQLite rather than mocking the database,
because Turso *is* SQLite (3.45.1) and the same statements execute on both.
The wire-encoding layer that differs is tested separately.
"""

from datetime import datetime

import pytest

from odte.config import DEFAULT_CONFIG, MARKET_TZ
from odte.models import Decision, Levels, Regime, RegimeScore
from odte.signal import evaluate
from odte.store import SignalStore, SqliteExecutor, StoreError, _decode, _encode


def at(hour, minute, day=31):
    return datetime(2026, 7, day, hour, minute, tzinfo=MARKET_TZ)


def bullish_levels(**overrides):
    base = dict(
        premarket_high=738.0,
        premarket_low=730.0,
        ema_fast=739.0,
        ema_slow=737.0,
        sma_daily=700.0,
        vwap=738.0,
        atr=2.0,
        price=741.0,
    )
    base.update(overrides)
    return Levels(**base)


BULL = RegimeScore(
    regime=Regime.STRONG_BULL,
    score=0.6,
    sector_rs=0.8,
    breadth=0.5,
    qqq_rs=0.4,
    detail="STRONG_BULL",
)
NEUTRAL = RegimeScore(
    regime=Regime.NEUTRAL,
    score=0.05,
    sector_rs=0,
    breadth=0,
    qqq_rs=0,
    detail="NEUTRAL",
)


@pytest.fixture
def store():
    s = SignalStore(SqliteExecutor(":memory:"))
    s.migrate()
    return s


def test_encode_covers_the_libsql_wire_types():
    assert _encode(None) == {"type": "null", "value": None}
    assert _encode(3) == {"type": "integer", "value": "3"}
    assert _encode(True) == {"type": "integer", "value": "1"}
    assert _encode(1.5) == {"type": "float", "value": 1.5}
    assert _encode("x") == {"type": "text", "value": "x"}


def test_decode_round_trips():
    assert _decode({"type": "null", "value": None}) is None
    assert _decode({"type": "integer", "value": "42"}) == 42
    assert _decode({"type": "float", "value": 1.5}) == 1.5
    assert _decode({"type": "text", "value": "hi"}) == "hi"


def test_migrate_is_idempotent(store):
    store.migrate()
    store.migrate()


def test_records_a_trade_signal_with_its_plan(store):
    signal = evaluate("SPY", at(10, 0), bullish_levels(), BULL, DEFAULT_CONFIG)
    store.record_signal(signal)

    rows = store._db.execute("SELECT * FROM signals")
    assert len(rows) == 1
    assert rows[0]["decision"] == "LONG_CALL"
    assert rows[0]["blocking_gate"] is None
    assert rows[0]["plan_json"] is not None
    assert rows[0]["session_date"] == "2026-07-31"


def test_records_no_trades_and_names_the_blocking_gate(store):
    """The rejections are the half worth keeping."""
    signal = evaluate("SPY", at(10, 0), bullish_levels(), NEUTRAL, DEFAULT_CONFIG)
    store.record_signal(signal)

    rows = store._db.execute("SELECT decision, blocking_gate, plan_json FROM signals")
    assert rows[0]["decision"] == "NO_TRADE"
    assert rows[0]["blocking_gate"] == "regime"
    assert rows[0]["plan_json"] is None


def test_rerunning_the_same_minute_updates_rather_than_duplicates(store):
    """A retried cron tick must not inflate the sample."""
    signal = evaluate("SPY", at(10, 0), bullish_levels(), NEUTRAL, DEFAULT_CONFIG)
    store.record_signal(signal)
    store.record_signal(signal)

    better = evaluate("SPY", at(10, 0), bullish_levels(), BULL, DEFAULT_CONFIG)
    store.record_signal(better)

    rows = store._db.execute("SELECT decision FROM signals")
    assert len(rows) == 1
    assert rows[0]["decision"] == "LONG_CALL"


def test_two_symbols_at_the_same_minute_are_separate_rows(store):
    store.record_signal(evaluate("SPY", at(10, 0), bullish_levels(), BULL))
    store.record_signal(evaluate("QQQ", at(10, 0), bullish_levels(), BULL))
    assert len(store._db.execute("SELECT * FROM signals")) == 2


def test_blocking_gate_histogram_ranks_the_common_refusals(store):
    store.record_signal(evaluate("SPY", at(10, 0), bullish_levels(), NEUTRAL))
    store.record_signal(evaluate("SPY", at(10, 5), bullish_levels(), NEUTRAL))
    store.record_signal(evaluate("SPY", at(12, 0), bullish_levels(), BULL))

    counts = store.blocking_gate_counts()
    assert counts[0]["gate"] == "regime"
    assert counts[0]["n"] == 2
    assert {c["gate"] for c in counts} == {"regime", "timing"}


def test_trade_lifecycle_computes_pnl(store):
    store.record_entry(
        symbol="SPY",
        session_date="2026-07-31",
        direction=1,
        quantity=4,
        entry_premium=2.00,
        entry_at=at(10, 0),
        conviction=90,
    )
    trade_id = store._db.execute("SELECT id FROM trades")[0]["id"]
    assert len(store.open_trades()) == 1

    store.close_trade(
        trade_id, exit_premium=2.60, exit_at=at(10, 20), exit_reason="target"
    )

    row = store._db.execute("SELECT * FROM trades")[0]
    assert row["pnl"] == pytest.approx(240.0)  # 0.60 * 100 * 4
    assert row["pnl_pct"] == pytest.approx(0.30)
    assert store.open_trades() == []


def test_losing_trade_has_negative_pnl(store):
    store.record_entry(
        symbol="SPY",
        session_date="2026-07-31",
        direction=1,
        quantity=2,
        entry_premium=2.00,
        entry_at=at(10, 0),
    )
    trade_id = store._db.execute("SELECT id FROM trades")[0]["id"]
    store.close_trade(trade_id, 1.50, at(10, 25), "stop")
    assert store._db.execute("SELECT pnl FROM trades")[0]["pnl"] == pytest.approx(
        -100.0
    )


def test_closing_an_unknown_trade_raises(store):
    with pytest.raises(StoreError):
        store.close_trade(999, 1.0, at(10, 0), "stop")


def test_counts_today_feeds_the_risk_budget_gate(store):
    for premium, exit_premium in [(2.0, 2.6), (2.0, 1.5), (2.0, 1.6)]:
        store.record_entry(
            symbol="SPY",
            session_date="2026-07-31",
            direction=1,
            quantity=1,
            entry_premium=premium,
            entry_at=at(10, 0),
        )
    for trade_id, exit_premium in enumerate([2.6, 1.5, 1.6], start=1):
        store.close_trade(trade_id, exit_premium, at(10, 30), "x")

    taken, losses = store.counts_today("2026-07-31")
    assert taken == 3
    assert losses == 2


def test_counts_today_ignores_other_sessions(store):
    store.record_entry(
        symbol="SPY",
        session_date="2026-07-30",
        direction=1,
        quantity=1,
        entry_premium=2.0,
        entry_at=at(10, 0, day=30),
    )
    assert store.counts_today("2026-07-31") == (0, 0)


def test_performance_summarises_closed_trades_only(store):
    store.record_entry(
        symbol="SPY",
        session_date="2026-07-31",
        direction=1,
        quantity=1,
        entry_premium=2.0,
        entry_at=at(10, 0),
    )
    store.record_entry(
        symbol="SPY",
        session_date="2026-07-31",
        direction=1,
        quantity=1,
        entry_premium=2.0,
        entry_at=at(14, 0),
    )
    store.close_trade(1, 2.6, at(10, 20), "target")

    summary = store.performance()[0]
    assert summary["trades"] == 1
    assert summary["wins"] == 1
    assert summary["net_pnl"] == pytest.approx(60.0)


def test_performance_by_conviction_buckets(store):
    for conviction, exit_premium in [(90, 2.6), (50, 1.5)]:
        store.record_entry(
            symbol="SPY",
            session_date="2026-07-31",
            direction=1,
            quantity=1,
            entry_premium=2.0,
            entry_at=at(10, 0),
            conviction=conviction,
        )
    store.close_trade(1, 2.6, at(10, 20), "target")
    store.close_trade(2, 1.5, at(10, 25), "stop")

    buckets = {r["bucket"]: r for r in store.performance_by_conviction()}
    assert buckets["high (80+)"]["wins"] == 1
    assert buckets["low (<60)"]["wins"] == 0


def test_performance_by_window_splits_on_the_midday_break(store):
    store.record_entry(
        symbol="SPY",
        session_date="2026-07-31",
        direction=1,
        quantity=1,
        entry_premium=2.0,
        entry_at=at(10, 0),
    )
    store.record_entry(
        symbol="SPY",
        session_date="2026-07-31",
        direction=1,
        quantity=1,
        entry_premium=2.0,
        entry_at=at(14, 0),
    )
    store.close_trade(1, 2.6, at(10, 20), "target")
    store.close_trade(2, 1.5, at(14, 20), "stop")

    windows = {r["window"]: r for r in store.performance_by_window()}
    assert windows["morning"]["wins"] == 1
    assert windows["afternoon"]["wins"] == 0


def test_signal_id_lookup(store):
    signal = evaluate("SPY", at(10, 0), bullish_levels(), BULL)
    store.record_signal(signal)
    assert store.signal_id("SPY", at(10, 0)) is not None
    assert store.signal_id("QQQ", at(10, 0)) is None
