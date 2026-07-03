"""Saliba — defined-risk structures scored on R:R, POP, and PoT.

Methodology: Anthony Saliba, *Managing Expectations* (1996) and *Options:
Trading Strategies That Work* (2008). Saliba's core insight is that the
industry-market-maker's edge comes from defined-risk structures whose max
loss is visible on entry; every ticket is priced against a distribution, not
a single outcome.

This module enumerates the common variants:

- **Iron condor** — two OTM credit spreads, neutral, flat in the middle
- **Iron butterfly** — ATM short straddle + protective wings
- **Long butterfly** — debit ATM body + 2× OTM wings, bullish-on-pin-risk
- **Broken-wing butterfly** — asymmetric wings so one side is a pure credit

Each candidate is scored by ``(R:R, POP, PoT)`` and rejected below
``min_reward_risk``. POP is integrated against the risk-neutral lognormal
density from ``app.core.bsm.pop_between``; PoT against the reflection-principle
formula in ``bsm.prob_touch``. We pick the expiry closest to 45 DTE — not a
Saliba convention per se, but the spec points the whole system at 30–60 DTE.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from app.core.bsm import pop_between, prob_touch
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
from app.data.base import DataProvider


@dataclass(frozen=True)
class SalibaConfig:
    min_reward_risk: float = 0.25
    min_dte: int = 21
    max_dte: int = 70
    preferred_dte: int = 45
    wing_widths: tuple[float, ...] = (5.0, 10.0)
    condor_short_delta: float = 0.20
    fly_wing_offset: float = 5.0


@dataclass
class _Candidate:
    label: str
    legs: list[TradeLeg]
    max_profit: float
    max_loss: float
    breakevens: list[float]
    pop: float
    pot_upper: float
    pot_lower: float
    notes: list[str] = field(default_factory=list)

    @property
    def reward_risk(self) -> float:
        return self.max_profit / self.max_loss if self.max_loss > 0 else float("inf")

    def score(self) -> float:
        """Composite: R:R weighted 60%, POP 30%, (1 − PoT) 10%."""
        pot = max(self.pot_upper, self.pot_lower)
        return 0.6 * min(self.reward_risk, 5.0) + 0.3 * self.pop + 0.1 * (1 - pot)


class SalibaStrategist:
    name = "saliba"

    def __init__(self, provider: DataProvider, config: SalibaConfig | None = None):
        self._provider = provider
        self._config = config or SalibaConfig()

    # ------------------------------------------------------------------ screen
    def screen(self, universe: list[str]) -> list[Candidate]:
        out: list[Candidate] = []
        for ticker in universe:
            try:
                chain = self._provider.get_chain(ticker)
            except Exception:  # pragma: no cover
                continue
            setup = self.analyze(ticker, chain)
            if setup is not None and setup.strategy != "skip":
                out.append(
                    Candidate(
                        ticker=ticker.upper(),
                        reason=f"{setup.strategy} R:R {setup.reward_risk:.2f}, POP {setup.pop or 0:.0%}",
                        score=setup.reward_risk,
                    )
                )
        return sorted(out, key=lambda c: c.score, reverse=True)

    # ----------------------------------------------------------------- analyze
    def analyze(self, ticker: str, chain: OptionChain) -> TradeSetup | None:
        expiry = self._pick_expiry(chain)
        if expiry is None:
            return self._skip(ticker, "No expiry in 21–70 DTE window.")

        dte = (expiry - self._today(chain.as_of)).days
        t = dte / 365.0
        atm_iv = self._atm_iv(chain, expiry)
        if atm_iv is None:
            return self._skip(ticker, "No ATM IV available to compute POP/PoT.")

        legs_for_expiry = chain.by_expiry(expiry)
        candidates: list[_Candidate] = []
        for width in self._config.wing_widths:
            c = self._build_iron_condor(chain, legs_for_expiry, width, t, atm_iv)
            if c:
                candidates.append(c)
        fly = self._build_iron_butterfly(chain, legs_for_expiry, t, atm_iv)
        if fly:
            candidates.append(fly)
        long_fly = self._build_long_butterfly(chain, legs_for_expiry, t, atm_iv)
        if long_fly:
            candidates.append(long_fly)
        bw = self._build_broken_wing_butterfly(chain, legs_for_expiry, t, atm_iv)
        if bw:
            candidates.append(bw)

        viable = [c for c in candidates if c.reward_risk >= self._config.min_reward_risk]
        if not viable:
            return self._skip(
                ticker,
                f"No defined-risk structure meets R:R >= {self._config.min_reward_risk:.2f}.",
            )
        best = max(viable, key=lambda c: c.score())

        return TradeSetup(
            ticker=ticker.upper(),
            strategy=best.label,
            thesis=(
                f"Saliba defined-risk {best.label.replace('_', ' ')}: "
                f"R:R {best.reward_risk:.2f}, POP {best.pop:.0%}, "
                f"PoT upper {best.pot_upper:.0%} / lower {best.pot_lower:.0%}."
            ),
            legs=best.legs,
            net_credit=best.max_profit if best.max_profit > 0 else 0.0,
            max_profit=best.max_profit,
            max_loss=best.max_loss,
            breakevens=best.breakevens,
            pop=best.pop,
            expected_value=best.pop * best.max_profit - (1 - best.pop) * best.max_loss,
            iv_rank=None,
            iv_percentile=None,
            dte=dte,
            notes=[
                *best.notes,
                "Defined-risk by construction — max loss visible on entry.",
                f"R:R threshold {self._config.min_reward_risk:.2f}; "
                f"rejected {len(candidates) - len(viable)} candidate(s) below it.",
            ],
        )

    # -------------------------------------------------------------------- size
    def size(self, setup: TradeSetup, account: Account) -> PositionSize:
        if setup.max_loss <= 0:
            return PositionSize(
                contracts=0, capital_at_risk=0.0, pct_of_account=0.0,
                rationale="Degenerate payoff.",
            )
        pop = setup.pop or 0.5
        kelly_raw = (pop * setup.max_profit - (1 - pop) * setup.max_loss) / (
            setup.max_profit * setup.max_loss
        )
        capital_budget = min(
            max(kelly_raw, 0.0) * account.kelly_fraction * account.cash,
            account.max_pct_per_trade * account.cash,
        )
        per_contract_risk = setup.max_loss * CONTRACT_MULTIPLIER
        contracts = int(capital_budget // per_contract_risk)
        return PositionSize(
            contracts=contracts,
            capital_at_risk=contracts * per_contract_risk,
            pct_of_account=(contracts * per_contract_risk) / account.cash if account.cash > 0 else 0.0,
            rationale=(
                f"Saliba sizing: fractional Kelly on defined-risk; POP={pop:.0%}, "
                f"per-contract risk ${per_contract_risk:.0f}, "
                f"capped by max_pct_per_trade={account.max_pct_per_trade:.0%}."
            ),
        )

    # ------------------------------------------------------------------ manage
    def manage(self, position: Position, market: MarketSnapshot) -> ManagementAction:
        setup = position.setup
        max_profit_dollars = setup.max_profit * CONTRACT_MULTIPLIER * position.size.contracts
        if max_profit_dollars > 0 and position.current_pnl >= 0.5 * max_profit_dollars:
            return ManagementAction(
                verdict=ManagementVerdict.CLOSE_WINNER,
                reason="Hit 50% of defined max profit.",
            )
        max_loss_dollars = setup.max_loss * CONTRACT_MULTIPLIER * position.size.contracts
        if max_loss_dollars > 0 and position.current_pnl <= -2 * max_profit_dollars:
            return ManagementAction(
                verdict=ManagementVerdict.ADJUST,
                reason="Down 2× credit — consider adjusting or closing the losing wing.",
            )
        today = self._today(market.as_of)
        if setup.legs:
            dte = (min(leg.contract.expiry for leg in setup.legs) - today).days
            if dte <= 7:
                return ManagementAction(
                    verdict=ManagementVerdict.CLOSE_TIME,
                    reason="≤7 DTE — pin risk on defined-risk structures.",
                )
        return ManagementAction(verdict=ManagementVerdict.HOLD, reason="No management trigger.")

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
        return min(candidates, key=lambda e: abs((e - today).days - self._config.preferred_dte))

    @staticmethod
    def _atm_iv(chain: OptionChain, expiry: date) -> float | None:
        legs = [c for c in chain.by_expiry(expiry) if c.implied_vol]
        if not legs:
            return None
        atm = min(legs, key=lambda c: abs(c.strike - chain.spot))
        return atm.implied_vol

    @staticmethod
    def _nearest_strike(contracts: list[OptionContract], strike: float) -> OptionContract | None:
        if not contracts or strike <= 0:
            return None
        return min(contracts, key=lambda c: abs(c.strike - strike))

    @staticmethod
    def _nearest_by_delta(
        contracts: list[OptionContract], target_abs_delta: float
    ) -> OptionContract | None:
        with_d = [c for c in contracts if c.delta is not None]
        if not with_d:
            return None
        return min(with_d, key=lambda c: abs(abs(c.delta or 0.0) - target_abs_delta))

    # --------------------------------------------------------- structure builders
    def _build_iron_condor(
        self,
        chain: OptionChain,
        legs_for_expiry: list[OptionContract],
        width: float,
        t: float,
        atm_iv: float,
    ) -> _Candidate | None:
        calls = [c for c in legs_for_expiry if c.right is OptionRight.CALL]
        puts = [c for c in legs_for_expiry if c.right is OptionRight.PUT]
        short_call = self._nearest_by_delta(
            [c for c in calls if c.strike >= chain.spot], self._config.condor_short_delta
        )
        short_put = self._nearest_by_delta(
            [p for p in puts if p.strike <= chain.spot], self._config.condor_short_delta
        )
        if not short_call or not short_put:
            return None
        long_call = self._nearest_strike(calls, short_call.strike + width)
        long_put = self._nearest_strike(puts, short_put.strike - width)
        if not long_call or not long_put or long_call.strike <= short_call.strike or long_put.strike >= short_put.strike:
            return None
        credit = (short_call.mid + short_put.mid) - (long_call.mid + long_put.mid)
        call_wing = long_call.strike - short_call.strike
        put_wing = short_put.strike - long_put.strike
        max_profit = max(credit, 0.0)
        # Asymmetric-safe: each side caps at its own wing width minus credit.
        max_loss = max(max(call_wing, put_wing) - credit, 0.01)
        breakevens = [short_put.strike - credit, short_call.strike + credit]
        pop = pop_between(breakevens[0], breakevens[1], chain.spot, t, atm_iv, chain.risk_free_rate)
        pot_up = prob_touch(short_call.strike, chain.spot, t, atm_iv, chain.risk_free_rate)
        pot_lo = prob_touch(short_put.strike, chain.spot, t, atm_iv, chain.risk_free_rate)
        return _Candidate(
            label=f"iron_condor_{int(width)}w",
            legs=[
                TradeLeg(contract=long_put, quantity=1),
                TradeLeg(contract=short_put, quantity=-1),
                TradeLeg(contract=short_call, quantity=-1),
                TradeLeg(contract=long_call, quantity=1),
            ],
            max_profit=max_profit,
            max_loss=max_loss,
            breakevens=breakevens,
            pop=pop,
            pot_upper=pot_up,
            pot_lower=pot_lo,
            notes=[f"Wing {width:g} pts, ~{self._config.condor_short_delta:.2f}-delta shorts."],
        )

    def _build_iron_butterfly(
        self,
        chain: OptionChain,
        legs_for_expiry: list[OptionContract],
        t: float,
        atm_iv: float,
    ) -> _Candidate | None:
        calls = [c for c in legs_for_expiry if c.right is OptionRight.CALL]
        puts = [c for c in legs_for_expiry if c.right is OptionRight.PUT]
        short_call = self._nearest_strike(calls, chain.spot)
        short_put = self._nearest_strike(puts, chain.spot)
        if not short_call or not short_put or short_call.strike != short_put.strike:
            return None
        long_call = self._nearest_strike(calls, short_call.strike + self._config.fly_wing_offset)
        long_put = self._nearest_strike(puts, short_put.strike - self._config.fly_wing_offset)
        if not long_call or not long_put:
            return None
        credit = (short_call.mid + short_put.mid) - (long_call.mid + long_put.mid)
        call_wing = long_call.strike - short_call.strike
        put_wing = short_put.strike - long_put.strike
        max_profit = max(credit, 0.0)
        max_loss = max(max(call_wing, put_wing) - credit, 0.01)
        breakevens = [short_put.strike - credit, short_call.strike + credit]
        pop = pop_between(breakevens[0], breakevens[1], chain.spot, t, atm_iv, chain.risk_free_rate)
        pot_up = prob_touch(long_call.strike, chain.spot, t, atm_iv, chain.risk_free_rate)
        pot_lo = prob_touch(long_put.strike, chain.spot, t, atm_iv, chain.risk_free_rate)
        return _Candidate(
            label="iron_butterfly",
            legs=[
                TradeLeg(contract=long_put, quantity=1),
                TradeLeg(contract=short_put, quantity=-1),
                TradeLeg(contract=short_call, quantity=-1),
                TradeLeg(contract=long_call, quantity=1),
            ],
            max_profit=max_profit,
            max_loss=max_loss,
            breakevens=breakevens,
            pop=pop,
            pot_upper=pot_up,
            pot_lower=pot_lo,
            notes=["ATM body; higher credit, tighter profit zone than the condor."],
        )

    def _build_long_butterfly(
        self,
        chain: OptionChain,
        legs_for_expiry: list[OptionContract],
        t: float,
        atm_iv: float,
    ) -> _Candidate | None:
        calls = [c for c in legs_for_expiry if c.right is OptionRight.CALL]
        if len(calls) < 3:
            return None
        body = self._nearest_strike(calls, chain.spot)
        if body is None:
            return None
        lower = self._nearest_strike(calls, body.strike - self._config.fly_wing_offset)
        upper = self._nearest_strike(calls, body.strike + self._config.fly_wing_offset)
        if not lower or not upper or lower.strike >= body.strike or upper.strike <= body.strike:
            return None
        debit = (lower.mid + upper.mid) - 2 * body.mid
        if debit <= 0:
            return None  # arbitrage-free fly should cost money
        wing = upper.strike - body.strike
        max_profit = max(wing - debit, 0.01)
        max_loss = debit
        breakevens = [lower.strike + debit, upper.strike - debit]
        pop = pop_between(breakevens[0], breakevens[1], chain.spot, t, atm_iv, chain.risk_free_rate)
        pot_up = prob_touch(upper.strike, chain.spot, t, atm_iv, chain.risk_free_rate)
        pot_lo = prob_touch(lower.strike, chain.spot, t, atm_iv, chain.risk_free_rate)
        return _Candidate(
            label="long_call_butterfly",
            legs=[
                TradeLeg(contract=lower, quantity=1),
                TradeLeg(contract=body, quantity=-2),
                TradeLeg(contract=upper, quantity=1),
            ],
            max_profit=max_profit,
            max_loss=max_loss,
            breakevens=breakevens,
            pop=pop,
            pot_upper=pot_up,
            pot_lower=pot_lo,
            notes=["Debit structure — profit peaks at the body strike on expiration."],
        )

    def _build_broken_wing_butterfly(
        self,
        chain: OptionChain,
        legs_for_expiry: list[OptionContract],
        t: float,
        atm_iv: float,
    ) -> _Candidate | None:
        """Put-side broken-wing fly: buys a lower long, sells 2 middle shorts,
        buys a *closer* upper wing. Asymmetric — if built for a credit it has
        no risk on the upside, only downside.
        """
        puts = [c for c in legs_for_expiry if c.right is OptionRight.PUT]
        if len(puts) < 3:
            return None
        body = self._nearest_strike(puts, chain.spot - self._config.fly_wing_offset)
        if body is None:
            return None
        lower = self._nearest_strike(puts, body.strike - self._config.fly_wing_offset * 2)
        upper = self._nearest_strike(puts, body.strike + self._config.fly_wing_offset)
        if not lower or not upper or lower.strike >= body.strike or upper.strike <= body.strike:
            return None
        net = (upper.mid + lower.mid) - 2 * body.mid  # positive = debit
        lower_wing = body.strike - lower.strike
        upper_wing = upper.strike - body.strike
        if lower_wing <= upper_wing:
            return None  # not broken
        # Max loss is the wider wing minus the net credit (or plus debit).
        max_loss = max(lower_wing - upper_wing + net, 0.01)
        max_profit = max(upper_wing - net, 0.01)
        breakevens = [lower.strike + (lower_wing - max_profit), upper.strike - net]
        pop = pop_between(breakevens[0], breakevens[1], chain.spot, t, atm_iv, chain.risk_free_rate)
        pot_up = prob_touch(upper.strike, chain.spot, t, atm_iv, chain.risk_free_rate)
        pot_lo = prob_touch(lower.strike, chain.spot, t, atm_iv, chain.risk_free_rate)
        return _Candidate(
            label="broken_wing_put_fly",
            legs=[
                TradeLeg(contract=lower, quantity=1),
                TradeLeg(contract=body, quantity=-2),
                TradeLeg(contract=upper, quantity=1),
            ],
            max_profit=max_profit,
            max_loss=max_loss,
            breakevens=breakevens,
            pop=pop,
            pot_upper=pot_up,
            pot_lower=pot_lo,
            notes=["Broken-wing: wider lower wing carries the residual risk."],
        )

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
