"""Scheduled runner.

    python -m odte.runner              # run today's session
    python -m odte.runner --once       # single evaluation, then exit
    python -m odte.runner --dry-run    # print the schedule, make no calls

This is a sleep-to-the-next-bar loop rather than a set of cron entries, for
two reasons. Cron schedulers drift -- GitHub Actions in particular routinely
fires scheduled jobs five to twenty minutes late, which for a process whose
entry windows are measured in five-minute bars means silently missing the
setup. And forty-odd separate invocations each pay the cold-start and
holiday-lookup cost that one loop pays once.

The loop only wakes on 5-minute bar closes, because that is the only time
the indicators change. It sleeps through the midday chop window and exits
after the close, so a supervisor can simply restart it each morning.
"""

from __future__ import annotations

import argparse
import sys
import time as time_module
from datetime import date, datetime, timedelta

import requests

from .calendar import MarketCalendar, shift_windows
from .cli import RED, RESET, YELLOW, BOLD, DIM, build_signal, render
from .config import DEFAULT_CONFIG, MARKET_TZ, StrategyConfig
from .fmp import FMPError
from .models import Decision
from .store import StoreError, default_store

BAR_MINUTES = 5
SETTLE_SECONDS = 10


def next_tick(now: datetime, bar_minutes: int = BAR_MINUTES) -> datetime:
    """The next bar close, plus a settling delay.

    Bars are stamped at their open, so the 09:45 bar is complete at 09:50.
    Waiting a few extra seconds avoids racing the provider's write.
    """
    floor = now.replace(second=0, microsecond=0)
    floor -= timedelta(minutes=floor.minute % bar_minutes)
    return floor + timedelta(minutes=bar_minutes, seconds=SETTLE_SECONDS)


def in_entry_window(now: datetime, config: StrategyConfig, no_entry_after) -> bool:
    timing = config.timing
    clock = now.time()
    if clock < timing.no_entry_before or clock >= no_entry_after:
        return False
    if (
        timing.skip_midday_chop
        and timing.morning_window_end <= clock < timing.afternoon_window_start
    ):
        return False
    return True


def plan_for(day: date, config: StrategyConfig, calendar: MarketCalendar) -> dict:
    hours = calendar.hours(day)
    no_entry_after, flat_by = shift_windows(
        hours, config.timing.no_entry_after, config.timing.hard_flat_by
    )
    return {
        "hours": hours,
        "no_entry_after": no_entry_after,
        "flat_by": flat_by,
    }


def run_once(
    symbols, now: datetime, day: date, config: StrategyConfig, use_uw: bool, store
) -> None:
    for symbol in symbols:
        taken = losses = 0
        if store is not None:
            taken, losses = store.counts_today(day.isoformat())
        try:
            signal = build_signal(
                symbol=symbol,
                now=now,
                session_day=day,
                broker_payload={},
                config=config,
                use_uw=use_uw,
                trades_taken=taken,
                losses=losses,
            )
        except (FMPError, requests.RequestException) as exc:
            # One bad tick must not end the session; the next bar retries.
            print(f"{RED}{symbol} skipped:{RESET} {exc}", file=sys.stderr)
            continue

        if store is not None:
            try:
                store.record_signal(signal)
            except (StoreError, requests.RequestException) as exc:
                print(f"{YELLOW}not recorded:{RESET} {exc}", file=sys.stderr)

        if signal.decision is Decision.NO_TRADE:
            blocking = signal.blocking_gates
            reason = blocking[0].detail if blocking else "no direction"
            print(f"{DIM}{now:%H:%M} {symbol:<4} no-trade — {reason}{RESET}")
        else:
            print(render(signal))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="odte.runner", description=__doc__)
    parser.add_argument("--symbols", default="SPY,QQQ")
    parser.add_argument("--use-uw", action="store_true")
    parser.add_argument("--once", action="store_true", help="evaluate once and exit")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the schedule and exit"
    )
    parser.add_argument("--no-record", action="store_true")
    args = parser.parse_args(argv)

    config = DEFAULT_CONFIG
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    calendar = MarketCalendar()
    now = datetime.now(MARKET_TZ)
    day = now.date()
    schedule = plan_for(day, config, calendar)
    hours = schedule["hours"]

    if not hours.trading:
        print(f"{day} is not a trading day ({hours.note}). Nothing to do.")
        return 0

    if hours.early_close:
        print(
            f"{YELLOW}early close {hours.close:%H:%M} ({hours.note}){RESET} — "
            f"cutoffs pulled to {schedule['no_entry_after']:%H:%M} / "
            f"{schedule['flat_by']:%H:%M}"
        )

    if args.dry_run:
        print(f"\n{BOLD}{day} session plan{RESET}")
        print(f"  symbols        {', '.join(symbols)}")
        print(
            f"  entry windows  {config.timing.no_entry_before:%H:%M}"
            f"-{config.timing.morning_window_end:%H:%M}, "
            f"{config.timing.afternoon_window_start:%H:%M}"
            f"-{schedule['no_entry_after']:%H:%M}"
        )
        print(f"  flat by        {schedule['flat_by']:%H:%M}")
        print(f"  cadence        every {BAR_MINUTES}m on bar close +{SETTLE_SECONDS}s")
        ticks, cursor = 0, datetime.combine(day, config.timing.no_entry_before).replace(
            tzinfo=MARKET_TZ
        )
        while cursor.time() < schedule["no_entry_after"]:
            if in_entry_window(cursor, config, schedule["no_entry_after"]):
                ticks += 1
            cursor += timedelta(minutes=BAR_MINUTES)
        print(f"  evaluations    {ticks} ticks x {len(symbols)} symbols\n")
        return 0

    store = None if args.no_record else default_store(migrate=True)
    if store is None and not args.no_record:
        print(f"{YELLOW}database not configured — running without recording{RESET}")

    if args.once:
        run_once(symbols, now, day, config, args.use_uw, store)
        return 0

    print(
        f"{BOLD}0DTE runner{RESET} {day} — {', '.join(symbols)}, "
        f"flat by {schedule['flat_by']:%H:%M}"
    )

    while True:
        now = datetime.now(MARKET_TZ)
        if now.date() != day or now.time() >= schedule["flat_by"]:
            print(f"{now:%H:%M} session over.")
            return 0

        if in_entry_window(now, config, schedule["no_entry_after"]):
            run_once(symbols, now, day, config, args.use_uw, store)

        wake = next_tick(datetime.now(MARKET_TZ))
        delay = max(1.0, (wake - datetime.now(MARKET_TZ)).total_seconds())
        time_module.sleep(delay)


if __name__ == "__main__":
    raise SystemExit(main())
