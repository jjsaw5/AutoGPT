"""Review an external options book through our framework's lens.

A "tool-box" utility: paste someone's posted plays (screenshot -> structured
rows) and get a framework-grounded critique — structure, direction, premium
regime, near-dated theta, and above all **concentration / correlation** (our G12
gate), which is what usually sinks a copied book.

The structural read needs no live data (that's the lightweight part). Vol-fit
(is buying premium justified?) and real EV need IV rank / a chain — layer those
on with the scanner when you want scores. This module is deliberately opinionated
toward *our* discipline: vol-regime-first, defined-risk, diversified, sized.
"""

from __future__ import annotations

import datetime
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ExternalPosition:
    """One leg of a posted book (as parsed from the screenshot/list)."""
    ticker: str
    option_type: str                 # "call" | "put"
    strike: float
    expiry: str                      # ISO date
    quantity: int = 1
    side: str = "long"               # "long" | "short"
    premium: Optional[float] = None  # per-contract price (per share)
    sector: Optional[str] = None     # for the correlation cluster (fill when known)
    underlying_price: Optional[float] = None


@dataclass
class PositionFlag:
    label: str
    ticker: str
    structure: str                   # naked_long_call | vertical_debit | ...
    direction: int                   # +1 bullish / -1 bearish
    dte: Optional[int]
    flags: list[str] = field(default_factory=list)


@dataclass
class BookReview:
    positions: list[PositionFlag]
    findings: list[str]              # book-level observations (framework vocabulary)
    verdict: str                     # one-line summary
    would_do: list[str]              # what our framework would do instead


def _dte(expiry: str, today: datetime.date) -> Optional[int]:
    try:
        return (datetime.date.fromisoformat(expiry) - today).days
    except ValueError:
        return None


def _direction(option_type: str, side: str) -> int:
    long = side == "long"
    if option_type == "call":
        return 1 if long else -1
    return -1 if long else 1          # long put bearish, short put bullish


def _detect_spreads(positions: list[ExternalPosition]):
    """Group same-ticker/expiry/type long+short into verticals; rest are singles.

    Returns a list of ('vertical'|'single', [positions]) groups.
    """
    groups: dict[tuple, list[ExternalPosition]] = {}
    for p in positions:
        groups.setdefault((p.ticker, p.expiry, p.option_type), []).append(p)
    out = []
    for _key, legs in groups.items():
        longs = [l for l in legs if l.side == "long"]
        shorts = [l for l in legs if l.side == "short"]
        while longs and shorts:                      # pair a long with a short = vertical
            out.append(("vertical", [longs.pop(), shorts.pop()]))
        for leg in longs + shorts:                   # leftovers are singles
            out.append(("single", [leg]))
    return out


def _structure_name(kind: str, legs: list[ExternalPosition]) -> str:
    if kind == "vertical":
        credit = any(l.side == "short" for l in legs) and legs[0].option_type
        return f"{legs[0].option_type}_vertical"
    leg = legs[0]
    return f"{'naked_long' if leg.side == 'long' else 'naked_short'}_{leg.option_type}"


def _fmt(leg: ExternalPosition) -> str:
    return f"{leg.ticker} ${leg.strike:g}{leg.option_type[0].upper()} {leg.expiry[5:]}"


def review_book(
    positions: list[ExternalPosition], *, now: datetime.datetime,
) -> BookReview:
    today = now.date()
    flags: list[PositionFlag] = []

    for kind, legs in _detect_spreads(positions):
        leg = legs[0]
        dte = _dte(leg.expiry, today)
        direction = _direction(leg.option_type, leg.side)
        structure = _structure_name(kind, legs)
        pf: list[str] = []

        if kind == "single" and leg.side == "long":
            pf.append("naked long premium — full cost at risk; a debit spread caps it")
        if dte is not None:
            if dte <= 1:
                pf.append("0DTE — maximum gamma/theta")
            elif dte <= 7:
                pf.append(f"near-dated (~{dte}d) — steep theta / late-entry")
            elif dte <= 21:
                pf.append(f"short-dated (~{dte}d)")
        # moneyness / lottery
        if leg.underlying_price and leg.option_type == "call":
            otm = (leg.strike - leg.underlying_price) / leg.underlying_price
            if otm > 0.05 and (dte is None or dte <= 14):
                pf.append(f"deep OTM (+{otm:.0%}) + near-dated — lottery ticket")
        elif leg.premium is not None and leg.premium < 1.0 and (dte is not None and dte <= 10):
            pf.append("cheap near-dated call — likely OTM lottery (confirm vs spot)")

        flags.append(PositionFlag(
            label=_fmt(leg), ticker=leg.ticker, structure=structure,
            direction=direction, dte=dte, flags=pf,
        ))

    findings, would_do = _book_level(positions, flags)
    verdict = _verdict(flags, findings)
    return BookReview(positions=flags, findings=findings, verdict=verdict, would_do=would_do)


def _book_level(positions: list[ExternalPosition], flags: list[PositionFlag]):
    n = len(flags)
    findings: list[str] = []
    would_do: list[str] = []

    # Direction concentration.
    dirs = [f.direction for f in flags]
    if n and all(d == 1 for d in dirs):
        findings.append(f"100% one-directional (all bullish) across {n} positions — no hedge")
    elif n and all(d == -1 for d in dirs):
        findings.append(f"100% one-directional (all bearish) across {n} positions — no hedge")

    # Premium regime (long vs short).
    longs = sum(1 for p in positions if p.side == "long")
    if longs == len(positions) and positions:
        findings.append(
            "entirely long premium — vol-blind; only justified if IV is CHEAP "
            "(confirm IV rank — semis after a run are often rich)")
        would_do.append("check IV rank first: rich → SELL premium (credit spreads); cheap → BUY debit spreads")

    # Correlation / sector cluster (our G12).
    sectors = Counter(p.sector for p in positions if p.sector)
    if sectors:
        top_sector, cnt = sectors.most_common(1)[0]
        if cnt >= max(2, 0.5 * len(positions)):
            findings.append(
                f"{cnt}/{len(positions)} positions in {top_sector} — a correlated cluster; "
                "our G12 correlation cap would block most of these (they win/lose together)")
            would_do.append(f"keep ONE {top_sector} position, not {cnt} — the rest is redundant risk")

    # Naked vs defined.
    naked = sum(1 for f in flags if f.structure.startswith("naked"))
    if naked:
        findings.append(f"{naked}/{n} are naked singles, not defined-risk spreads")
        would_do.append("express direction as debit/credit spreads (defined risk, less vega/theta bleed)")

    # Near-dated exposure.
    near = sum(1 for f in flags if f.dte is not None and f.dte <= 7)
    if near:
        findings.append(f"{near}/{n} expire in ≤7 days — heavy theta/gamma; speculative-bucket territory")

    return findings, would_do


def _verdict(flags: list[PositionFlag], findings: list[str]) -> str:
    n = len(flags)
    naked = sum(1 for f in flags if f.structure.startswith("naked"))
    one_way = bool(flags) and len({f.direction for f in flags}) == 1
    clustered = any("correlated cluster" in f for f in findings)
    near = sum(1 for f in flags if f.dte is not None and f.dte <= 7)

    hard = sum([one_way, clustered, naked >= max(2, 0.6 * n), near >= max(1, 0.3 * n)])
    if hard >= 3:
        return ("PASS / restructure — concentrated, vol-blind, naked, near-dated: "
                "the opposite of our discipline. Our engine would reject or rebuild most of it.")
    if hard == 2:
        return "MIXED — some framework merit but real red flags; would restructure before touching."
    return "PLAUSIBLE — no glaring structural violations; score live for IV-fit / EV / catalyst."


def render_review(review: BookReview) -> str:
    lines = ["[R] EXTERNAL PLAY REVIEW  (through our framework — structural read)"]
    lines.append(f"  VERDICT: {review.verdict}")
    lines.append("")
    lines.append("  Positions:")
    for f in review.positions:
        d = "bull" if f.direction > 0 else "bear"
        dte = f"{f.dte}d" if f.dte is not None else "?"
        note = ("; ".join(f.flags)) or "no structural flag"
        lines.append(f"    {f.label:<22} {f.structure:<18} {d:<4} {dte:>4}  — {note}")
    lines.append("")
    lines.append("  Book-level findings:")
    for x in review.findings:
        lines.append(f"    • {x}")
    if review.would_do:
        lines.append("")
        lines.append("  What our framework would do instead:")
        for x in review.would_do:
            lines.append(f"    → {x}")
    return "\n".join(lines) + "\n"
