"""CLI entrypoint for the Vol Desk rule engine. Run as `python -m voldesk`."""

from __future__ import annotations

import argparse
from datetime import date

from .exits import evaluate_exits, evaluate_take_profit
from .grading import evaluate_setup
from .ingest import load_gamma_screen
from .ledger import PositionLedger
from .models import Position, PositionStatus, SetupClassification
from .regime import evaluate_regime


def _cmd_scan(args: argparse.Namespace) -> None:
    rows = load_gamma_screen(args.csv_path)
    evaluations = [evaluate_setup(row) for row in rows]

    groups: dict[SetupClassification, list] = {
        SetupClassification.CONFIRMED: [],
        SetupClassification.PENDING: [],
        SetupClassification.BLOCKED: [],
    }
    for ev in evaluations:
        groups[ev.classification].append(ev)

    for classification in (
        SetupClassification.CONFIRMED,
        SetupClassification.PENDING,
        SetupClassification.BLOCKED,
    ):
        evs = groups[classification]
        print(f"\n=== {classification.value} ({len(evs)}) ===")
        for ev in evs:
            rr = f"{ev.risk_reward:.2f}" if ev.risk_reward is not None else "n/a"
            cushion = (
                f"{ev.cotmp_cushion_pct:.2f}%" if ev.cotmp_cushion_pct is not None else "n/a"
            )
            print(f"  {ev.symbol}: R/R={rr} cotmp_cushion={cushion}")
            if classification == SetupClassification.BLOCKED:
                for f in ev.filters:
                    if not f.passed:
                        print(f"      FAILED [{f.name}]: {f.reason}")


def _cmd_regime(args: argparse.Namespace) -> None:
    result = evaluate_regime(
        spy_change_pct=args.spy,
        qqq_change_pct=args.qqq,
        bull_count=args.bull,
        bear_count=args.bear,
        vix_dealer_delta=args.vix_delta,
        hyg_bearish=args.hyg_bearish,
        basket_bullish_or_bull_bear_confirms=args.basket_bullish_or_bull_bear_confirms,
    )
    print("Regime gate results:")
    print(f"  basket_gate:               {result.basket_gate}")
    print(f"  bull_bear_gate:            {result.bull_bear_gate}")
    print(f"  vix_delta_gate:            {result.vix_delta_gate}")
    print(f"  gates_passed:              {result.gates_passed}/3")
    print(f"  track1_mechanical_allowed: {result.track1_mechanical_allowed}")
    print(f"  b_continuation_allowed:    {result.b_continuation_allowed}")
    print(f"  hyg_divergence_warning:    {result.hyg_divergence_warning}")
    print(f"  sizing_multiplier:         {result.sizing_multiplier}")


def _cmd_position_open(args: argparse.Namespace) -> None:
    ledger = PositionLedger(args.ledger)
    ledger.load()
    position = Position(
        symbol=args.symbol,
        entry_price=args.entry_price,
        entry_date=date.fromisoformat(args.entry_date),
        p_trans=args.p_trans,
        n_trans=args.n_trans,
        t1_target=args.t1,
        t2_target=args.t2,
        status=PositionStatus.CONFIRMED,
    )
    ledger.open_position(position)
    print(f"Opened position: {position.symbol} @ {position.entry_price} on {position.entry_date}")


def _cmd_position_check(args: argparse.Namespace) -> None:
    ledger = PositionLedger(args.ledger)
    ledger.load()
    position = ledger.get(args.symbol)
    if position is None:
        print(f"No position found for {args.symbol}")
        return

    check_date = date.fromisoformat(args.date)
    exit_decision = evaluate_exits(
        position=position,
        current_price=args.price,
        current_date=check_date,
        closed_below_n_trans=args.closed_below_ntrans,
    )
    take_profit = evaluate_take_profit(position, args.price)

    print(f"Position check: {position.symbol} @ {args.price} on {check_date}")
    print(f"  should_exit:   {exit_decision.should_exit}")
    if exit_decision.reason:
        print(f"  reason:        {exit_decision.reason}")
    if exit_decision.exit_urgency:
        urgency = (
            exit_decision.exit_urgency.value
            if hasattr(exit_decision.exit_urgency, "value")
            else exit_decision.exit_urgency
        )
        print(f"  urgency:       {urgency}")
    if exit_decision.new_status:
        print(f"  new_status:    {exit_decision.new_status.value}")

    print(f"  t1_reached:    {take_profit['t1_reached']}")
    if take_profit["t1_reached"]:
        for choice in take_profit["choices"]:
            print(f"    - {choice}")
        print(f"    note: {take_profit['note']}")


def _cmd_position_list(args: argparse.Namespace) -> None:
    ledger = PositionLedger(args.ledger)
    ledger.load()
    open_positions = ledger.all_open()
    if not open_positions:
        print("No open positions.")
        return
    for p in open_positions:
        print(
            f"  {p.symbol}: entry={p.entry_price} ({p.entry_date}) "
            f"status={p.status.value} t1={p.t1_target} t2={p.t2_target} "
            f"t1_hit={p.t1_hit} stop_locked={p.stop_locked_to_entry}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="voldesk", description="Vol Desk rule engine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan a gamma screen CSV")
    scan_parser.add_argument("csv_path", help="Path to the gamma screen CSV export")
    scan_parser.set_defaults(func=_cmd_scan)

    regime_parser = subparsers.add_parser("regime", help="Evaluate the regime gates")
    regime_parser.add_argument("--spy", type=float, required=True, dest="spy")
    regime_parser.add_argument("--qqq", type=float, required=True, dest="qqq")
    regime_parser.add_argument("--bull", type=int, required=True, dest="bull")
    regime_parser.add_argument("--bear", type=int, required=True, dest="bear")
    regime_parser.add_argument("--vix-delta", type=float, required=True, dest="vix_delta")
    regime_parser.add_argument(
        "--hyg-bearish", action="store_true", dest="hyg_bearish", default=False
    )
    regime_parser.add_argument(
        "--basket-bullish-or-bull-bear-confirms",
        action="store_true",
        dest="basket_bullish_or_bull_bear_confirms",
        default=False,
        help="Set if basket/breadth gates are bullish/confirming (for HYG divergence check)",
    )
    regime_parser.set_defaults(func=_cmd_regime)

    position_parser = subparsers.add_parser("position", help="Manage tracked positions")
    position_subparsers = position_parser.add_subparsers(dest="position_command", required=True)

    open_parser = position_subparsers.add_parser("open", help="Open a new position")
    open_parser.add_argument("symbol")
    open_parser.add_argument("--entry-price", type=float, required=True)
    open_parser.add_argument("--entry-date", required=True, help="YYYY-MM-DD")
    open_parser.add_argument("--p-trans", type=float, required=True)
    open_parser.add_argument("--n-trans", type=float, required=True)
    open_parser.add_argument("--t1", type=float, required=True)
    open_parser.add_argument("--t2", type=float, default=None)
    open_parser.add_argument("--ledger", required=True)
    open_parser.set_defaults(func=_cmd_position_open)

    check_parser = position_subparsers.add_parser("check", help="Check a position's exit/target status")
    check_parser.add_argument("symbol")
    check_parser.add_argument("--price", type=float, required=True)
    check_parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    check_parser.add_argument(
        "--closed-below-ntrans", action="store_true", default=False, dest="closed_below_ntrans"
    )
    check_parser.add_argument("--ledger", required=True)
    check_parser.set_defaults(func=_cmd_position_check)

    list_parser = position_subparsers.add_parser("list", help="List open positions")
    list_parser.add_argument("--ledger", required=True)
    list_parser.set_defaults(func=_cmd_position_list)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
