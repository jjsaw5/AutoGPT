"""Streamlit web UI for the options flow screener.

Run via the double-click launcher (launch.command on Mac, launch.bat on Windows)
or manually with: streamlit run app.py
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from options_flow_screener.llm import filter_spec_from_prompt, trade_plan
from options_flow_screener.screener import (
    TickerSummary,
    aggregate,
    alert_premium,
    apply_filters,
)
from options_flow_screener.unusual_whales import UnusualWhalesClient


load_dotenv(Path(__file__).parent / ".env")

st.set_page_config(page_title="Options Flow Screener", page_icon="📈", layout="wide")
st.title("📈 Institutional Options Flow Screener")
st.caption(
    "Type what you want to screen for in plain English. "
    "Claude parses it, Unusual Whales feeds the data, you get a ranked table."
)

missing = [
    name
    for name in ("UNUSUAL_WHALES_API_KEY", "ANTHROPIC_API_KEY")
    if not os.environ.get(name)
]
if missing:
    st.error(
        f"Missing API keys: {', '.join(missing)}. Open the `.env` file next to "
        "this app, paste your keys, save, and restart the launcher."
    )
    st.stop()


DEFAULT_PROMPT = (
    "Screen institutional options flow from the last session. Mid-cap stocks "
    "between $1B and $10B market cap. Minimum $30K premium per order. IV rank "
    "above 80%. At least 70% bullish flow. Volume/OI under 0.5. DTE between 15 "
    "and 60 days. Rank by bullish flow percent."
)

with st.form("screen_form"):
    prompt = st.text_area(
        "Your screen", value=DEFAULT_PROMPT, height=140,
        help="Describe filters in plain English — market cap, premium, IV rank, DTE, etc.",
    )
    c1, c2 = st.columns([1, 1])
    with c1:
        generate_plan = st.checkbox(
            "Also generate a trade plan for the top pick",
            value=False,
            help="Chains a second Claude call that checks news + earnings.",
        )
    with c2:
        model = st.selectbox(
            "Claude model",
            ["claude-sonnet-4-6", "claude-opus-4-7"],
            help="Sonnet is fast and cheap. Opus is smarter for the trade plan.",
        )
    submitted = st.form_submit_button("Run screen", type="primary")


async def run_screen(prompt: str, generate_plan: bool, model: str):
    spec = filter_spec_from_prompt(prompt, model=model)
    uw = UnusualWhalesClient.from_env()
    alerts = await uw.flow_alerts(
        min_premium=int(spec.premium_min_usd) if spec.premium_min_usd else None,
        min_dte=spec.dte_min,
        max_dte=spec.dte_max,
        max_vol_oi=spec.vol_oi_max,
        limit=1000,
    )
    if spec.premium_min_usd is not None:
        alerts = [a for a in alerts if alert_premium(a) >= spec.premium_min_usd]
    summaries = aggregate(alerts)
    results = apply_filters(summaries, spec)

    plan_text = None
    if generate_plan and results:
        top = results[0]
        news, earnings = await asyncio.gather(uw.news(top.ticker), uw.earnings(top.ticker))
        plan_text = trade_plan(top, news, earnings, user_prompt=prompt, model=model)
    return spec, len(alerts), results, plan_text


def summary_to_row(s: TickerSummary) -> dict:
    return {
        "Ticker": s.ticker,
        "Sector": s.sector or "—",
        "Mkt Cap": f"${s.market_cap/1e9:.2f}B" if s.market_cap else "—",
        "Bull $": f"${s.bullish_premium/1e3:.0f}K",
        "Bear $": f"${s.bearish_premium/1e3:.0f}K",
        "Bull %": f"{s.bullish_flow_pct:.0f}%",
        "IV Rank": f"{s.iv_rank:.0f}" if s.iv_rank is not None else "—",
        "Largest": f"${s.largest_order/1e3:.0f}K",
        "Open Interest": f"{s.open_interest:,}",
        "Vol/OI": f"{s.vol_oi:.2f}" if s.vol_oi is not None else "—",
        "Alerts": s.alert_count,
        "DTE": s.largest_dte if s.largest_dte is not None else "—",
    }


if submitted:
    try:
        with st.spinner("Asking Claude to parse your screen, then pulling flow data…"):
            spec, n_alerts, results, plan_text = asyncio.run(
                run_screen(prompt, generate_plan, model)
            )

        with st.expander("Parsed filter spec (sanity check)", expanded=False):
            st.json({k: v for k, v in spec.__dict__.items() if v is not None})

        st.caption(f"Fetched {n_alerts} alerts. {len(results)} tickers passed all filters.")

        if not results:
            st.warning("No tickers passed today. Try loosening filters and re-run.")
        else:
            st.subheader("Ranked candidates")
            st.dataframe(
                [summary_to_row(r) for r in results],
                use_container_width=True,
                hide_index=True,
            )
            if plan_text:
                st.subheader(f"Trade plan: {results[0].ticker}")
                st.markdown(plan_text)
    except Exception as e:
        st.error(f"Run failed: {type(e).__name__}: {e}")
