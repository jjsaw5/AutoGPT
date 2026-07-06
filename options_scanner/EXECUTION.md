# Execution policy — human-approved, never automated

The scanner is decision-support. Execution is a **separate, explicitly-invoked
action** with hard guardrails. This file is the contract for when and how the
agent may place an order. If a rule isn't here, the answer is "don't place it."

## The rule

The agent may place an order **only** when **you explicitly ask for a specific
trade, or approve a specific trade the agent proposed.** That's it.

- **No automated trading. Ever.** Nothing in a scan, session, schedule, or CI
  run places an order. `execution.auto_trade` is hard-off.
- **Per-trade.** Approval is per order. Approving one trade never authorizes the
  next. "Place the NFLX condor" authorizes exactly that order.
- **Recommend-only is still the default output.** GO / WATCH / confirmations are
  recommendations. They do not become orders until you say so.

## The flow (every placed order)

1. **You ask or approve** a specific trade.
2. **Confirm it first** — run the Robinhood confirmation layer (`confirm.py`) so
   the trade is priced on real quotes, not UW estimates. Don't place a REJECTED
   trade without you overriding explicitly.
3. **Preview** — `review_option_order` (non-executing) to show the exact legs,
   net credit/debit, max loss, and buying-power/margin impact.
4. **Final go** — you confirm the preview (or told the agent up front to place
   it directly). Only then:
5. **Place** — `place_option_order` with the exact previewed order.
6. **Log** — record the placed order to the journal (`log_placed_orders`), so
   the taken-trade track and calibration see the real fill.

## Account constraint (important)

The agent can only act on accounts where **`agentic_allowed = true`**:

- ✅ **Agentic** (`992952861`) — agent may place orders here (per this policy).
- ❌ **Individual** (`422644971`) — `agentic_allowed=false`; Robinhood blocks
  agent action. Trades here are **manual only** — the agent gives you the ticket.
- ❌ **Roth IRA** (`497083394`) — not in `tradable_accounts`.

`execution.tradable_accounts` in `config.yaml` is the allow-list; the agent
never places outside it.

## Order hygiene

- **Limit orders only** — never market. Default to the mid (or slightly worse
  for a credit) and don't chase.
- **Size to the risk caps** — the same %-of-account sizing the scanner uses
  (G6/G7). Default to the smallest sensible size (often 1 spread) unless you
  specify.
- **Size vs. buying power** — check the account can actually support the max
  loss / margin before placing.
- **Stop on any ambiguity** — unclear account, size, price, or a failed
  guardrail → ask, don't guess.

## What the agent still won't do

- Place, modify, or cancel an order you didn't explicitly request/approve.
- Trade an account not on the allow-list.
- Turn on any recurring/automated placement.
- Treat "it's a GO" or "it's CONFIRMED" as permission — those are analysis, not
  an instruction to trade.
