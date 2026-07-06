"""Stage 6 — Readout (spec §8).

Three sections: (1) core book GO-first then WATCH, (2) separated speculative /
0DTE bucket held to a higher quality bar and never counted against core risk,
(3) portfolio summary. Rendered as plain text for terminal / logging.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from ..config import Config
from ..models import Decision, EvaluatedCandidate, StructureType


def render_readout(
    evaluated: list[EvaluatedCandidate],
    config: Config,
    *,
    context: dict[str, Any] | None = None,
    regime=None,
) -> str:
    ctx = context or {}
    spec_bar = float(config.speculative.get("quality_bar_min_composite", 75))

    speculative = [
        ec for ec in evaluated
        if ec.structure.structure_type == StructureType.ZERO_DTE_SPREAD
        or ec.structure.is_speculative
    ]
    spec_ids = {id(ec) for ec in speculative}
    core = [ec for ec in evaluated if id(ec) not in spec_ids]

    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("OPTIONS OPPORTUNITY SCANNER — READOUT   (recommend-only; human confirms)")
    lines.append("=" * 78)

    if regime is not None:
        infl = " ⚠inflationary" if getattr(regime, "inflationary_flag", False) else ""
        lines.append(
            f"MARKET REGIME: {regime.regime} · composite {regime.composite:+.2f} · "
            f"macro {regime.macro_score:+d} ({regime.macro_label}){infl}"
        )

    # --- Section 1: core book -------------------------------------------------
    lines.append("\n[1] CORE BOOK  (GO first, then WATCH)")
    core_book = [ec for ec in core if ec.decision in (Decision.GO, Decision.WATCH)]
    if not core_book:
        lines.append("  (no GO/WATCH candidates this scan)")
    else:
        # Compact table first (parallels the position-review table), detail below.
        lines.extend(_render_candidate_table(core_book, config))
        lines.append("")
    for rank, ec in enumerate(core_book, 1):
        lines.extend(_render_row(rank, ec))

    # --- Section 2: speculative / 0DTE bucket ---------------------------------
    used = int(ctx.get("zerodte_used", 0))
    cap = int(config.budget.get("zerodte_per_week", 3))
    lines.append(f"\n[2] SPECULATIVE / 0DTE BUCKET  (0DTE used {used}/{cap}; approve each)")
    spec_book = [
        ec for ec in speculative
        if ec.decision != Decision.PASS and ec.score.composite >= spec_bar
    ]
    if not spec_book:
        lines.append(f"  (no speculative setups clearing the quality bar ≥ {spec_bar:g})")
    for rank, ec in enumerate(spec_book, 1):
        lines.extend(_render_row(rank, ec, speculative=True))

    # --- Section 3: portfolio summary -----------------------------------------
    lines.append("\n[3] PORTFOLIO SUMMARY")
    lines.extend(_render_summary(core_book, config, ctx))

    lines.append("\n" + "-" * 78)
    lines.append("Not investment advice. Every GO is a hypothesis to validate (§9).")
    return "\n".join(lines)


# Structures that are sold for a credit (entry = credit received); the rest are
# bought for a debit (entry = premium paid).
_CREDIT_STRUCTURES = {
    StructureType.CREDIT_VERTICAL, StructureType.IRON_CONDOR,
}


def _entry_short(ec: EvaluatedCandidate) -> str:
    """Compact entry cost: '$400 db' (debit paid) or '$300 cr' (credit taken)."""
    s = ec.structure
    if s.structure_type in _CREDIT_STRUCTURES:
        amt = s.max_profit
        return f"${amt:.0f} cr" if amt is not None else "—"
    amt = s.max_loss
    return f"${amt:.0f} db" if amt is not None else "—"


# Pillar → short label for the "what moves it" lever (weakest pillar = the drag).
_PILLAR_LABEL = {
    "p1": "vol", "p2": "dir", "p3": "EV", "p4": "catalyst", "p5": "liq", "p6": "corrob",
}


def _weakest_pillar(ec: EvaluatedCandidate) -> str:
    s = ec.score
    pillars = {"p1": s.p1, "p2": s.p2, "p3": s.p3, "p4": s.p4, "p5": s.p5, "p6": s.p6}
    key = min(pillars, key=lambda k: pillars[k])
    return f"{_PILLAR_LABEL[key]} {pillars[key]:.0f}"


def _distance_to_go(ec: EvaluatedCandidate, go: float) -> str:
    """The binding blocker: bad pricing, a failed gate, GO, or the score gap +
    the weakest pillar (the single most likely lever to move it up)."""
    if ec.structure.max_loss is not None and ec.structure.max_loss <= 0:
        return "⚠ bad pricing"
    failed = [r.gate_id for r in ec.gates.failures]
    if failed:
        return "gate " + ",".join(failed)
    if ec.decision == Decision.GO:
        return "GO ✓"
    gap = go - ec.effective_composite
    return f"+{gap:.1f} → {_weakest_pillar(ec)}"


def _contract_str(ec: EvaluatedCandidate) -> str:
    """Compact contract: signed strikes + type, e.g. '+C751 -C761'."""
    legs = ec.structure.legs
    if not legs:
        return "—"
    return " ".join(
        f"{'+' if lg.action == 'buy' else '-'}{lg.option_type[0].upper()}{lg.strike:g}"
        for lg in legs
    )


def _expiry_str(ec: EvaluatedCandidate) -> str:
    s = ec.structure
    if s.expiry:
        return s.expiry
    if s.legs and s.legs[0].expiry:
        return s.legs[0].expiry            # placeholder shows '~7-30d'
    return "—"


def _render_candidate_table(core_book: list[EvaluatedCandidate], config: Config) -> list[str]:
    """Compact one-line-per-candidate table — the new-position analogue of the
    position-review table. Shows the contract we'd trade (strikes/expiry/cost)
    and the distance to a full GO. Detail rows follow below it."""
    go = float(config.go_threshold)
    header = (f"  {'#':<2} {'TICKER':<6} {'STRUCTURE':<15} {'DEC':<5} {'COMP':>5} "
              f"{'POP':>4} {'EV':>7} {'CONTRACT':<24} {'EXPIRY':<11} {'COST':>9}  Δ→GO / BLOCKER")
    rows = [header, "  " + "-" * (len(header) - 2)]
    for rank, ec in enumerate(core_book, 1):
        s = ec.score
        pop = f"{s.pop:.0%}" if s.pop is not None else "—"
        ev = f"${s.expected_value:.0f}" if s.expected_value is not None else "—"
        rows.append(
            f"  {rank:<2} {ec.ticker:<6} {ec.structure.structure_type.value:<15} "
            f"{ec.decision.value:<5} {ec.effective_composite:>5.1f} {pop:>4} {ev:>7} "
            f"{_contract_str(ec):<24} {_expiry_str(ec):<11} {_entry_short(ec):>9}  "
            f"{_distance_to_go(ec, go)}"
        )
    return rows


def _render_row(
    rank: int, ec: EvaluatedCandidate, *, speculative: bool = False
) -> list[str]:
    s = ec.score
    t = ec.thesis
    cap = ec.candidate.cap_tier.value if ec.candidate.cap_tier else "?"
    pillars = f"P1 {s.p1:.0f} P2 {s.p2:.0f} P3 {s.p3:.0f} P4 {s.p4:.0f} P5 {s.p5:.0f} P6 {s.p6:.0f}"
    ivr = f"{t.iv_rank:.0f}" if t.iv_rank is not None else "—"
    im = f"{t.implied_move:.1%}" if t.implied_move else "—"
    em = f"{t.expected_move:.1%}" if t.expected_move else "—"
    dtc = f"{t.days_to_catalyst}d" if t.days_to_catalyst is not None else "—"
    maxp = f"${ec.structure.max_profit:.0f}" if ec.structure.max_profit is not None else "—"
    maxl = f"${ec.structure.max_loss:.0f}" if ec.structure.max_loss is not None else "—"
    be = "/".join(f"{b:g}" for b in ec.structure.breakevens) or "—"
    size = f"${ec.suggested_size:.0f} ({ec.size_tier})" if ec.suggested_size else "—"

    comp = f"composite {s.composite:.1f}"
    if ec.regime_adj:
        comp += f"{ec.regime_adj:+.0f} macro → {ec.effective_composite:.1f}"
    header = (
        f"  #{rank} {ec.ticker} [{cap}/T{ec.candidate.tier.value}] "
        f"{ec.structure.structure_type.value}  →  {ec.decision.value}  ({comp})"
    )
    return [
        header,
        f"     {_entry_line(ec)}",
        f"     legs: {ec.structure.legs_str()}",
        f"     thesis: {t.direction.value} | vol={t.vol_regime.value} | catalyst={t.catalyst.value} ({dtc})",
        f"     IVR {ivr} | {pillars} | POP {s.pop:.0%} | EV ${s.expected_value:.0f}",
        f"     maxP {maxp} / maxL {maxl} | breakeven {be} | implied {im} vs expected {em}",
        f"     gates: {ec.gates.flags()} | size: {size}",
        f"     why: {ec.why}",
        f"     risk: {ec.biggest_risk}",
    ] + ([f"     exit: {ec.exit_plan.summary()}"] if ec.exit_plan else [])


_CREDIT_FAMILY = {StructureType.CREDIT_VERTICAL, StructureType.IRON_CONDOR}


def _entry_line(ec: EvaluatedCandidate) -> str:
    """The exact play — 'here is the trade to put on' (GO) or why we're waiting."""
    st = ec.structure
    credit = st.structure_type in _CREDIT_FAMILY
    net = st.max_profit if credit else st.max_loss
    net_str = f"~${net:.0f} {'credit' if credit else 'debit'}" if net is not None else "—"
    verb = "SELL" if credit else "BUY"
    play = f"{verb} {ec.ticker} {st.structure_type.value} {st.legs_str()}  for {net_str}"

    if ec.decision == Decision.GO:
        contracts = 1
        if st.max_loss and ec.suggested_size:
            contracts = max(1, round(ec.suggested_size / st.max_loss))
        return f"▶ ENTRY: {play} · {contracts}×  (${ec.suggested_size:.0f} risk)"

    # WATCH — say plainly what's holding it back.
    if not ec.gates.passed:
        blocked = ", ".join(f.gate_id for f in ec.gates.failures)
        reason = f"gated on {blocked}"
    elif ec.effective_composite < 72:
        reason = f"score {ec.effective_composite:.0f} < 72"
    elif ec.score.expected_value <= 0:
        reason = "EV ≤ 0"
    else:
        reason = "below GO bar"
    return f"○ WATCH: would {play.lower()} — waiting ({reason})"


def _render_summary(
    core_book: list[EvaluatedCandidate], config: Config, ctx: dict[str, Any]
) -> list[str]:
    gos = [ec for ec in core_book if ec.decision == Decision.GO]
    new_risk = sum(ec.suggested_size for ec in gos)
    open_risk = float(ctx.get("open_risk", 0))
    max_open = config.max_open_risk()
    open_positions = int(ctx.get("open_positions", 0))
    max_pos = config.max_positions()
    used = int(ctx.get("zerodte_used", 0))
    cap = int(config.budget.get("zerodte_per_week", 3))

    total_risk = open_risk + new_risk
    remaining = max(0.0, max_open - total_risk)
    sectors = Counter(
        ec.candidate.sector for ec in gos if ec.candidate.sector
    )
    sector_str = ", ".join(f"{k}:{v}" for k, v in sectors.most_common()) or "—"

    return [
        f"  Open risk (existing + new GO): ${total_risk:.0f} / ${max_open:.0f} "
        f"({total_risk / max_open:.0%})",
        f"  Remaining core risk budget: ${remaining:.0f}",
        f"  Concurrent positions: {open_positions + len(gos)} / {max_pos}",
        f"  0DTE used this week: {used} / {cap}",
        f"  GO sector concentration: {sector_str}",
    ]
