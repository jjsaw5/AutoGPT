"""Sosnoff / Tastytrade premium-selling module.

Methodology:
- IV Rank + IV Percentile computed from 52-week ATM IV history. Entry requires
  IVR > 30 and DTE between 30 and 60. References: Sosnoff & Battista, *The
  tastytrade Guide to Options*; Tom Sosnoff interviews on IVR vs IVP (2013+).
- Strategy picker:
  * IVR >= 50 and neutral bias -> short strangle (~16-delta both sides)
  * 30 <= IVR < 50 and neutral bias -> iron condor (~20-delta shorts, 5-wide wings)
  * Directional bias with IVR >= 30 -> credit spread (~30-delta short)
  * IVR < 30 -> skip; premium is too thin to earn risk-adjusted return
- Mechanical management: close at 50% of max profit, roll/close at 21 DTE.

This module intentionally refuses to trade when IVR is low — the whole point of
the approach is that the edge comes from selling expensive volatility.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal

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
from app.data.base import DataProvider, IVHistoryPoint

Bias = Literal["neutral", "bullish", "bearish"]


@dataclass(frozen=True)
class SosnoffConfig:
    min_ivr: float = 30.0
    high_ivr: float = 50.0
    min_dte: int = 30
    max_dte: int = 60
    short_delta_strangle: float = 0.16
    short_delta_condor: float = 0.20
    short_delta_spread: float = 0.30
    wing_width: float = 5.0
    profit_target_pct: float = 0.50
    time_exit_dte: int = 21


def iv_rank(history: list[IVHistoryPoint], current_iv: float) -> float:
    """Classic Tastytrade IVR: (current - 52w low) / (52w high - 52w low) * 100."""
    if not history:
        return 0.0
    vals = [p.atm_iv for p in history]
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        return 0.0
    return max(0.0, min(100.0, (current_iv - lo) / (hi - lo) * 100.0))


def iv_percentile(history: list[IVHistoryPoint], current_iv: float) -> float:
    """Percent of trailing observations strictly below ``current_iv``."""
    if not history:
        return 0.0
    below = sum(1 for p in history if p.atm_iv < current_iv)
    return below / len(history) * 100.0


class SosnoffStrategist:
    """Premium-selling strategist implementing :class:`app.strategists.base.Strategist`."""

    name = "sosnoff"

    def __init__(self, provider: DataProvider, config: SosnoffConfig | None = None):
        self._provider = provider
        self._config = config or SosnoffConfig()

    # ------------------------------------------------------------------ screen
    def screen(self, universe: list[str]) -> list[Candidate]:
        out: list[Candidate] = []
        for ticker in universe:
            history = self._provider.get_iv_history(ticker)
            if not history:
                continue
            current = history[-1].atm_iv
            ivr = iv_rank(history, current)
            if ivr >= self._config.min_ivr:
                out.append(
                    Candidate(
                        ticker=ticker.upper(),
                        reason=f"IVR {ivr:.1f} above entry threshold",
                        score=ivr,
                    )
                )
        return sorted(out, key=lambda c: c.score, reverse=True)

    # ----------------------------------------------------------------- analyze
    def analyze(
        self,
        ticker: str,
        chain: OptionChain,
        bias: Bias = "neutral",
    ) -> TradeSetup | None:
        history = self._provider.get_iv_history(ticker)
        if not history:
            return None
        current_iv = history[-1].atm_iv
        ivr = iv_rank(history, current_iv)
        ivp = iv_percentile(history, current_iv)

        expiry = self._pick_expiry(chain)
        if expiry is None:
            return None
        dte = (expiry - self._today(chain.as_of)).days

        if ivr < self._config.min_ivr:
            return self._skip(ticker, ivr, ivp, dte, "IVR below entry threshold — premium too thin.")

        picker: tuple[str, TradeSetup | None]
        if bias == "neutral" and ivr >= self._config.high_ivr:
            picker = ("short_strangle", self._short_strangle(ticker, chain, expiry, ivr, ivp, dte))
        elif bias == "neutral":
            picker = ("iron_condor", self._iron_condor(ticker, chain, expiry, ivr, ivp, dte))
        else:
            picker = ("credit_spread", self._credit_spread(ticker, chain, expiry, ivr, ivp, dte, bias))
        _, setup = picker
        return setup

    # -------------------------------------------------------------------- size
    def size(self, setup: TradeSetup, account: Account) -> PositionSize:
        """Contracts = min(Kelly-implied, hard cap by max_pct_per_trade).

        Kelly for a binary bet with POP ``p``, win ``w``, loss ``l`` is
        ``(p * w - (1-p) * l) / (w * l)``. We apply ``account.kelly_fraction`` as
        a multiplicative cap (Thorp's fractional-Kelly recommendation).
        """
        if setup.max_loss <= 0 or setup.max_profit <= 0:
            return PositionSize(
                contracts=0,
                capital_at_risk=0.0,
                pct_of_account=0.0,
                rationale="Degenerate payoff — max_loss or max_profit is zero.",
            )

        pop = setup.pop or 0.5
        kelly_raw = (pop * setup.max_profit - (1 - pop) * setup.max_loss) / (
            setup.max_profit * setup.max_loss
        )
        kelly_fraction_of_account = max(0.0, kelly_raw) * account.kelly_fraction
        capital_budget_kelly = kelly_fraction_of_account * account.cash
        capital_budget_cap = account.max_pct_per_trade * account.cash
        capital_budget = min(capital_budget_kelly, capital_budget_cap)

        per_contract_risk = setup.max_loss * CONTRACT_MULTIPLIER
        contracts = int(capital_budget // per_contract_risk)
        capital_at_risk = contracts * per_contract_risk
        pct = capital_at_risk / account.cash if account.cash > 0 else 0.0

        rationale = (
            f"Kelly raw={kelly_raw:.3f}, fractional={kelly_fraction_of_account:.3f} of cash; "
            f"capped by max_pct_per_trade={account.max_pct_per_trade:.2f}. "
            f"Per-contract risk ${per_contract_risk:,.0f}."
        )
        return PositionSize(
            contracts=contracts,
            capital_at_risk=capital_at_risk,
            pct_of_account=pct,
            rationale=rationale,
        )

    # ------------------------------------------------------------------ manage
    def manage(self, position: Position, market: MarketSnapshot) -> ManagementAction:
        cfg = self._config
        setup = position.setup
        max_profit_dollars = setup.max_profit * CONTRACT_MULTIPLIER * position.size.contracts
        if max_profit_dollars > 0 and position.current_pnl >= cfg.profit_target_pct * max_profit_dollars:
            return ManagementAction(
                verdict=ManagementVerdict.CLOSE_WINNER,
                reason=f"Hit {cfg.profit_target_pct * 100:.0f}% of max profit.",
                suggested_action="Close position at market.",
            )
        today = self._today(market.as_of)
        if setup.legs:
            earliest_expiry = min(leg.contract.expiry for leg in setup.legs)
            dte = (earliest_expiry - today).days
            if dte <= cfg.time_exit_dte:
                return ManagementAction(
                    verdict=ManagementVerdict.CLOSE_TIME,
                    reason=f"{dte} DTE is at/below the {cfg.time_exit_dte}-DTE time stop.",
                    suggested_action="Close or roll to next monthly cycle.",
                )
        return ManagementAction(
            verdict=ManagementVerdict.HOLD,
            reason="Neither profit target nor 21-DTE rule triggered.",
        )

    # ===================================================================== utils
    @staticmethod
    def _today(as_of: datetime) -> date:
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        return as_of.astimezone(timezone.utc).date()

    def _pick_expiry(self, chain: OptionChain) -> date | None:
        today = self._today(chain.as_of)
        candidates = [
            e for e in chain.expiries()
            if self._config.min_dte <= (e - today).days <= self._config.max_dte
        ]
        if not candidates:
            return None
        # Prefer ~45 DTE (the Tastytrade sweet spot).
        target = 45
        return min(candidates, key=lambda e: abs((e - today).days - target))

    def _skip(
        self, ticker: str, ivr: float, ivp: float, dte: int, reason: str
    ) -> TradeSetup | None:
        """Produce a "no-trade" TradeSetup so the UI still has context to show."""
        return TradeSetup(
            ticker=ticker.upper(),
            strategy="skip",
            thesis=reason,
            legs=[],
            net_credit=0.0,
            max_profit=0.0,
            max_loss=0.0,
            breakevens=[],
            iv_rank=ivr,
            iv_percentile=ivp,
            dte=max(dte, 0),
            notes=[reason, "Entry gate: IVR>=30 and 30<=DTE<=60."],
        )

    # ----------------------------------------------------------- structure picks
    def _nearest_short_by_delta(
        self,
        candidates: list[OptionContract],
        target_abs_delta: float,
    ) -> OptionContract | None:
        with_delta = [c for c in candidates if c.delta is not None]
        if not with_delta:
            return None
        return min(with_delta, key=lambda c: abs(abs(c.delta or 0.0) - target_abs_delta))

    def _short_strangle(
        self,
        ticker: str,
        chain: OptionChain,
        expiry: date,
        ivr: float,
        ivp: float,
        dte: int,
    ) -> TradeSetup | None:
        legs_for_expiry = chain.by_expiry(expiry)
        calls = [c for c in legs_for_expiry if c.right is OptionRight.CALL and c.strike >= chain.spot]
        puts = [c for c in legs_for_expiry if c.right is OptionRight.PUT and c.strike <= chain.spot]
        short_call = self._nearest_short_by_delta(calls, self._config.short_delta_strangle)
        short_put = self._nearest_short_by_delta(puts, self._config.short_delta_strangle)
        if not short_call or not short_put:
            return None

        credit = short_call.mid + short_put.mid
        max_profit = credit
        # Undefined-risk: max loss is theoretical; report notional exposure instead.
        max_loss = max(short_call.strike, chain.spot * 0.5)
        breakevens = [short_put.strike - credit, short_call.strike + credit]
        # POP ≈ 1 - 2 * |short delta| for a symmetric strangle.
        short_delta = (abs(short_call.delta or 0) + abs(short_put.delta or 0)) / 2
        pop = max(0.0, min(1.0, 1 - 2 * short_delta))
        return TradeSetup(
            ticker=ticker.upper(),
            strategy="short_strangle",
            thesis=(
                f"IVR {ivr:.1f} (>= {self._config.high_ivr:.0f}) — sell the expensive "
                f"vol with a ~16-delta strangle at {dte} DTE."
            ),
            legs=[TradeLeg(contract=short_call, quantity=-1), TradeLeg(contract=short_put, quantity=-1)],
            net_credit=credit,
            max_profit=max_profit,
            max_loss=max_loss,
            breakevens=breakevens,
            pop=pop,
            expected_value=pop * max_profit - (1 - pop) * max_loss,
            iv_rank=ivr,
            iv_percentile=ivp,
            dte=dte,
            notes=[
                "UNDEFINED RISK — max loss above is a conservative estimate, not a cap.",
                "Manage at 50% of max profit or 21 DTE, whichever comes first.",
            ],
        )

    def _iron_condor(
        self,
        ticker: str,
        chain: OptionChain,
        expiry: date,
        ivr: float,
        ivp: float,
        dte: int,
    ) -> TradeSetup | None:
        legs_for_expiry = chain.by_expiry(expiry)
        calls = [c for c in legs_for_expiry if c.right is OptionRight.CALL]
        puts = [c for c in legs_for_expiry if c.right is OptionRight.PUT]
        short_call = self._nearest_short_by_delta(
            [c for c in calls if c.strike >= chain.spot], self._config.short_delta_condor
        )
        short_put = self._nearest_short_by_delta(
            [p for p in puts if p.strike <= chain.spot], self._config.short_delta_condor
        )
        if not short_call or not short_put:
            return None
        long_call = self._nearest_strike(calls, short_call.strike + self._config.wing_width)
        long_put = self._nearest_strike(puts, short_put.strike - self._config.wing_width)
        if not long_call or not long_put:
            return None

        credit = (short_call.mid + short_put.mid) - (long_call.mid + long_put.mid)
        wing = max(long_call.strike - short_call.strike, short_put.strike - long_put.strike)
        max_profit = max(credit, 0.0)
        max_loss = max(wing - credit, 0.01)
        breakevens = [short_put.strike - credit, short_call.strike + credit]
        short_delta = (abs(short_call.delta or 0) + abs(short_put.delta or 0)) / 2
        pop = max(0.0, min(1.0, 1 - 2 * short_delta))
        return TradeSetup(
            ticker=ticker.upper(),
            strategy="iron_condor",
            thesis=(
                f"IVR {ivr:.1f} in {self._config.min_ivr:.0f}–{self._config.high_ivr:.0f} band — "
                f"defined-risk condor at ~20-delta shorts, {self._config.wing_width}-wide wings."
            ),
            legs=[
                TradeLeg(contract=long_put, quantity=1),
                TradeLeg(contract=short_put, quantity=-1),
                TradeLeg(contract=short_call, quantity=-1),
                TradeLeg(contract=long_call, quantity=1),
            ],
            net_credit=credit,
            max_profit=max_profit,
            max_loss=max_loss,
            breakevens=breakevens,
            pop=pop,
            expected_value=pop * max_profit - (1 - pop) * max_loss,
            iv_rank=ivr,
            iv_percentile=ivp,
            dte=dte,
            notes=[
                "Defined-risk. Max loss shown before max gain by design.",
                "Manage at 50% of max profit or 21 DTE.",
            ],
        )

    def _credit_spread(
        self,
        ticker: str,
        chain: OptionChain,
        expiry: date,
        ivr: float,
        ivp: float,
        dte: int,
        bias: Bias,
    ) -> TradeSetup | None:
        legs_for_expiry = chain.by_expiry(expiry)
        if bias == "bullish":
            puts = [p for p in legs_for_expiry if p.right is OptionRight.PUT and p.strike <= chain.spot]
            short = self._nearest_short_by_delta(puts, self._config.short_delta_spread)
            long = self._nearest_strike(puts, (short.strike - self._config.wing_width) if short else 0)
            right_label = "bull put spread"
        else:
            calls = [c for c in legs_for_expiry if c.right is OptionRight.CALL and c.strike >= chain.spot]
            short = self._nearest_short_by_delta(calls, self._config.short_delta_spread)
            long = self._nearest_strike(calls, (short.strike + self._config.wing_width) if short else 0)
            right_label = "bear call spread"
        if not short or not long:
            return None

        credit = short.mid - long.mid
        width = abs(long.strike - short.strike)
        max_profit = max(credit, 0.0)
        max_loss = max(width - credit, 0.01)
        if bias == "bullish":
            breakevens = [short.strike - credit]
        else:
            breakevens = [short.strike + credit]
        pop = max(0.0, min(1.0, 1 - abs(short.delta or 0.3)))
        return TradeSetup(
            ticker=ticker.upper(),
            strategy=right_label.replace(" ", "_"),
            thesis=(
                f"{bias.title()} bias with IVR {ivr:.1f} — {right_label} at ~30-delta short, "
                f"{self._config.wing_width}-wide wing."
            ),
            legs=[TradeLeg(contract=long, quantity=1), TradeLeg(contract=short, quantity=-1)],
            net_credit=credit,
            max_profit=max_profit,
            max_loss=max_loss,
            breakevens=breakevens,
            pop=pop,
            expected_value=pop * max_profit - (1 - pop) * max_loss,
            iv_rank=ivr,
            iv_percentile=ivp,
            dte=dte,
            notes=[
                "Defined-risk directional trade.",
                "Manage at 50% of max profit or 21 DTE.",
            ],
        )

    @staticmethod
    def _nearest_strike(contracts: list[OptionContract], strike: float) -> OptionContract | None:
        if not contracts or strike <= 0:
            return None
        return min(contracts, key=lambda c: abs(c.strike - strike))
