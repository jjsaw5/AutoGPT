import json
from datetime import date

from smallcap_scanner.models import RedditSignal
from smallcap_scanner import scoring
from smallcap_scanner.trend import (
    annotate_signals,
    load_social_snapshots,
    trend_report,
)


def _social_row(symbol, mentions):
    return {"symbol": symbol, "mentions_total": mentions, "mentions_recent": 1,
            "subreddits": ["pennystocks"]}


def _write_scan(dirpath, day, rows, suffix=""):
    payload = {"fundamentals": [], "social": rows, "combined": []}
    (dirpath / f"scan_{day}{suffix}.json").write_text(json.dumps(payload))


def _seed_scans(tmp_path):
    # SLS on all three days with growing mentions; GRND only on day 2.
    _write_scan(tmp_path, "2026-06-28", [_social_row("SLS", 10)])
    _write_scan(tmp_path, "2026-06-29",
                [_social_row("SLS", 15), _social_row("GRND", 5)])
    # Two files on the same day (morning + EOD) must merge into one scan-day.
    _write_scan(tmp_path, "2026-07-01", [_social_row("SLS", 25)])
    _write_scan(tmp_path, "2026-07-01", [_social_row("SLS", 30)], suffix="_eod")


def test_snapshots_group_and_merge_by_date(tmp_path):
    _seed_scans(tmp_path)
    snaps = load_social_snapshots(str(tmp_path))
    assert set(snaps) == {date(2026, 6, 28), date(2026, 6, 29), date(2026, 7, 1)}
    # Later same-day file wins.
    assert snaps[date(2026, 7, 1)]["SLS"]["mentions_total"] == 30


def test_bare_social_list_files_are_loaded(tmp_path):
    # `social --out FILE` writes a bare list, not the all-payload dict.
    (tmp_path / "scan_2026-06-30.json").write_text(
        json.dumps([_social_row("SLS", 12)])
    )
    snaps = load_social_snapshots(str(tmp_path))
    assert snaps[date(2026, 6, 30)]["SLS"]["mentions_total"] == 12


def test_annotate_signals_persistence_and_growth(tmp_path):
    _seed_scans(tmp_path)
    live = [RedditSignal(symbol="SLS", mentions_total=40),
            RedditSignal(symbol="NEWCO", mentions_total=8)]
    annotate_signals(live, str(tmp_path), lookback_days=14,
                     today=date(2026, 7, 2))
    sls, newco = live
    # Present today + all 3 prior scan-days -> seen 4, unbroken streak of 4.
    assert sls.days_seen == 4
    assert sls.streak_days == 4
    # growth = 40 / mean(10, 15, 30)
    assert abs(sls.mention_growth - 40 / ((10 + 15 + 30) / 3)) < 1e-6
    # Never seen before: only today counts, no growth baseline.
    assert newco.days_seen == 1
    assert newco.streak_days == 1
    assert newco.mention_growth is None


def test_streak_breaks_on_missed_scan_day(tmp_path):
    _seed_scans(tmp_path)
    live = [RedditSignal(symbol="GRND", mentions_total=9)]
    annotate_signals(live, str(tmp_path), lookback_days=14,
                     today=date(2026, 7, 2))
    g = live[0]
    # GRND appeared only on 06-29; it was absent on the 07-01 scan-day, so
    # the streak is just today even though it was seen twice overall.
    assert g.days_seen == 2
    assert g.streak_days == 1


def test_persistent_signal_outscores_identical_one_day_signal():
    base = dict(mentions_total=20, mentions_recent=10, upvotes_sum=100,
                subreddits=["pennystocks", "wallstreetbets"])
    steady = RedditSignal(symbol="A", days_seen=4, streak_days=4,
                          mention_growth=2.0, **base)
    one_day = RedditSignal(symbol="B", **base)
    s_steady, reasons = scoring.score_social(steady)
    s_once, _ = scoring.score_social(one_day)
    assert s_steady > s_once
    assert any("scan-days in a row" in r for r in reasons)


def test_trend_report_ranks_by_persistence(tmp_path):
    _seed_scans(tmp_path)
    rows = trend_report(str(tmp_path), lookback_days=14, min_days=1)
    by_symbol = {r.symbol: r for r in rows}
    assert rows[0].symbol == "SLS"  # longest streak first
    assert by_symbol["SLS"].days_seen == 3
    assert by_symbol["SLS"].streak_days == 3
    assert by_symbol["GRND"].streak_days == 0  # absent on the latest scan-day
    # min_days=2 filters GRND (seen once) out.
    assert all(r.days_seen >= 2 for r in trend_report(str(tmp_path), 14, 2))


def test_missing_scans_dir_is_harmless(tmp_path):
    live = [RedditSignal(symbol="SLS", mentions_total=5)]
    annotated = annotate_signals(live, str(tmp_path / "nope"), 14,
                                 today=date(2026, 7, 2))
    assert annotated == 0
    assert trend_report(str(tmp_path / "nope")) == []
