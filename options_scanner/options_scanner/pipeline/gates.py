"""Stage 2 — Hard gates (spec §5).

Binary GO/NO-GO filters. Any failure => the candidate is PASS regardless of
score. Gates that require the live option chain (spread width, greeks-based
assignment risk) are *deferred* — marked passing with an explicit note — when
no live-chain metrics are supplied, since the human confirmation step in the
recommend-only flow pulls those from Robinhood. True underlying-level blockers
(liquidity floor, earnings alignment, risk caps) are evaluated fail-closed.
"""

from __future__ import annotations

from typing import Any

from ..config import Config
from ..models import (
    Candidate,
    CapTier,
    GateReport,
    GateResult,
    Horizon,
    Structure,
    StructureType,
    Thesis,
)

# Approximate holding window (calendar days) by thesis horizon — used to decide
# whether a scheduled earnings date falls inside the trade's life (gate G4).
_HOLDING_DAYS = {
    Horizon.INTRADAY: 0,
    Horizon.SWING: 10,
    Horizon.POSITION: 56,
    Horizon.LEAPS: 200,
}

# Long-premium structures blocked through earnings unless tagged as an edge play.
_LONG_PREMIUM = {
    StructureType.LONG_CALL,
    StructureType.LONG_PUT,
    StructureType.LEAPS,
    StructureType.DEBIT_VERTICAL,
}

_TIER_SCALE = {  # G1 "scale down one tier for MID/SMALL"
    CapTier.MEGA: 1.0,
    CapTier.LARGE: 1.0,
    CapTier.MID: 0.5,
    CapTier.SMALL: 0.25,
    CapTier.MICRO: 0.25,
}


def evaluate_gates(
    candidate: Candidate,
    thesis: Thesis,
    structure: Structure,
    config: Config,
    *,
    context: dict[str, Any] | None = None,
) -> GateReport:
    """Run all gates. ``context`` carries live portfolio / chain state:
    ``open_risk``, ``open_positions``, ``zerodte_used``, ``manual_override``,
    and optional live-chain metrics (``contract_oi``, ``contract_vol``,
    ``spread_pct``, ``short_leg_itm``, ``margin_deficit``, ``data_stale``).
    """
    ctx = context or {}
    g = config.gates
    results: list[GateResult] = [
        _g1_contract_liquidity(candidate, structure, g, ctx),
        _g2_spread(thesis, structure, g, ctx),
        _g3_underlying_liquidity(candidate, g, ctx),
        _g4_earnings_alignment(thesis, structure),
        _g5_zerodte_budget(structure, config, ctx),
        _g6_per_trade_risk(structure, config),
        _g7_aggregate_risk(structure, config, ctx),
        _g8_data_freshness(candidate, ctx),
        _g9_assignment_risk(candidate, structure, g, ctx),
        _g10_intraday_margin(structure, g, ctx),
        _g11_exit_plan(structure, ctx),
        _g12_correlation(candidate, thesis, structure, config, ctx),
    ]
    return GateReport(results=results)


def _proxy_liquidity(candidate: Candidate) -> tuple[float | None, float | None]:
    """Best-effort contract OI/volume from base-tier flow alerts."""
    best_oi = best_vol = None
    for alert in candidate.signals.get("flow_alerts", []):
        try:
            oi = float(alert.get("open_interest"))
            vol = float(alert.get("volume"))
        except (TypeError, ValueError):
            continue
        if best_oi is None or oi > best_oi:
            best_oi = oi
        if best_vol is None or vol > best_vol:
            best_vol = vol
    return best_oi, best_vol


def _g1_contract_liquidity(candidate, structure, g, ctx) -> GateResult:
    scale = _TIER_SCALE.get(candidate.cap_tier or CapTier.LARGE, 1.0)
    oi_min = float(g.get("oi_min", 500)) * scale
    vol_min = float(g.get("contract_vol_min", 100)) * scale

    # Prefer the structure's real per-leg metrics from the live chain.
    oi = structure.contract_oi if structure.contract_oi is not None else ctx.get("contract_oi")
    vol = structure.contract_volume if structure.contract_volume is not None else ctx.get("contract_vol")
    if oi is None or vol is None:
        p_oi, p_vol = _proxy_liquidity(candidate)
        oi = oi if oi is not None else p_oi
        vol = vol if vol is not None else p_vol
    if oi is None and vol is None:
        return GateResult("G1", True, "deferred: confirm OI/vol on live chain")
    # Some feeds report OI=0 for very liquid names (SPY had vol 700-2600/strike
    # with OI=0). Treat a zero/absent OI as *unknown*, not illiquid: when OI is
    # missing, let volume carry the liquidity signal instead of hard-failing.
    if oi and oi > 0:
        ok = oi >= oi_min and (vol or 0) >= vol_min
    elif vol is not None:
        ok = vol >= vol_min
    else:
        return GateResult("G1", True, "deferred: OI unavailable, no volume — confirm live")
    src = "chain" if structure.from_chain else "proxy"
    return GateResult(
        "G1", ok, f"OI={oi} vol={vol} vs min OI={oi_min:g}/vol={vol_min:g} ({src})"
    )


def _g2_spread(thesis, structure, g, ctx) -> GateResult:
    is_short_dated = thesis.horizon == Horizon.INTRADAY
    max_pct = float(
        g.get("spread_max_pct_0dte", 0.05) if is_short_dated
        else g.get("spread_max_pct", 0.10)
    )
    # Real per-leg spread from the chain wins; otherwise defer to live confirm.
    spread = structure.spread_pct if structure.spread_pct is not None else ctx.get("spread_pct")
    if spread is None:
        return GateResult("G2", True, f"deferred: confirm spread ≤ {max_pct:.0%} on live chain")
    ok = spread <= max_pct
    src = "chain" if structure.from_chain else "ctx"
    return GateResult("G2", ok, f"spread={spread:.1%} vs max {max_pct:.0%} ({src})")


def _g3_underlying_liquidity(candidate, g, ctx) -> GateResult:
    tier = candidate.cap_tier or CapTier.LARGE
    if tier == CapTier.MICRO and not ctx.get("manual_override"):
        return GateResult("G3", False, "MICRO cap requires manual override")
    floors = g.get("underlying_dollar_vol_floor", {})
    floor = float(floors.get(tier.value, 0))
    price = candidate.price or candidate.signals.get("price")
    avg_vol = candidate.signals.get("avg_volume")
    if not price or not avg_vol:
        return GateResult("G3", True, "deferred: missing price/volume for $-vol")
    dollar_vol = float(price) * float(avg_vol)
    ok = dollar_vol >= floor
    return GateResult("G3", ok, f"$vol={dollar_vol/1e6:.0f}M vs floor {floor/1e6:.0f}M")


def _g4_earnings_alignment(thesis, structure) -> GateResult:
    long_premium = structure.structure_type in _LONG_PREMIUM
    holding_days = _HOLDING_DAYS.get(thesis.horizon, 10)
    dte = thesis.days_to_earnings
    holds_through_earnings = dte is not None and 0 <= dte <= holding_days
    if not holds_through_earnings:
        return GateResult("G4", True, "no earnings inside holding window")
    if long_premium and not thesis.is_earnings_play:
        return GateResult(
            "G4", False,
            f"long premium held through earnings (in {dte}d), not an earnings play — IV crush",
        )
    # Credit-into-earnings or an explicit earnings play: allowed but flagged.
    return GateResult("G4", True, f"earnings in {dte}d — aligned (flagged)")


def _g5_zerodte_budget(structure, config, ctx) -> GateResult:
    if structure.structure_type != StructureType.ZERO_DTE_SPREAD:
        return GateResult("G5", True, "not 0DTE")
    cap = int(config.budget.get("zerodte_per_week", 3))
    used = int(ctx.get("zerodte_used", 0))
    if not structure.is_defined_risk:
        return GateResult("G5", False, "0DTE must be defined-risk")
    if used >= cap:
        return GateResult("G5", False, f"0DTE weekly cap reached ({used}/{cap})")
    return GateResult("G5", True, f"0DTE {used}/{cap} used")


def _g6_per_trade_risk(structure, config) -> GateResult:
    ceiling = config.per_trade_risk_cap()   # %-based, raised by max_trade_risk
    max_loss = structure.max_loss
    if max_loss is None:
        return GateResult("G6", True, "deferred: size on live chain")
    ok = max_loss <= ceiling
    return GateResult("G6", ok, f"max loss ${max_loss:.0f} vs ceiling ${ceiling:.0f}")


def _g7_aggregate_risk(structure, config, ctx) -> GateResult:
    max_open = config.max_open_risk()
    max_pos = config.max_positions()
    open_risk = float(ctx.get("open_risk", 0))
    open_positions = int(ctx.get("open_positions", 0))
    new_risk = structure.max_loss or 0.0
    if open_positions >= max_pos:
        return GateResult("G7", False, f"at position cap ({open_positions}/{max_pos})")
    if open_risk + new_risk > max_open:
        return GateResult(
            "G7", False, f"open+new ${open_risk + new_risk:.0f} > cap ${max_open:.0f}"
        )
    return GateResult("G7", True, f"risk ${open_risk + new_risk:.0f}/{max_open:.0f}, pos {open_positions}/{max_pos}")


def _g8_data_freshness(candidate, ctx) -> GateResult:
    if ctx.get("data_stale"):
        return GateResult("G8", False, "stale quotes/flow (halt/weekend)")
    has_signal = any(
        candidate.signals.get(k) is not None
        for k in ("iv_rank", "price", "net_prem")
    )
    if not has_signal:
        return GateResult("G8", False, "no fresh signal data")
    return GateResult("G8", True, "fresh")


def _g9_assignment_risk(candidate, structure, g, ctx) -> GateResult:
    if ctx.get("short_leg_itm"):
        return GateResult("G9", False, "short leg ITM near expiry — close-only")
    short_legs = [leg for leg in structure.legs if leg.action == "sell"]
    if not short_legs:
        return GateResult("G9", True, "no short leg")

    # Real evaluation when the structure came from the live chain.
    spot = candidate.price or candidate.signals.get("price")
    if structure.from_chain and spot and structure.expiry:
        dte = _dte(structure.expiry)
        near_expiry = dte is not None and dte <= int(g.get("assignment_dte_flag", 2))
        for leg in short_legs:
            itm = (leg.option_type == "call" and spot > leg.strike) or (
                leg.option_type == "put" and spot < leg.strike
            )
            if itm and near_expiry:
                return GateResult("G9", False, f"short {leg.option_type} ITM, {dte}d to expiry — close-only")
        return GateResult("G9", True, "short leg OTM / not near expiry")
    return GateResult("G9", True, "deferred: confirm short-leg moneyness on live chain")


def _dte(expiry_iso: str) -> int | None:
    from datetime import datetime, timezone
    try:
        exp = datetime.strptime(expiry_iso[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    return (exp - datetime.now(timezone.utc).date()).days


def _g12_correlation(candidate, thesis, structure, config, ctx) -> GateResult:
    """Don't pile correlated risk onto an already-concentrated book.

    ``ctx['open_exposure']`` is a list of open positions:
    ``{sector, direction, risk}``. A new trade's cluster is other open risk in
    the SAME direction (net long/short exposure) or the SAME sector. If the
    cluster + this trade exceeds the correlated-risk cap, block it.
    """
    exposure = ctx.get("open_exposure")
    if not exposure:
        return GateResult("G12", True, "deferred: no open-exposure data")
    new_risk = structure.max_loss or 0.0
    new_dir = thesis.direction.value
    new_sector = candidate.sector
    same_dir = sum(e.get("risk", 0) for e in exposure if e.get("direction") == new_dir and new_dir != "neutral")
    same_sec = sum(e.get("risk", 0) for e in exposure if new_sector and e.get("sector") == new_sector)
    cluster = max(same_dir, same_sec)
    cap = config.max_correlated_risk()
    if cluster + new_risk > cap:
        kind = "direction" if same_dir >= same_sec else "sector"
        return GateResult(
            "G12", False,
            f"correlated {kind} risk ${cluster + new_risk:.0f} > cap ${cap:.0f}",
        )
    return GateResult("G12", True, f"correlated risk ${cluster + new_risk:.0f}/{cap:.0f}")


def _g11_exit_plan(structure, ctx) -> GateResult:
    """No exit plan, no trade. Every tradeable structure must carry a complete
    plan (profit target + stop + invalidation) before it can GO."""
    if structure.structure_type == StructureType.NONE:
        return GateResult("G11", True, "no trade")
    plan = ctx.get("exit_plan")
    if plan is None or not plan.is_complete():
        return GateResult("G11", False, "no complete exit plan — no trade")
    return GateResult("G11", True, "exit plan defined")


def _g10_intraday_margin(structure, g, ctx) -> GateResult:
    if structure.is_defined_risk:
        return GateResult("G10", True, "defined-risk — non-binding")
    safe_harbor = float(g.get("intraday_margin_safe_harbor", 250))
    deficit = float(ctx.get("margin_deficit", 0))
    ok = deficit <= safe_harbor
    return GateResult("G10", ok, f"margin deficit ${deficit:.0f} vs safe harbor ${safe_harbor:.0f}")
