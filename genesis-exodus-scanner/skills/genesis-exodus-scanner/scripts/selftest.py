#!/usr/bin/env python3
"""
selftest.py -- regression suite for the Genesis + Exodus safety core + data layer.

Run this before trusting a scan:
    python3 scripts/selftest.py

ops.py checks run fully offline against a throwaway state directory (never the
real ~/.claude state). fmp.py checks are network/API-key dependent: if
FMP_API_KEY isn't configured yet, or the network is unreachable, those checks
are reported as SKIPPED rather than FAILED -- this file is meant to be usable
immediately after `git clone`, before you've added your key.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OPS = SCRIPT_DIR / "ops.py"
FMP = SCRIPT_DIR / "fmp.py"

sys.path.insert(0, str(SCRIPT_DIR))
import fmp as fmp_module  # noqa: E402 -- pure-function import for offline unit tests below

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results = []


def record(name, status, detail=""):
    results.append((name, status, detail))
    print(f"[{status}] {name}" + (f" -- {detail}" if detail else ""))


def run_ops(state_dir, *args):
    proc = subprocess.run(
        [sys.executable, str(OPS), *args],
        cwd=str(SCRIPT_DIR),
        env={"GENESIS_STATE_DIR": str(state_dir), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    return proc


def run_fmp(state_dir, *args):
    import os
    env = dict(os.environ)
    env["GENESIS_STATE_DIR"] = str(state_dir)
    proc = subprocess.run(
        [sys.executable, str(FMP), *args],
        cwd=str(SCRIPT_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    return proc


def test_ops_default_state(tmp):
    proc = run_ops(tmp, "status")
    if proc.returncode != 0:
        return record("ops: fresh status", FAIL, proc.stderr.strip())
    data = json.loads(proc.stdout)
    ok = data == {
        "halted": False,
        "halt_reason": None,
        "live_trading": False,
        "consecutive_loss_halt": False,
    }
    record("ops: fresh state defaults to safe (not halted, live off)", PASS if ok else FAIL, json.dumps(data))


def test_ops_preflight_blocks_by_default(tmp):
    proc = run_ops(tmp, "preflight", "--nav", "10000")
    data = json.loads(proc.stdout)
    ok = data["new_buys_allowed"] is False and "live_trading_off" in " ".join(data["reasons"])
    record("ops: preflight blocks buys until live is explicitly on", PASS if ok else FAIL, json.dumps(data))


def test_ops_live_and_preflight_pass(tmp):
    run_ops(tmp, "live", "on")
    run_ops(tmp, "nav-set", "10000")
    proc = run_ops(tmp, "preflight", "--nav", "10050")
    data = json.loads(proc.stdout)
    ok = data["new_buys_allowed"] is True and data["reasons"] == []
    record("ops: preflight passes once live is on + NAV seeded + no breaches", PASS if ok else FAIL, json.dumps(data))


def test_ops_halt_blocks(tmp):
    run_ops(tmp, "halt", "manual test halt")
    proc = run_ops(tmp, "preflight", "--nav", "10050")
    data = json.loads(proc.stdout)
    ok = data["new_buys_allowed"] is False and data["halted"] is True
    record("ops: kill-switch blocks new buys", PASS if ok else FAIL, json.dumps(data))
    run_ops(tmp, "resume")


def test_ops_daily_loss_halt(tmp):
    run_ops(tmp, "live", "on")
    run_ops(tmp, "nav-set", "10000")
    proc = run_ops(tmp, "preflight", "--nav", "9400")  # -6%
    data = json.loads(proc.stdout)
    ok = data["new_buys_allowed"] is False and data["daily_loss_halt"] is True
    record("ops: 5% daily-loss halt trips on drawdown vs baseline", PASS if ok else FAIL, json.dumps(data))


def test_ops_nav_first_write_wins(tmp):
    run_ops(tmp, "nav-set", "10000")
    proc = run_ops(tmp, "nav-set", "20000")
    data = json.loads(proc.stdout)
    ok = data["seeded"] is False
    record("ops: nav-set is first-write-wins per day", PASS if ok else FAIL, json.dumps(data))


def test_ops_consecutive_loss_halt(tmp):
    run_ops(tmp, "live", "on")
    run_ops(tmp, "nav-set", "10000")
    run_ops(tmp, "ledger-add", json.dumps({
        "symbol": "AAA", "outcome": "stop", "realized_pl": -100, "realized_pct": -10, "setup": "genesis"
    }))
    run_ops(tmp, "ledger-add", json.dumps({
        "symbol": "BBB", "outcome": "stop", "realized_pl": -80, "realized_pct": -8, "setup": "genesis"
    }))
    proc = run_ops(tmp, "preflight", "--nav", "10000")
    data = json.loads(proc.stdout)
    ok = data["new_buys_allowed"] is False and data["consecutive_loss_halt"] is True
    record("ops: 2-of-3 stopped trades trips the consecutive-loss halt", PASS if ok else FAIL, json.dumps(data))

    # Scanner must never be able to clear its own halt -- only ack-losses (user-only) can.
    proc2 = run_ops(tmp, "ack-losses", "reviewed, resuming")
    ack_data = json.loads(proc2.stdout)
    proc3 = run_ops(tmp, "preflight", "--nav", "10000")
    data3 = json.loads(proc3.stdout)
    ok2 = ack_data["consecutive_loss_halt"] is False and data3["consecutive_loss_halt"] is False
    record("ops: ack-losses clears the consecutive-loss halt", PASS if ok2 else FAIL, json.dumps(data3))


def test_ops_daily_buy_cap(tmp):
    run_ops(tmp, "live", "on")
    run_ops(tmp, "nav-set", "10000")
    for i in range(3):
        run_ops(tmp, "buy-record", json.dumps({"symbol": f"SYM{i}", "shares": 1, "price": 100}))
    proc = run_ops(tmp, "preflight", "--nav", "10000")
    data = json.loads(proc.stdout)
    ok = data["new_buys_allowed"] is False and "daily_buy_cap_reached" in " ".join(data["reasons"])
    record("ops: daily buy cap (3/day) blocks a 4th buy", PASS if ok else FAIL, json.dumps(data))


def test_ops_ledger_validation(tmp):
    proc = run_ops(tmp, "ledger-add", json.dumps({"symbol": "AAA"}))
    ok = proc.returncode != 0
    record("ops: ledger-add rejects a record missing required fields", PASS if ok else FAIL, proc.stdout.strip())


def test_rr_far_below_high_uses_distance_method(tmp):
    # INTC-shaped case from the 2026-07-01 $1,000 dry run: 10.77% off the 52wk high, no breakout.
    rr = fmp_module.compute_reward_risk(price=127.02, high52=142.35, atr20=11.007)
    ok = (
        rr is not None
        and rr["reward_method"] == "distance to prior 52wk high"
        and abs(rr["reward_pct"] - 10.77) < 0.05
        and rr["rr_ratio"] == 1.08
        and rr["rr_pass"] is False
    )
    record("fmp: R:R uses distance-to-high when not near the high", PASS if ok else FAIL, json.dumps(rr))


def test_rr_far_below_high_clears_2to1(tmp):
    # NBIS-shaped case: 23.57% off the high clears the 2:1 bar on the distance method alone.
    rr = fmp_module.compute_reward_risk(price=229.18, high52=299.86, atr20=28.945)
    ok = rr is not None and rr["rr_ratio"] == 2.36 and rr["rr_pass"] is True
    record("fmp: R:R clears 2:1 when reward >= 2x the 10% stop", PASS if ok else FAIL, json.dumps(rr))


def test_rr_near_high_switches_to_atr_method(tmp):
    # BAC-shaped case: only 1.42% off the high -- distance method would wrongly show ~0 reward,
    # so it must switch to the ATR-multiple projection instead.
    rr = fmp_module.compute_reward_risk(price=58.36, high52=59.2, atr20=1.206)
    ok = rr is not None and "ATR20" in rr["reward_method"] and rr["rr_ratio"] == 0.62
    record("fmp: R:R switches to ATR-multiple method near the 52wk high", PASS if ok else FAIL, json.dumps(rr))


def test_rr_breakout_forces_atr_method_even_if_not_literally_near_high(tmp):
    rr = fmp_module.compute_reward_risk(price=100.0, high52=95.0, atr20=4.0, breakout20=True)
    ok = rr is not None and "ATR20" in rr["reward_method"]
    record("fmp: R:R uses ATR-multiple method on a confirmed breakout", PASS if ok else FAIL, json.dumps(rr))


def test_rr_missing_data_fails_closed(tmp):
    rr_no_high = fmp_module.compute_reward_risk(price=100.0, high52=None, atr20=5.0)
    rr_no_atr_near_high = fmp_module.compute_reward_risk(price=100.0, high52=99.0, atr20=None)
    ok = rr_no_high is None and rr_no_atr_near_high is None
    record(
        "fmp: R:R returns None (gate fails) on missing data instead of guessing",
        PASS if ok else FAIL,
        json.dumps({"rr_no_high": rr_no_high, "rr_no_atr_near_high": rr_no_atr_near_high}),
    )


def test_news_scan_flags_real_negative_catalyst(tmp):
    # Actual NBIS headlines from the 2026-07-01 dry run -- this is the exact case the mandatory
    # news check exists to catch: every quant gate was clean, but the drop was company-specific.
    articles = [
        {
            "title": "Nebius stock is crashing, and it has its biggest customer to blame",
            "text": "Nebius Group (NBIS) stock is under immense pressure this morning mostly "
                    "because of aggressive new competitive threat from its biggest customer.",
        },
        {
            "title": "CoreWeave, Nebius shares tumble as Meta stands to become a fresh threat in the cloud",
            "text": "Artificial-intelligence infrastructure providers like CoreWeave and Nebius "
                    "Group may soon face stiff competition from a new kid on the block: Meta.",
        },
        {
            "title": "Russell 2000 Kicks off 3rd Quarter With Record High",
            "text": "Stocks are firmly higher as July trading gets underway.",
        },
    ]
    result = fmp_module.scan_news_for_negative_catalysts(articles)
    ok = (
        result["flagged"] is True
        and "threat" in result["matched_keywords"]
        and "tumble" in result["matched_keywords"]
        and len(result["matched_articles"]) == 2  # the record-high article shouldn't match
    )
    record("fmp: news keyword scan flags the real NBIS negative-catalyst headlines", PASS if ok else FAIL, json.dumps(result))


def test_news_scan_clean_when_no_keywords_present(tmp):
    articles = [
        {"title": "Company announces new product line", "text": "Sales expected to grow steadily."},
        {"title": "Analyst maintains buy rating", "text": "Price target raised to $150."},
    ]
    result = fmp_module.scan_news_for_negative_catalysts(articles)
    ok = result["flagged"] is False and result["matched_keywords"] == [] and result["matched_articles"] == []
    record("fmp: news keyword scan stays clean with no negative-catalyst language", PASS if ok else FAIL, json.dumps(result))


def test_news_scan_handles_empty_input(tmp):
    result = fmp_module.scan_news_for_negative_catalysts([])
    ok = result["flagged"] is False and result["matched_keywords"] == []
    record("fmp: news keyword scan handles an empty article list", PASS if ok else FAIL, json.dumps(result))


def test_liquidity_check_passes_above_floor(tmp):
    ok = fmp_module.check_liquidity(5_000_000) is True
    record("fmp: liquidity check passes above the $3M/day floor", PASS if ok else FAIL, "avg_dollar_vol20=5,000,000")


def test_liquidity_check_fails_below_floor(tmp):
    ok = fmp_module.check_liquidity(500_000) is False
    record("fmp: liquidity check fails below the $3M/day floor", PASS if ok else FAIL, "avg_dollar_vol20=500,000")


def test_liquidity_check_fails_closed_on_missing_data(tmp):
    ok = fmp_module.check_liquidity(None) is False
    record("fmp: liquidity check fails closed on missing data", PASS if ok else FAIL, "avg_dollar_vol20=None")


def test_fmp_key_missing_is_graceful(tmp):
    proc = run_fmp(tmp, "regime")
    if proc.returncode == 0:
        record("fmp: behavior without FMP_API_KEY", SKIP, "a key is already configured; live-checking instead")
        return
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return record("fmp: missing-key error is valid JSON", FAIL, proc.stdout[:200])
    ok = "error" in data and "FMP_API_KEY" in data["error"]
    record("fmp: missing key fails clearly instead of guessing data", PASS if ok else FAIL, json.dumps(data))


def test_fmp_live_regime(tmp):
    import os
    has_key = bool(os.environ.get("FMP_API_KEY")) or (SCRIPT_DIR.parent / "state" / "fmp.env").exists()
    if not has_key:
        return record("fmp: live regime call (SPY/QQQ/IWM + VIX)", SKIP, "no FMP_API_KEY configured yet")
    proc = run_fmp(tmp, "regime")
    if proc.returncode != 0:
        return record("fmp: live regime call (SPY/QQQ/IWM + VIX)", SKIP, f"network/API unavailable: {proc.stdout[:200]}")
    data = json.loads(proc.stdout)
    ok = data.get("regime") in ("normal", "cautious", "defensive", "crash")
    record("fmp: live regime call (SPY/QQQ/IWM + VIX)", PASS if ok else FAIL, json.dumps(data))


def test_fmp_live_screener_has_leaders(tmp):
    import os
    has_key = bool(os.environ.get("FMP_API_KEY")) or (SCRIPT_DIR.parent / "state" / "fmp.env").exists()
    if not has_key:
        return record("fmp: screener returns a real, non-empty universe", SKIP, "no FMP_API_KEY configured yet")
    proc = run_fmp(tmp, "screener", "--marketCapMoreThan", "10000000000", "--volumeMoreThan", "1000000", "--limit", "10")
    if proc.returncode != 0:
        return record("fmp: screener returns a real, non-empty universe", SKIP, f"network/API unavailable: {proc.stdout[:200]}")
    data = json.loads(proc.stdout)
    ok = isinstance(data, list) and len(data) > 0
    record("fmp: screener returns a real, non-empty universe", PASS if ok else FAIL, f"{len(data) if isinstance(data, list) else 'n/a'} rows")


def main():
    with tempfile.TemporaryDirectory(prefix="genesis-selftest-") as tmp_str:
        tmp = Path(tmp_str)
        test_ops_default_state(tmp)
        test_ops_preflight_blocks_by_default(tmp)
        test_ops_live_and_preflight_pass(tmp)
        test_ops_halt_blocks(tmp)
        test_ops_daily_loss_halt(tmp)
        test_ops_nav_first_write_wins(tmp)
        test_ops_consecutive_loss_halt(tmp)
        test_ops_daily_buy_cap(tmp)
        test_ops_ledger_validation(tmp)
        test_rr_far_below_high_uses_distance_method(tmp)
        test_rr_far_below_high_clears_2to1(tmp)
        test_rr_near_high_switches_to_atr_method(tmp)
        test_rr_breakout_forces_atr_method_even_if_not_literally_near_high(tmp)
        test_rr_missing_data_fails_closed(tmp)
        test_news_scan_flags_real_negative_catalyst(tmp)
        test_news_scan_clean_when_no_keywords_present(tmp)
        test_news_scan_handles_empty_input(tmp)
        test_liquidity_check_passes_above_floor(tmp)
        test_liquidity_check_fails_below_floor(tmp)
        test_liquidity_check_fails_closed_on_missing_data(tmp)

    with tempfile.TemporaryDirectory(prefix="genesis-selftest-fmp-") as tmp_str2:
        tmp2 = Path(tmp_str2)
        test_fmp_key_missing_is_graceful(tmp2)
        test_fmp_live_regime(tmp2)
        test_fmp_live_screener_has_leaders(tmp2)

    failed = [r for r in results if r[1] == FAIL]
    skipped = [r for r in results if r[1] == SKIP]
    passed = [r for r in results if r[1] == PASS]
    print()
    print(f"{len(passed)} passed, {len(failed)} failed, {len(skipped)} skipped")
    if failed:
        print("\nFAILED:")
        for name, _, detail in failed:
            print(f"  - {name}: {detail}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
