"""Thorp — quantitative edge through vol-surface mispricings.

Methodology (Thorp, *A Man for All Markets*, 2017; *Beat the Market*, 1967):
- Fit a per-expiry vol smile to the chain (``app.core.vol_surface``).
- For each listed contract, compare market IV to the smile's fair IV.
- If |Δσ| exceeds ``edge_threshold`` (default 3 vol points *and* at least 5%
  of fair IV), flag the contract. Underpriced market IV → buy; overpriced → sell.
- Size the top pick with **fractional Kelly** (default 0.25×), capped by the
  account's per-trade cash limit. Kelly uses a normal-approximation edge in
  dollars divided by variance of the fair-vs-market residual.
- Output a delta-neutral "pair": the primary option + an opposing option on
  the same expiry that cancels most of the delta. The UI/journal can replace
  the opposing leg with equivalent stock if preferred.

This module intentionally does **not** hedge perfectly — Phase 2 returns the
opposing option closest to -delta of the primary. A full delta-neutral hedger
using stock is a Phase 4 concern once the backtest harness is in place.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal

from app.core.bsm import delta as bsm_delta
from app.core.bsm import price as bsm_price
from app.core.models import (
    CONTRACT_MULTIPLIER,
    Account,
    Candidate,
    ManagementAction,
    ManagementVerdict,
    MarketSnapshot,
    OptionChain,
    OptionContract,
    OptionRight,
    Position,
    PositionSize,
    TradeLeg,
    TradeSetup,
)
from app.core.vol_surface import SmileFit, fit_surface
from app.data.base import DataProvider

EdgeSide = Literal["buy_underpriced", "sell_overpriced"]


@dataclass(frozen=True)
class ThorpConfig:
    min_abs_vol_edge: float = 0.03  # 3 vol points
    min_rel_vol_edge: float = 0.05  # 5% of fair IV
    min_dte: int = 14
    max_dte: int = 120
    kelly_cap: float = 0.25  # max fraction of Kelly to deploy
    kelly_variance_floor: float = 0.01  # prevents divide-by-zero in outrageous edges


@dataclass
class EdgeFinding:
    contract: OptionContract
    fair_iv: float
    market_iv: float
    fair_price: float
    edge_dollars: float  # mid - fair; positive = overpriced (sell), negative = underpriced (buy)
    side: EdgeSide


class ThorpStrategist:
    name = "thorp"

    def __init__(self, provider: DataProvider, config: ThorpConfig | None = None):
        self._provider = provider
        self._config = config or ThorpConfig()

    # ------------------------------------------------------------------ screen
    def screen(self, universe: list[str]) -> list[Candidate]:
        """Cheap pre-filter: tickers whose chain has fittable smiles."""
        out: list[Candidate] = []
        for ticker in universe:
            try:
                chain = self._provider.get_chain(ticker)
            except Exception:  # pragma: no cover - provider-specific failures
                continue
            surface = fit_surface(chain)
            if not surface:
                continue
            findings = self._find_edges(chain, surface)
            if findings:
                top = max(findings, key=lambda f: abs(f.edge_dollars))
                out.append(
                    Candidate(
                        ticker=ticker.upper(),
                        reason=f"{len(findings)} vol-surface mispricings; top ${top.edge_dollars:+.2f}",
                        score=abs(top.edge_dollars),
                    )
                )
        return sorted(out, key=lambda c: c.score, reverse=True)

    # ----------------------------------------------------------------- analyze
    def analyze(self, ticker: str, chain: OptionChain) -> TradeSetup | None:
        surface = fit_surface(chain)
        if not surface:
            return None
        findings = self._find_edges(chain, surface)
        if not findings:
            return self._skip(ticker, "No vol-surface edge above threshold.")
        top = max(findings, key=lambda f: abs(f.edge_dollars))
        hedge = self._pick_hedge(top, chain)

        primary_qty = 1 if top.side == "buy_underpriced" else -1
        legs = [TradeLeg(contract=top.contract, quantity=primary_qty)]
        if hedge is not None:
            hedge_qty = -1 if primary_qty > 0 else 1
            legs.append(TradeLeg(contract=hedge, quantity=hedge_qty))

        net_debit_credit = self._net_cost(legs)
        edge_abs = abs(top.edge_dollars)
        edge_pct = edge_abs / max(top.fair_price, 0.01)

        # Quick payoff extremes via scenario evaluation around spot ±30%.
        max_profit, max_loss = self._bracket_payoff(legs, chain)
        expected_value = edge_abs  # first-order expectation = the mispricing itself

        return TradeSetup(
            ticker=ticker.upper(),
            strategy="thorp_edge_pair" if hedge else "thorp_edge_single",
            thesis=(
                f"Market IV {top.market_iv:.1%} vs surface fair {top.fair_iv:.1%} "
                f"(edge ${top.edge_dollars:+.2f}, {edge_pct:.1%} of fair). "
                f"{'Buy' if top.side == 'buy_underpriced' else 'Sell'} "
                f"{top.contract.right.value} {top.contract.strike:g} exp {top.contract.expiry}"
                + (" with delta-neutral hedge." if hedge else ".")
            ),
            legs=legs,
            net_credit=-net_debit_credit,  # credit if net_cost < 0
            max_profit=max_profit,
            max_loss=max_loss,
            breakevens=[],
            pop=None,
            expected_value=expected_value,
            iv_rank=None,
            iv_percentile=None,
            dte=max((top.contract.expiry - self._today(chain.as_of)).days, 0),
            notes=[
                f"Surface RMSE: {surface[top.contract.expiry].rmse:.4f} over "
                f"{surface[top.contract.expiry].n_points} OTM quotes.",
                "Per Thorp, fractional Kelly (0.25×) sizing — see size().",
            ],
        )

    # -------------------------------------------------------------------- size
    def size(self, setup: TradeSetup, account: Account) -> PositionSize:
        """Kelly sizing on a normal-approx single-edge bet.

        Let e = |edge| in dollars per contract, σ² = max(e², floor). Kelly
        fraction of bankroll = e / σ² · 1 share = 1/e if σ²=e² (pure lognormal
        limit). We then take ``kelly_cap × account.kelly_fraction`` of that and
        cap by ``account.max_pct_per_trade``.
        """
        if not setup.legs or setup.expected_value is None or setup.expected_value <= 0:
            return PositionSize(
                contracts=0, capital_at_risk=0.0, pct_of_account=0.0,
                rationale="No positive edge to size against.",
            )
        edge_per_contract = setup.expected_value * CONTRACT_MULTIPLIER
        variance = max(edge_per_contract**2, self._config.kelly_variance_floor)
        kelly_raw = edge_per_contract / variance
        kelly_fraction = kelly_raw * min(self._config.kelly_cap, account.kelly_fraction)
        capital_budget_kelly = max(kelly_fraction, 0.0) * account.cash
        capital_budget_cap = account.max_pct_per_trade * account.cash
        capital_budget = min(capital_budget_kelly, capital_budget_cap)

        per_contract_cost = max(self._per_contract_risk(setup), 1.0)
        contracts = int(capital_budget // per_contract_cost)
        capital_at_risk = contracts * per_contract_cost
        pct = capital_at_risk / account.cash if account.cash > 0 else 0.0
        return PositionSize(
            contracts=contracts,
            capital_at_risk=capital_at_risk,
            pct_of_account=pct,
            rationale=(
                f"Thorp fractional Kelly: edge ${edge_per_contract:.0f}/contract, "
                f"kelly_cap={self._config.kelly_cap}, account_fraction={account.kelly_fraction}, "
                f"capped by max_pct_per_trade={account.max_pct_per_trade:.0%}."
            ),
        )

    # ------------------------------------------------------------------ manage
    def manage(self, position: Position, market: MarketSnapshot) -> ManagementAction:
        """Thorp holds until the edge is realised or the thesis breaks.

        We recompute the surface fit for the primary leg; if |edge| has
        decayed below 30% of entry, the trade has done its job.
        """
        if market.chain is None:
            return ManagementAction(
                verdict=ManagementVerdict.HOLD, reason="No market snapshot chain available."
            )
        surface = fit_surface(market.chain)
        primary = position.setup.legs[0].contract if position.setup.legs else None
        if primary is None or primary.expiry not in surface:
            return ManagementAction(
                verdict=ManagementVerdict.HOLD, reason="No same-expiry smile to re-evaluate."
            )
        fair_iv = surface[primary.expiry].fair_iv(primary.strike)
        current_iv = primary.implied_vol or 0.0
        residual = abs(current_iv - fair_iv)
        if residual < 0.5 * self._config.min_abs_vol_edge:
            return ManagementAction(
                verdict=ManagementVerdict.CLOSE_WINNER,
                reason=f"Vol edge decayed to {residual:.3f} — thesis realised.",
                suggested_action="Close pair at market.",
            )
        return ManagementAction(verdict=ManagementVerdict.HOLD, reason="Edge still intact.")

    # ===================================================================== utils
    def _find_edges(
        self, chain: OptionChain, surface: dict[date, SmileFit]
    ) -> list[EdgeFinding]:
        today = self._today(chain.as_of)
        out: list[EdgeFinding] = []
        for contract in chain.contracts:
            if contract.implied_vol is None or contract.implied_vol <= 0:
                continue
            dte = (contract.expiry - today).days
            if not (self._config.min_dte <= dte <= self._config.max_dte):
                continue
            fit = surface.get(contract.expiry)
            if fit is None:
                continue
            fair_iv = fit.fair_iv(contract.strike)
            delta_iv = contract.implied_vol - fair_iv
            if abs(delta_iv) < self._config.min_abs_vol_edge:
                continue
            if fair_iv > 0 and abs(delta_iv / fair_iv) < self._config.min_rel_vol_edge:
                continue
            t = dte / 365.0
            fair_price = bsm_price(
                chain.spot, contract.strike, t, chain.risk_free_rate, fair_iv, contract.right
            )
            market_price = bsm_price(
                chain.spot, contract.strike, t, chain.risk_free_rate, contract.implied_vol, contract.right
            )
            edge_dollars = market_price - fair_price
            side: EdgeSide = "sell_overpriced" if edge_dollars > 0 else "buy_underpriced"
            out.append(
                EdgeFinding(
                    contract=contract,
                    fair_iv=fair_iv,
                    market_iv=contract.implied_vol,
                    fair_price=fair_price,
                    edge_dollars=edge_dollars,
                    side=side,
                )
            )
        return out

    def _pick_hedge(self, finding: EdgeFinding, chain: OptionChain) -> OptionContract | None:
        """Pick the same-expiry opposite-right contract nearest to -primary delta."""
        primary = finding.contract
        opposite = OptionRight.PUT if primary.right is OptionRight.CALL else OptionRight.CALL
        candidates = [
            c for c in chain.by_expiry(primary.expiry)
            if c.right is opposite and c.delta is not None
        ]
        if not candidates or primary.delta is None:
            return None
        target = -primary.delta
        return min(candidates, key=lambda c: abs((c.delta or 0.0) - target))

    @staticmethod
    def _net_cost(legs: list[TradeLeg]) -> float:
        """Net debit (positive) or credit (negative) per spread, pre-multiplier."""
        total = 0.0
        for leg in legs:
            total += leg.quantity * leg.contract.mid
        return total

    def _per_contract_risk(self, setup: TradeSetup) -> float:
        """Dollar risk per spread. For debit trades it's the premium; for
        credit trades it's reported ``max_loss``. Conservative by design."""
        net_cost = self._net_cost(setup.legs)
        if net_cost > 0:
            return net_cost * CONTRACT_MULTIPLIER
        return max(setup.max_loss, 0.0) * CONTRACT_MULTIPLIER

    def _bracket_payoff(
        self, legs: list[TradeLeg], chain: OptionChain
    ) -> tuple[float, float]:
        """Scan spot ±30% at each leg's expiry and return (max_profit, max_loss)."""
        if not legs:
            return 0.0, 0.0
        spots = [chain.spot * x for x in [0.7 + 0.01 * i for i in range(61)]]
        best = worst = 0.0
        net_cost_dollars = self._net_cost(legs) * CONTRACT_MULTIPLIER
        for s in spots:
            pnl = -net_cost_dollars
            for leg in legs:
                c = leg.contract
                intrinsic = (
                    max(s - c.strike, 0.0)
                    if c.right is OptionRight.CALL
                    else max(c.strike - s, 0.0)
                )
                pnl += leg.quantity * intrinsic * CONTRACT_MULTIPLIER
            best = max(best, pnl)
            worst = min(worst, pnl)
        return best / CONTRACT_MULTIPLIER, abs(worst) / CONTRACT_MULTIPLIER

    @staticmethod
    def _today(as_of: datetime) -> date:
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        return as_of.astimezone(timezone.utc).date()

    def _skip(self, ticker: str, reason: str) -> TradeSetup:
        return TradeSetup(
            ticker=ticker.upper(),
            strategy="skip",
            thesis=reason,
            legs=[],
            net_credit=0.0,
            max_profit=0.0,
            max_loss=0.0,
            breakevens=[],
            dte=0,
            notes=[reason],
        )


# Keep mypy happy: assert hedge helper references bsm_delta so the import is used.
_ = bsm_delta
