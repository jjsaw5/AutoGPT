from datetime import date, timedelta

from smallcap_scanner.metrics import compute_history_metrics
from smallcap_scanner.models import StockCandidate
from smallcap_scanner import scoring


def _rows(prices_newest_first, volumes_newest_first):
    start = date(2026, 7, 1)
    out = []
    for i, (p, v) in enumerate(zip(prices_newest_first, volumes_newest_first)):
        out.append({
            "date": (start - timedelta(days=i)).isoformat(),
            "price": p,
            "volume": v,
        })
    return out


def _grinder(days=150):
    """Steady climber: +0.5%/day with a small dip every 7th day, volume rising."""
    prices, vols = [], []
    price = 1.0
    for i in range(days):
        prices.append(price)
        vols.append(2_000_000 + (days - i) * 20_000)  # newest days have more volume
        price /= 1.005 if i % 7 else 0.999  # walking backward in time
    return _rows(prices, vols)


def _spiker(days=150):
    """Drifting slightly down for months, then +80% in the last 8 trading
    days on huge volume — big returns, no week-over-week consistency."""
    prices, vols = [], []
    for i in range(days):
        if i < 8:
            prices.append(1.8 - i * 0.1)
            vols.append(20_000_000)
        else:
            prices.append(1.0 + (i - 8) * 0.001)  # older days slightly higher
            vols.append(1_000_000)
    return _rows(prices, vols)


def test_insufficient_rows_returns_empty():
    assert compute_history_metrics(_grinder(days=10)) == {}


def test_grinder_metrics_show_steady_climb():
    m = compute_history_metrics(_grinder())
    assert m["ret_3m"] > 0.2
    assert m["ret_6m"] > m["ret_3m"]
    assert m["up_week_ratio"] >= 0.7  # most weeks closed up
    assert m["volume_trend"] > 1.05  # volume building
    assert m["avg_volume_30d"] > 0


def test_spiker_has_returns_but_no_consistency():
    m = compute_history_metrics(_spiker())
    assert m["ret_1m"] > 0.5  # the spike is real
    assert m["up_week_ratio"] < 0.5  # but the climb was not steady
    grind = compute_history_metrics(_grinder())
    assert grind["up_week_ratio"] > m["up_week_ratio"]


def test_avg_volume_30d_excludes_today():
    # Today has a 100x volume spike; the trailing average must not include it.
    prices = [1.0] * 60
    vols = [100_000_000.0] + [1_000_000.0] * 59
    m = compute_history_metrics(_rows(prices, vols))
    assert m["avg_volume_30d"] == 1_000_000.0


def test_volume_surge_prefers_true_trailing_average():
    stock = StockCandidate(
        symbol="X", volume=10_000_000, avg_volume=10_000_000,  # snapshot artifact
        avg_volume_30d=2_000_000,
    )
    assert stock.volume_surge == 5.0


def test_grind_up_outscores_equivalent_spike_on_momentum():
    common = dict(
        price=2.0, price_avg_50=1.6, price_avg_200=1.2,
        volume=3_000_000, avg_volume_30d=1_500_000,
        year_high=3.0, year_low=1.0, history_days=140,
    )
    grinder = StockCandidate(
        symbol="GRIND", ret_3m=0.4, ret_6m=0.8, up_week_ratio=0.75,
        volume_trend=1.8, **common,
    )
    spiker = StockCandidate(
        symbol="SPIKE", ret_3m=0.4, ret_6m=0.8, up_week_ratio=0.35,
        volume_trend=1.8, **common,
    )
    g_score, g_reasons = scoring.score_momentum(grinder)
    s_score, _ = scoring.score_momentum(spiker)
    assert g_score > s_score
    assert any("steady climb" in r for r in g_reasons)


def test_momentum_degrades_gracefully_without_history():
    quote_only = StockCandidate(
        symbol="Q", price=2.0, price_avg_50=1.6, price_avg_200=1.2,
        volume=1_000_000, avg_volume=1_000_000,
    )
    score, _ = scoring.score_momentum(quote_only)
    assert 0 < score < 60  # MA-based points only, no history families
