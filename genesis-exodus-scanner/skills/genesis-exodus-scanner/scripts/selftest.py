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


def test_ideal_entry_pullback_case_intc(tmp):
    # Real INTC data from the 2026-07-01 sims: no breakout, so the 50-DMA is the reference.
    entry = fmp_module.compute_ideal_entry(price=127.02, sma50=112.2994, hi20=None, hi55=None)
    ok = (
        entry is not None
        and entry["entry_method"] == "50-day SMA (pullback support)"
        and entry["pct_above_ideal_entry"] == 13.11
        and entry["entry_gate_pass"] is False
    )
    record("fmp: ideal entry uses the 50-DMA when not breaking out (INTC -- fails, too extended)", PASS if ok else FAIL, json.dumps(entry))


def test_ideal_entry_pullback_case_nbis_passes(tmp):
    entry = fmp_module.compute_ideal_entry(price=229.18, sma50=213.9096, hi20=None, hi55=None)
    ok = entry is not None and entry["pct_above_ideal_entry"] == 7.14 and entry["entry_gate_pass"] is True
    record("fmp: ideal entry passes within 8% of the 50-DMA (NBIS)", PASS if ok else FAIL, json.dumps(entry))


def test_ideal_entry_breakout_case_uses_breakout_level(tmp):
    # Confirmed breakout should use the breakout level, not the 50-DMA, even if both are available.
    entry = fmp_module.compute_ideal_entry(price=105.0, sma50=90.0, hi20=100.0, hi55=95.0, breakout20=True)
    ok = (
        entry is not None
        and entry["entry_method"] == "20-day breakout level"
        and entry["ideal_entry"] == 100.0
    )
    record("fmp: ideal entry uses the breakout level (not 50-DMA) when breakout20 is true", PASS if ok else FAIL, json.dumps(entry))


def test_ideal_entry_prefers_55day_breakout_over_20day(tmp):
    entry = fmp_module.compute_ideal_entry(price=110.0, sma50=90.0, hi20=100.0, hi55=105.0, breakout20=True, breakout55=True)
    ok = entry is not None and entry["entry_method"] == "55-day breakout level" and entry["ideal_entry"] == 105.0
    record("fmp: ideal entry prefers the 55-day breakout level over 20-day when both trigger", PASS if ok else FAIL, json.dumps(entry))


def test_ideal_entry_missing_data_fails_closed(tmp):
    entry = fmp_module.compute_ideal_entry(price=100.0, sma50=None, hi20=None, hi55=None)
    ok = entry is None
    record("fmp: ideal entry returns None (gate fails) with no SMA50 or breakout level", PASS if ok else FAIL, json.dumps(entry))


def test_ops_deployable_capital_blocks_below_floor(tmp):
    run_ops(tmp, "live", "on")
    run_ops(tmp, "nav-set", "10000")
    proc = run_ops(tmp, "preflight", "--nav", "10000", "--buying-power", "5")
    data = json.loads(proc.stdout)
    ok = (
        data["new_buys_allowed"] is False
        and data["deployable_capital_ok"] is False
        and "insufficient_deployable_capital" in " ".join(data["reasons"])
    )
    record("ops: preflight blocks buys when buying power is below the $10 deployable floor", PASS if ok else FAIL, json.dumps(data))


def test_ops_deployable_capital_passes_above_floor(tmp):
    proc = run_ops(tmp, "preflight", "--nav", "10000", "--buying-power", "500")
    data = json.loads(proc.stdout)
    ok = data["new_buys_allowed"] is True and data["deployable_capital_ok"] is True
    record("ops: preflight passes once buying power clears the deployable floor", PASS if ok else FAIL, json.dumps(data))


def test_ops_preflight_backward_compatible_without_buying_power(tmp):
    proc = run_ops(tmp, "preflight", "--nav", "10000")
    data = json.loads(proc.stdout)
    ok = data["new_buys_allowed"] is True and data["deployable_capital_ok"] is None
    record("ops: preflight without --buying-power skips the floor check (backward compatible)", PASS if ok else FAIL, json.dumps(data))


def test_confidence_trend_template_fail_is_hard_zero(tmp):
    # TTWO-shaped case: even with excellent other numbers, a failed trend template must zero out.
    conf = fmp_module.compute_confidence(
        trend_template_pass=False, rs_vs_spy=200.0, rr_ratio=5.0,
        pct_above_ideal_entry=0.5, avg_dollar_vol20=50_000_000, earnings_trading_days_out=100,
    )
    ok = conf["confidence"] == 0 and "hard zero" in conf["reason"]
    record("fmp: confidence is a hard zero when trend_template_pass is false", PASS if ok else FAIL, json.dumps(conf))


def test_confidence_nbis_case(tmp):
    # Real NBIS data from the 2026-07-01 sims: strong RS, R:R just over the 2:1 minimum, decent
    # entry, very liquid, earnings comfortably clear.
    conf = fmp_module.compute_confidence(
        trend_template_pass=True, rs_vs_spy=106.2, rr_ratio=2.36,
        pct_above_ideal_entry=7.14, avg_dollar_vol20=4_463_857_521, earnings_trading_days_out=36,
    )
    ok = conf["confidence"] == 8 and conf["components"] == {
        "relative_strength": 2, "risk_reward": 1, "entry_quality": 1,
        "liquidity": 2, "earnings_safety": 2,
    }
    record("fmp: confidence scores 8/10 on the real NBIS case (would pass >=7 if not for the news check)", PASS if ok else FAIL, json.dumps(conf))


def test_confidence_intc_case(tmp):
    # Real INTC data: strong RS, but already failed R:R and entry-extension -- confidence should
    # reflect that even though trend_template_pass is true.
    conf = fmp_module.compute_confidence(
        trend_template_pass=True, rs_vs_spy=173.16, rr_ratio=1.08,
        pct_above_ideal_entry=13.11, avg_dollar_vol20=16_134_998_831, earnings_trading_days_out=22,
    )
    ok = conf["confidence"] == 6
    record("fmp: confidence scores 6/10 on the real INTC case (below the >=7 bar, consistent with its other gate failures)", PASS if ok else FAIL, json.dumps(conf))


def test_confidence_missing_data_fails_closed_per_component(tmp):
    conf = fmp_module.compute_confidence(
        trend_template_pass=True, rs_vs_spy=None, rr_ratio=None,
        pct_above_ideal_entry=None, avg_dollar_vol20=None, earnings_trading_days_out=None,
    )
    ok = conf["confidence"] == 0 and all(v == 0 for v in conf["components"].values())
    record("fmp: confidence scores 0 per-component on missing data, not a crash or a guess", PASS if ok else FAIL, json.dumps(conf))


def test_confidence_all_strong_maxes_at_ten(tmp):
    conf = fmp_module.compute_confidence(
        trend_template_pass=True, rs_vs_spy=200.0, rr_ratio=5.0,
        pct_above_ideal_entry=0.5, avg_dollar_vol20=50_000_000, earnings_trading_days_out=100,
    )
    ok = conf["confidence"] == 10
    record("fmp: confidence maxes at 10/10 when every dimension clears its strong threshold", PASS if ok else FAIL, json.dumps(conf))


def test_biotech_check_not_flagged_for_non_biotech_industry(tmp):
    result = fmp_module.assess_biotech_binary_risk("Drug Manufacturers - General", 309_765_378_129, 10_000_000_000)
    ok = result["flagged"] is False
    record("fmp: biotech check clears non-'Biotechnology' industry (MRK-shaped)", PASS if ok else FAIL, json.dumps(result))


def test_biotech_check_clears_profitable_established_names(tmp):
    # Real REGN/VRTX data: "Biotechnology" industry, but large revenue AND profitable.
    regn = fmp_module.assess_biotech_binary_risk("Biotechnology", 14_342_900_000, 4_504_900_000)
    vrtx = fmp_module.assess_biotech_binary_risk("Biotechnology", 12_074_600_000, 3_953_200_000)
    ok = regn["flagged"] is False and vrtx["flagged"] is False
    record("fmp: biotech check clears profitable, diversified biotechs (REGN/VRTX -- industry alone would wrongly flag these)", PASS if ok else FAIL, json.dumps({"regn": regn, "vrtx": vrtx}))


def test_biotech_check_flags_low_revenue_clinical_stage_names(tmp):
    # Real RCUS/GRAL/XENE/KURA/REPL data: "Biotechnology" industry, revenue well under the floor.
    cases = {
        "RCUS": (247_000_000, -353_000_000),
        "GRAL": (147_172_000, -408_351_000),
        "XENE": (7_500_000, -345_910_000),
        "KURA": (67_482_000, -278_666_000),
        "REPL": (0, -313_940_000),
    }
    results = {sym: fmp_module.assess_biotech_binary_risk("Biotechnology", rev, ni) for sym, (rev, ni) in cases.items()}
    ok = all(r["flagged"] is True for r in results.values())
    record("fmp: biotech check flags real low-revenue clinical-stage names (RCUS/GRAL/XENE/KURA/REPL)", PASS if ok else FAIL, json.dumps(results))


def test_biotech_check_flags_revenue_but_bigger_loss(tmp):
    # Real MRNA data: revenue clears the floor, but net loss exceeds total revenue.
    result = fmp_module.assess_biotech_binary_risk("Biotechnology", 1_944_000_000, -2_822_000_000)
    ok = result["flagged"] is True and "exceeds total revenue" in result["reason"]
    record("fmp: biotech check flags revenue-clearing names whose losses exceed revenue (MRNA)", PASS if ok else FAIL, json.dumps(result))


def test_biotech_check_known_data_quality_blind_spot(tmp):
    # Real ONTX case: FMP's reported revenue ($2.79B) is obviously wrong for a $625M market-cap
    # clinical-stage company -- this heuristic will clear it anyway, which is exactly why it's a
    # mandatory judgment prompt, not an auto-block. This test documents the known limitation.
    result = fmp_module.assess_biotech_binary_risk("Biotechnology", 2_790_000_000, 9_170_000)
    ok = result["flagged"] is False  # documents the blind spot, doesn't pretend it's fixed
    record("fmp: biotech check has a known blind spot on bad upstream data (ONTX) -- by design requires a human read, not just the flag", PASS if ok else FAIL, json.dumps(result))


def test_biotech_check_missing_revenue_flags_for_safety(tmp):
    result = fmp_module.assess_biotech_binary_risk("Biotechnology", None, None)
    ok = result["flagged"] is True
    record("fmp: biotech check flags (fails closed) when revenue data is missing entirely", PASS if ok else FAIL, json.dumps(result))


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
        test_ops_deployable_capital_blocks_below_floor(tmp)
        test_ops_deployable_capital_passes_above_floor(tmp)
        test_ops_preflight_backward_compatible_without_buying_power(tmp)
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
        test_ideal_entry_pullback_case_intc(tmp)
        test_ideal_entry_pullback_case_nbis_passes(tmp)
        test_ideal_entry_breakout_case_uses_breakout_level(tmp)
        test_ideal_entry_prefers_55day_breakout_over_20day(tmp)
        test_ideal_entry_missing_data_fails_closed(tmp)
        test_confidence_trend_template_fail_is_hard_zero(tmp)
        test_confidence_nbis_case(tmp)
        test_confidence_intc_case(tmp)
        test_confidence_missing_data_fails_closed_per_component(tmp)
        test_confidence_all_strong_maxes_at_ten(tmp)
        test_biotech_check_not_flagged_for_non_biotech_industry(tmp)
        test_biotech_check_clears_profitable_established_names(tmp)
        test_biotech_check_flags_low_revenue_clinical_stage_names(tmp)
        test_biotech_check_flags_revenue_but_bigger_loss(tmp)
        test_biotech_check_known_data_quality_blind_spot(tmp)
        test_biotech_check_missing_revenue_flags_for_safety(tmp)

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
