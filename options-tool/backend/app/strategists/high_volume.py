"""High-volume / "Elite" premium-selling module.

This module exists *because* several influential educators advocate aggressive
scale-in-on-loss tactics without hard stops. Rather than re-implement that
literally, we treat high-volume as a **volume-and-journaling module** — we
allow the mechanics but require the caps and the journal to be surfaced.

Rules (explicit, auditable):

- Underlying setup is a wide short strangle (~8-delta) if IVR is available, or
  a delta-neutral covered structure otherwise. Both are UNDEFINED RISK and
  must surface ``max_theoretical_loss`` on entry.
- Every entry passes through :class:`app.risk.RiskGuard`:
    * per-ticker open-contract cap,
    * daily realized-loss cap (hard block, not a warning),
    * weekly realized-loss cap (hard block).
- If a position is losing, ``manage`` may suggest a scale-in add-on — but only
  if doing so keeps the total contracts on that ticker within the cap.
- No stop-loss is attached (that is the module's deliberate departure). The
  UI MUST show ``max_theoretical_loss`` because there is no floor otherwise.
- Every decision includes a journaling hint so the Phase-3 analytics surface
  can compare Kelly-implied size against actual size after the fact.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable

from app.core.models import (
    CONTRACT_MULTIPLIER,
    Account,
    Candidate,
    JournalEntry,
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
from app.risk.guard import RiskCaps, RiskGuard, RiskVerdict


@dataclass(frozen=True)
class HighVolumeConfig:
    short_delta: float = 0.08
    min_dte: int = 30
    max_dte: int = 70
    scale_in_loss_threshold: float = -0.50  # 50% of credit lost -> consider scale-in
    scale_in_max_multiplier: float = 2.0  # never double+ the original position
    kelly_fraction_override: float | None = 0.5  # aggressive by design, still fractional


class HighVolumeStrategist:
    name = "high_volume"

    def __init__(
        self,
        provider: DataProvider,
        journal: Iterable[JournalEntry] | None = None,
        risk_caps: RiskCaps | None = None,
        config: HighVolumeConfig | None = None,
    ):
        self._provider = provider
        self._journal = list(journal or [])
        self._risk_guard = RiskGuard(caps=risk_caps)
        self._config = config or HighVolumeConfig()

    @property
    def risk_guard(self) -> RiskGuard:
        return self._risk_guard

    def set_journal(self, journal: Iterable[JournalEntry]) -> None:
        self._journal = list(journal)

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
                        reason=setup.thesis,
                        score=setup.expected_value or 0.0,
                    )
                )
        return sorted(out, key=lambda c: c.score, reverse=True)

    # ----------------------------------------------------------------- analyze
    def analyze(
        self,
        ticker: str,
        chain: OptionChain,
        account: Account | None = None,
    ) -> TradeSetup | None:
        account = account or Account(cash=100_000)
        expiry = self._pick_expiry(chain)
        if expiry is None:
            return self._skip(ticker, "No expiry in 30–70 DTE window.")
        dte = (expiry - self._today(chain.as_of)).days

        legs_for_expiry = chain.by_expiry(expiry)
        calls = [c for c in legs_for_expiry if c.right is OptionRight.CALL and c.strike >= chain.spot]
        puts = [c for c in legs_for_expiry if c.right is OptionRight.PUT and c.strike <= chain.spot]
        short_call = self._nearest_by_delta(calls, self._config.short_delta)
        short_put = self._nearest_by_delta(puts, self._config.short_delta)
        if not short_call or not short_put:
            return self._skip(ticker, "No ~8-delta shorts available.")

        credit = short_call.mid + short_put.mid
        short_delta = (abs(short_call.delta or 0) + abs(short_put.delta or 0)) / 2
        pop = max(0.0, min(1.0, 1 - 2 * short_delta))
        breakevens = [short_put.strike - credit, short_call.strike + credit]
        # Max *theoretical* loss is conservative: spot could drop to 0 or rise infinitely.
        # We bound upward risk at 2× spot (a common worst-case assumption for equities).
        max_theoretical_loss = max(
            short_put.strike - credit,  # downside: put strike minus credit
            (2 * chain.spot - short_call.strike) - credit,
        )
        max_loss_for_sizing = max_theoretical_loss  # used by caps/sizing

        # Enforce risk caps on the *proposed* size (Kelly-implied) before returning.
        planned_size = self._kelly_contracts(credit, max_loss_for_sizing, pop, account)
        decision = self._risk_guard.check_entry(
            ticker=ticker,
            proposed_contracts=planned_size,
            account=account,
            journal=self._journal,
            as_of=chain.as_of,
        )
        notes = [
            "UNDEFINED RISK — there is no stop-loss on this module by design.",
            f"Max theoretical loss ${max_theoretical_loss:.0f}/spread surfaced at entry.",
            f"Risk guard: {decision.verdict.value} — {decision.reason}",
            f"Daily loss ${decision.daily_loss:,.0f} / weekly ${decision.weekly_loss:,.0f}.",
            "Journal every fill. Scale-in rules only fire inside the cap; see manage().",
        ]
        if not decision.allowed:
            return self._blocked(ticker, short_call, short_put, decision.reason, notes)

        return TradeSetup(
            ticker=ticker.upper(),
            strategy="wide_short_strangle",
            thesis=(
                f"High-volume ~{self._config.short_delta:.2f}-delta short strangle at {dte} DTE. "
                f"Credit ${credit:.2f}/spread, POP {pop * 100:.0f}%. Caps + journal are the discipline."
            ),
            legs=[
                TradeLeg(contract=short_call, quantity=-1),
                TradeLeg(contract=short_put, quantity=-1),
            ],
            net_credit=credit,
            max_profit=credit,
            max_loss=max_loss_for_sizing,
            max_theoretical_loss=max_theoretical_loss,
            breakevens=breakevens,
            pop=pop,
            expected_value=pop * credit - (1 - pop) * max_loss_for_sizing,
            iv_rank=None,
            iv_percentile=None,
            dte=dte,
            notes=notes,
        )

    # -------------------------------------------------------------------- size
    def size(self, setup: TradeSetup, account: Account) -> PositionSize:
        if setup.max_loss <= 0 or setup.net_credit <= 0:
            return PositionSize(
                contracts=0, capital_at_risk=0.0, pct_of_account=0.0,
                rationale="No credit or no risk reported — will not size.",
            )
        pop = setup.pop or 0.5
        contracts = self._kelly_contracts(setup.net_credit, setup.max_loss, pop, account)
        decision = self._risk_guard.check_entry(
            ticker=setup.ticker,
            proposed_contracts=contracts,
            account=account,
            journal=self._journal,
            as_of=datetime.now(tz=timezone.utc),
        )
        if not decision.allowed:
            return PositionSize(
                contracts=0, capital_at_risk=0.0, pct_of_account=0.0,
                rationale=f"Blocked by risk guard: {decision.reason}",
            )
        per_contract_risk = setup.max_loss * CONTRACT_MULTIPLIER
        capital_at_risk = contracts * per_contract_risk
        return PositionSize(
            contracts=contracts,
            capital_at_risk=capital_at_risk,
            pct_of_account=capital_at_risk / account.cash if account.cash > 0 else 0.0,
            rationale=(
                f"High-volume fractional Kelly={self._config.kelly_fraction_override}, "
                f"capped by max_pct_per_trade={account.max_pct_per_trade:.0%} and RiskGuard."
            ),
        )

    # ------------------------------------------------------------------ manage
    def manage(self, position: Position, market: MarketSnapshot) -> ManagementAction:
        setup = position.setup
        max_profit_dollars = setup.max_profit * CONTRACT_MULTIPLIER * position.size.contracts
        if max_profit_dollars > 0 and position.current_pnl >= 0.5 * max_profit_dollars:
            return ManagementAction(
                verdict=ManagementVerdict.CLOSE_WINNER,
                reason="Hit 50% of credit — take the win even in high-volume mode.",
            )
        if max_profit_dollars > 0 and position.current_pnl <= self._config.scale_in_loss_threshold * max_profit_dollars:
            return self._scale_in_or_halt(position, market)
        return ManagementAction(
            verdict=ManagementVerdict.HOLD,
            reason="Within tolerance; no management action triggered.",
        )

    # ===================================================================== utils
    @staticmethod
    def _today(as_of: datetime) -> date:
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        return as_of.astimezone(timezone.utc).date()

    def _pick_expiry(self, chain: OptionChain) -> date | None:
        today = self._today(chain.as_of)
        cands = [e for e in chain.expiries() if self._config.min_dte <= (e - today).days <= self._config.max_dte]
        if not cands:
            return None
        return min(cands, key=lambda e: abs((e - today).days - 45))

    @staticmethod
    def _nearest_by_delta(
        contracts: list[OptionContract], target_abs_delta: float
    ) -> OptionContract | None:
        with_d = [c for c in contracts if c.delta is not None]
        if not with_d:
            return None
        return min(with_d, key=lambda c: abs(abs(c.delta or 0.0) - target_abs_delta))

    def _kelly_contracts(
        self, credit: float, max_loss: float, pop: float, account: Account
    ) -> int:
        if credit <= 0 or max_loss <= 0:
            return 0
        kelly_raw = (pop * credit - (1 - pop) * max_loss) / (credit * max_loss)
        fraction = max(kelly_raw, 0.0) * (
            self._config.kelly_fraction_override
            if self._config.kelly_fraction_override is not None
            else account.kelly_fraction
        )
        budget_kelly = fraction * account.cash
        budget_cap = account.max_pct_per_trade * account.cash
        budget = min(budget_kelly, budget_cap)
        per_contract_risk = max_loss * CONTRACT_MULTIPLIER
        return int(budget // per_contract_risk)

    def _scale_in_or_halt(self, position: Position, market: MarketSnapshot) -> ManagementAction:
        current_contracts = position.size.contracts
        cap = self._risk_guard.caps.max_contracts_per_ticker
        max_additional = max(
            0,
            min(
                int(current_contracts * (self._config.scale_in_max_multiplier - 1)),
                cap - current_contracts,
            ),
        )
        if max_additional == 0:
            return ManagementAction(
                verdict=ManagementVerdict.CLOSE_TIME,
                reason=(
                    "Down >50% of credit and already at per-ticker cap. "
                    "No room to scale in — close or reduce."
                ),
                suggested_action="Close or trim the losing side.",
            )
        decision = self._risk_guard.check_entry(
            ticker=position.setup.ticker,
            proposed_contracts=max_additional,
            account=Account(cash=1),  # size is capped by contract count here
            journal=self._journal,
            as_of=market.as_of,
        )
        if not decision.allowed:
            return ManagementAction(
                verdict=ManagementVerdict.CLOSE_TIME,
                reason=f"Scale-in blocked by risk guard: {decision.reason}",
                suggested_action="Close or reduce instead of adding.",
            )
        return ManagementAction(
            verdict=ManagementVerdict.ADJUST,
            reason=(
                f"Down >50% of credit. Scale-in permitted: up to {max_additional} "
                f"additional contract(s) keeps position within per-ticker cap {cap}."
            ),
            suggested_action=f"Roll untested side or add up to {max_additional} more spreads.",
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

    def _blocked(
        self,
        ticker: str,
        short_call: OptionContract,
        short_put: OptionContract,
        reason: str,
        notes: list[str],
    ) -> TradeSetup:
        """Return a skip with the would-be structure legs included for audit."""
        return TradeSetup(
            ticker=ticker.upper(),
            strategy="skip",
            thesis=f"High-volume entry blocked: {reason}",
            legs=[
                TradeLeg(contract=short_call, quantity=-1),
                TradeLeg(contract=short_put, quantity=-1),
            ],
            net_credit=0.0,
            max_profit=0.0,
            max_loss=0.0,
            max_theoretical_loss=None,
            breakevens=[],
            dte=max((short_call.expiry - self._today(short_call.as_of)).days, 0),
            notes=[reason, *notes],
        )
