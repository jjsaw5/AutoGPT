#!/usr/bin/env python3
"""
ops.py -- Project Genesis + Exodus safety core.

Deterministic gates for the trading scanner: kill-switch, live-trading flag,
NAV baseline / daily-loss halt, consecutive-loss halt, and the daily buy cap.

This script deliberately contains NO market judgment -- it only reads/writes
state/*.json(l) and answers yes/no questions. The scanning skill is required
to call `preflight` before placing any buy and to obey `new_buys_allowed`.

State directory resolution: sibling `state/` next to this script's parent,
overridable with the GENESIS_STATE_DIR environment variable (used by
selftest.py so tests never touch real state).
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(os.environ.get("GENESIS_STATE_DIR") or (Path(__file__).resolve().parent.parent / "state"))
CONTROL_FILE = STATE_DIR / "control.json"
NAV_FILE = STATE_DIR / "nav_baseline.json"
LEDGER_FILE = STATE_DIR / "ledger.jsonl"
BUYS_FILE = STATE_DIR / "buys_today.json"

DEFAULT_CONTROL = {
    "halted": False,
    "halt_reason": None,
    "live_trading": False,
    "consecutive_loss_halt": False,
    "consecutive_loss_ack_note": None,
}

# CUSTOMIZE: tune these to your backtested risk profile.
DAILY_LOSS_HALT_PCT = 5.0
DAILY_BUY_CAP = 3
CONSECUTIVE_LOOKBACK = 3
CONSECUTIVE_LOSS_THRESHOLD = 2

# Smallest buying power worth running discovery for at all -- previously undefined prose ("BP
# below your smallest-deployable floor"). Derived from fmp.py's UNIVERSE_PRICE_FLOOR ($5): the
# whole-share rule requires >=2 shares, so $10 is the absolute floor below which no valid buy
# exists anywhere in our own universe. Kept in sync manually (ops.py and fmp.py are independent
# CLIs, not a shared import) -- if you change UNIVERSE_PRICE_FLOOR, update this too.
DEPLOYABLE_CAPITAL_FLOOR = 10.0


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def today_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def ensure_state_dir():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "cache").mkdir(parents=True, exist_ok=True)


def load_json(path, default):
    if not path.exists():
        return json.loads(json.dumps(default))
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(default))


def save_json(path, data):
    ensure_state_dir()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    tmp.replace(path)


def load_control():
    c = load_json(CONTROL_FILE, DEFAULT_CONTROL)
    for k, v in DEFAULT_CONTROL.items():
        c.setdefault(k, v)
    return c


def save_control(c):
    save_json(CONTROL_FILE, c)


def load_ledger():
    if not LEDGER_FILE.exists():
        return []
    trades = []
    with open(LEDGER_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                trades.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return trades


def append_ledger(record):
    ensure_state_dir()
    with open(LEDGER_FILE, "a") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def _consecutive_loss_tripped():
    trades = load_ledger()
    recent = trades[-CONSECUTIVE_LOOKBACK:]
    if len(recent) < CONSECUTIVE_LOSS_THRESHOLD:
        return False
    losses = sum(1 for t in recent if t.get("outcome") in ("loss", "stop"))
    return losses >= CONSECUTIVE_LOSS_THRESHOLD


def out(obj):
    print(json.dumps(obj, indent=2, sort_keys=True))


# ---------------------------------------------------------------- commands

def cmd_halt(args):
    c = load_control()
    c["halted"] = True
    c["halt_reason"] = args.reason
    c["halted_at"] = now_iso()
    save_control(c)
    out({"halted": True, "reason": args.reason})


def cmd_resume(args):
    c = load_control()
    c["halted"] = False
    c["halt_reason"] = None
    c["resumed_at"] = now_iso()
    save_control(c)
    out({"halted": False})


def cmd_live(args):
    c = load_control()
    c["live_trading"] = args.state == "on"
    save_control(c)
    out({"live_trading": c["live_trading"]})


def cmd_ack_losses(args):
    """User-only. The scanner must never call this itself."""
    c = load_control()
    c["consecutive_loss_halt"] = False
    c["consecutive_loss_ack_note"] = args.note
    c["consecutive_loss_ack_at"] = now_iso()
    save_control(c)
    out({"consecutive_loss_halt": False, "note": args.note})


def cmd_nav_set(args):
    """First-write-wins: seeds the session-open NAV baseline once per day."""
    nav = load_json(NAV_FILE, {})
    today = today_str()
    if nav.get("date") == today and "baseline_nav" in nav:
        out({"seeded": False, "reason": "already seeded today", **nav})
        return
    nav = {"date": today, "baseline_nav": args.nav, "seeded_at": now_iso()}
    save_json(NAV_FILE, nav)
    out({"seeded": True, **nav})


def cmd_nav_check(args):
    nav = load_json(NAV_FILE, {})
    if nav.get("date") != today_str() or "baseline_nav" not in nav:
        out({"baseline_set": False})
        return
    baseline = nav["baseline_nav"]
    drawdown_pct = round((baseline - args.nav) / baseline * 100, 3) if baseline else 0.0
    out({
        "baseline_set": True,
        "baseline_nav": baseline,
        "current_nav": args.nav,
        "drawdown_pct": drawdown_pct,
        "daily_loss_halt": drawdown_pct >= DAILY_LOSS_HALT_PCT,
    })


def cmd_buy_record(args):
    try:
        record = json.loads(args.json)
    except json.JSONDecodeError as e:
        out({"error": f"invalid json: {e}"})
        sys.exit(1)
    buys = load_json(BUYS_FILE, {})
    today = today_str()
    if buys.get("date") != today:
        buys = {"date": today, "count": 0, "buys": []}
    record["recorded_at"] = now_iso()
    buys["buys"].append(record)
    buys["count"] = len(buys["buys"])
    save_json(BUYS_FILE, buys)
    out({"recorded": True, "count_today": buys["count"], "daily_buy_cap": DAILY_BUY_CAP})


def cmd_buys_today(args):
    buys = load_json(BUYS_FILE, {})
    if buys.get("date") != today_str():
        out({"date": today_str(), "count": 0, "buys": []})
        return
    out(buys)


def cmd_ledger_add(args):
    try:
        record = json.loads(args.json)
    except json.JSONDecodeError as e:
        out({"error": f"invalid json: {e}"})
        sys.exit(1)
    required = {"symbol", "outcome", "realized_pl", "realized_pct", "setup"}
    missing = required - record.keys()
    if missing:
        out({"error": f"missing fields: {sorted(missing)}"})
        sys.exit(1)
    if record["outcome"] not in ("win", "loss", "stop"):
        out({"error": "outcome must be one of: win, loss, stop"})
        sys.exit(1)
    record.setdefault("closed_at", now_iso())
    append_ledger(record)

    c = load_control()
    if _consecutive_loss_tripped():
        c["consecutive_loss_halt"] = True
        save_control(c)
    out({"recorded": True, "consecutive_loss_halt": c.get("consecutive_loss_halt", False)})


def cmd_ledger_recent(args):
    trades = load_ledger()
    out(trades[-args.n:])


def cmd_perf(args):
    trades = load_ledger()
    if not trades:
        out({"trades": 0})
        return
    wins = [t for t in trades if t.get("outcome") == "win"]
    losses = [t for t in trades if t.get("outcome") in ("loss", "stop")]
    out({
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2),
        "total_realized_pl": round(sum(t.get("realized_pl", 0) for t in trades), 2),
        "avg_realized_pct": round(sum(t.get("realized_pct", 0) for t in trades) / len(trades), 2),
    })


def cmd_status(args):
    c = load_control()
    out({
        "halted": c["halted"],
        "halt_reason": c.get("halt_reason"),
        "live_trading": c["live_trading"],
        "consecutive_loss_halt": c.get("consecutive_loss_halt", False),
    })


def cmd_preflight(args):
    c = load_control()
    reasons = []

    if c["halted"]:
        reasons.append(f"kill_switch_engaged: {c.get('halt_reason') or 'no reason given'}")
    if not c["live_trading"]:
        reasons.append("live_trading_off (run: ops.py live on)")
    if c.get("consecutive_loss_halt"):
        reasons.append("consecutive_loss_halt (needs: ops.py ack-losses \"<note>\")")

    nav = load_json(NAV_FILE, {})
    daily_loss_halt = False
    drawdown_pct = 0.0
    nav_seeded_today = nav.get("date") == today_str() and "baseline_nav" in nav
    if nav_seeded_today and nav["baseline_nav"]:
        drawdown_pct = round((nav["baseline_nav"] - args.nav) / nav["baseline_nav"] * 100, 3)
        if drawdown_pct >= DAILY_LOSS_HALT_PCT:
            daily_loss_halt = True
            reasons.append(f"daily_loss_halt ({drawdown_pct}% drawdown >= {DAILY_LOSS_HALT_PCT}%)")

    buys = load_json(BUYS_FILE, {})
    buys_today = buys["count"] if buys.get("date") == today_str() else 0
    if buys_today >= DAILY_BUY_CAP:
        reasons.append(f"daily_buy_cap_reached ({buys_today}/{DAILY_BUY_CAP})")

    deployable_capital_ok = None
    if args.buying_power is not None:
        deployable_capital_ok = args.buying_power >= DEPLOYABLE_CAPITAL_FLOOR
        if not deployable_capital_ok:
            reasons.append(
                f"insufficient_deployable_capital (${args.buying_power} < "
                f"${DEPLOYABLE_CAPITAL_FLOOR} floor -- fast-path to monitoring only, skip discovery)"
            )

    out({
        "new_buys_allowed": len(reasons) == 0,
        "reasons": reasons,
        "halted": c["halted"],
        "live_trading": c["live_trading"],
        "consecutive_loss_halt": c.get("consecutive_loss_halt", False),
        "nav_baseline_seeded_today": nav_seeded_today,
        "daily_loss_halt": daily_loss_halt,
        "drawdown_pct": drawdown_pct,
        "buys_today": buys_today,
        "daily_buy_cap": DAILY_BUY_CAP,
        "buying_power": args.buying_power,
        "deployable_capital_floor": DEPLOYABLE_CAPITAL_FLOOR,
        "deployable_capital_ok": deployable_capital_ok,
    })


# ------------------------------------------------------------------- CLI

def build_parser():
    p = argparse.ArgumentParser(prog="ops.py", description="Genesis + Exodus safety core")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("preflight", help="consolidated buy-gate verdict")
    sp.add_argument("--nav", type=float, required=True, dest="nav")
    sp.add_argument("--buying-power", type=float, default=None, dest="buying_power",
                     help="confirmed buying power; omit to skip the deployable-capital floor check")
    sp.set_defaults(func=cmd_preflight)

    sp = sub.add_parser("nav-set", help="seed today's NAV baseline (first-write-wins)")
    sp.add_argument("nav", type=float)
    sp.set_defaults(func=cmd_nav_set)

    sp = sub.add_parser("nav-check", help="drawdown vs today's baseline")
    sp.add_argument("nav", type=float)
    sp.set_defaults(func=cmd_nav_check)

    sp = sub.add_parser("halt", help="engage the durable kill-switch")
    sp.add_argument("reason")
    sp.set_defaults(func=cmd_halt)

    sp = sub.add_parser("resume", help="disengage the durable kill-switch")
    sp.set_defaults(func=cmd_resume)

    sp = sub.add_parser("live", help="master live-trading flag")
    sp.add_argument("state", choices=["on", "off"])
    sp.set_defaults(func=cmd_live)

    sp = sub.add_parser("ack-losses", help="user-only: clear a tripped consecutive-loss breaker")
    sp.add_argument("note")
    sp.set_defaults(func=cmd_ack_losses)

    sp = sub.add_parser("ledger-add", help="append a closed trade")
    sp.add_argument("json")
    sp.set_defaults(func=cmd_ledger_add)

    sp = sub.add_parser("ledger-recent", help="last N closed trades")
    sp.add_argument("-n", type=int, default=10)
    sp.set_defaults(func=cmd_ledger_recent)

    sp = sub.add_parser("buy-record", help="record a placed buy against the daily cap")
    sp.add_argument("json")
    sp.set_defaults(func=cmd_buy_record)

    sp = sub.add_parser("buys-today", help="today's buy-cap counter")
    sp.set_defaults(func=cmd_buys_today)

    sp = sub.add_parser("perf", help="performance readout across the ledger")
    sp.set_defaults(func=cmd_perf)

    sp = sub.add_parser("status", help="quick kill-switch / live-flag state")
    sp.set_defaults(func=cmd_status)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    ensure_state_dir()
    args.func(args)


if __name__ == "__main__":
    main()
