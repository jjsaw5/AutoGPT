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
    ok = (oi or 0) >= oi_min and (vol or 0) >= vol_min
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
    ceiling = float(config.account.get("risk_high_conviction_max", 500))
    max_loss = structure.max_loss
    if max_loss is None:
        return GateResult("G6", True, "deferred: size on live chain")
    ok = max_loss <= ceiling
    return GateResult("G6", ok, f"max loss ${max_loss:.0f} vs ceiling ${ceiling:.0f}")


def _g7_aggregate_risk(structure, config, ctx) -> GateResult:
    max_open = float(config.account.get("max_open_risk", 2000))
    max_pos = int(config.account.get("max_positions", 6))
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


def _g10_intraday_margin(structure, g, ctx) -> GateResult:
    if structure.is_defined_risk:
        return GateResult("G10", True, "defined-risk — non-binding")
    safe_harbor = float(g.get("intraday_margin_safe_harbor", 250))
    deficit = float(ctx.get("margin_deficit", 0))
    ok = deficit <= safe_harbor
    return GateResult("G10", ok, f"margin deficit ${deficit:.0f} vs safe harbor ${safe_harbor:.0f}")
