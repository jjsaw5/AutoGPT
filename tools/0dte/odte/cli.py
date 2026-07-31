"""Command line entry point.

    python -m odte.cli regime
    python -m odte.cli signal --symbol SPY --broker-data premarket.json
    python -m odte.cli signal --symbol QQQ --json

`--broker-data` takes the raw JSON payload from
`mcp__Robinhood__get_equity_historicals` (bounds='extended'). Without it the
premarket levels are unavailable and every signal correctly refuses to
trade, because FMP's intraday feed starts at 09:30.

`--now` shifts the *timing gate only*. Quotes are always fetched live, so
replaying an earlier timestamp does not rewind price -- this tool is not a
backtester and must not be read as one.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime

from .brokers import parse_historicals, parse_quotes
from .config import DEFAULT_CONFIG, MARKET_TZ, StrategyConfig
from .fmp import FMPClient, FMPError
from .levels import build_levels
from .models import Decision, Session, Signal
from .regime import required_symbols, score_regime
from .signal import evaluate
from .uw import load_uw_context

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _load_broker_payload(path: str | None) -> dict:
    if not path:
        return {}
    with open(path) as handle:
        return json.load(handle)


def _resolve_now(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(MARKET_TZ)
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MARKET_TZ)
    return parsed.astimezone(MARKET_TZ)


def build_signal(
    symbol: str,
    now: datetime,
    session_day: date,
    broker_payload: dict,
    config: StrategyConfig,
    use_uw: bool,
    trades_taken: int,
    losses: int,
) -> Signal:
    client = FMPClient()

    quotes = client.batch_quotes(required_symbols())
    regime = score_regime(quotes, config.regime)

    intraday = client.intraday_bars(
        symbol, interval=config.trend.intraday_interval, day=session_day
    )
    daily = client.daily_bars(symbol, limit=config.trend.daily_sma + 40)

    broker_bars = (
        parse_historicals(broker_payload).get(symbol, []) if broker_payload else []
    )
    premarket_bars = [b for b in broker_bars if b.session is Session.PRE]

    broker_quotes = parse_quotes(broker_payload) if broker_payload else {}
    price = None
    if symbol in broker_quotes:
        price = broker_quotes[symbol].price
    elif symbol in quotes:
        price = quotes[symbol].price
    elif intraday:
        price = intraday[-1].close
    if price is None:
        raise FMPError(f"no price available for {symbol}")

    levels = build_levels(
        intraday_bars=intraday,
        daily_bars=daily,
        day=session_day,
        price=price,
        premarket_bars=premarket_bars or None,
        trend_config=config.trend,
        level_config=config.levels,
    )

    uw = load_uw_context(symbol, enabled=use_uw)

    return evaluate(
        symbol=symbol,
        now=now,
        levels=levels,
        regime=regime,
        config=config,
        uw=uw,
        trades_taken_today=trades_taken,
        losses_today=losses,
    )


def render(signal: Signal) -> str:
    colour = {
        Decision.LONG_CALL: GREEN,
        Decision.LONG_PUT: RED,
        Decision.NO_TRADE: YELLOW,
    }[signal.decision]

    lines = [
        "",
        f"{BOLD}{signal.symbol} 0DTE — {signal.asof:%Y-%m-%d %H:%M} ET{RESET}",
        f"  {colour}{BOLD}{signal.decision.value}{RESET}"
        + (f"   conviction {signal.conviction}/100" if signal.conviction else ""),
        "",
        f"  {DIM}regime{RESET}  {signal.regime.detail}",
    ]

    if signal.uw_detail:
        lines.append(
            f"  {DIM}flow  {RESET}  {signal.uw_detail} (bias {signal.uw_bias:+.2f})"
        )

    lv = signal.levels

    def fmt(value):
        return f"{value:.2f}" if isinstance(value, float) else "—"

    lines += [
        f"  {DIM}price {RESET} {fmt(lv.price)}   "
        f"{DIM}PMH{RESET} {fmt(lv.premarket_high)}  "
        f"{DIM}PML{RESET} {fmt(lv.premarket_low)}",
        f"  {DIM}EMA9  {RESET} {fmt(lv.ema_fast)}   "
        f"{DIM}EMA21{RESET} {fmt(lv.ema_slow)}  "
        f"{DIM}VWAP{RESET} {fmt(lv.vwap)}  "
        f"{DIM}200SMA{RESET} {fmt(lv.sma_daily)}  "
        f"{DIM}ATR{RESET} {fmt(lv.atr)}",
        "",
    ]

    for gate in signal.gates:
        mark = f"{GREEN}pass{RESET}" if gate.passed else f"{RED}fail{RESET}"
        lines.append(f"  [{mark}] {gate.name:<12} {gate.detail}")

    if signal.plan:
        plan = signal.plan
        lines += [
            "",
            f"  {BOLD}plan{RESET}",
            f"    risk budget      ${plan.risk_dollars:,.0f}",
            f"    entry reference  {plan.entry_reference:.2f}",
            f"    invalidation     {plan.invalidation:.2f}",
            f"    exits            +{plan.profit_target_pct:.0%} target / "
            f"-{plan.stop_loss_pct:.0%} stop / {plan.time_stop_minutes}m time stop",
            f"    flat by          {plan.flat_by}",
        ]
        for note in plan.notes:
            lines.append(f"    {DIM}· {note}{RESET}")
        lines += [
            "",
            f"  {YELLOW}Contract selection and order entry are deliberately manual.{RESET}",
            f"  {DIM}Pull the 0DTE chain, run odte.contract.select_contract(), and "
            f"place the order yourself.{RESET}",
        ]

    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="odte", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="emit JSON")
    common.add_argument(
        "--now",
        help="override the clock for the timing gate (ISO, ET). Quotes stay live; "
        "this is not a backtest",
    )
    common.add_argument("--use-uw", action="store_true", help="enable Unusual Whales")

    sub.add_parser("regime", parents=[common], help="score the tech regime only")

    sig = sub.add_parser("signal", parents=[common], help="full signal for one symbol")
    sig.add_argument("--symbol", default="SPY")
    sig.add_argument("--broker-data", help="Robinhood historicals JSON (extended)")
    sig.add_argument("--date", help="session date (YYYY-MM-DD), defaults to today")
    sig.add_argument("--trades-taken", type=int, default=0)
    sig.add_argument("--losses", type=int, default=0)

    args = parser.parse_args(argv)
    config = DEFAULT_CONFIG
    now = _resolve_now(args.now)

    try:
        if args.command == "regime":
            quotes = FMPClient().batch_quotes(required_symbols())
            regime = score_regime(quotes, config.regime)
            if args.json:
                print(
                    json.dumps(
                        {
                            "regime": regime.regime.value,
                            "score": round(regime.score, 3),
                            "detail": regime.detail,
                        },
                        indent=2,
                    )
                )
            else:
                print(f"\n  {BOLD}{regime.regime.value}{RESET}  {regime.detail}\n")
            return 0

        session_day = date.fromisoformat(args.date) if args.date else now.date()
        signal = build_signal(
            symbol=args.symbol.upper(),
            now=now,
            session_day=session_day,
            broker_payload=_load_broker_payload(args.broker_data),
            config=config,
            use_uw=args.use_uw,
            trades_taken=args.trades_taken,
            losses=args.losses,
        )
        print(json.dumps(signal.to_dict(), indent=2) if args.json else render(signal))
        return 0

    except FMPError as exc:
        print(f"{RED}data error:{RESET} {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"{RED}missing file:{RESET} {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
