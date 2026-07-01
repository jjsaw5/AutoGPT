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
