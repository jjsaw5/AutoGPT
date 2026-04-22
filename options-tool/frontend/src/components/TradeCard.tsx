import { useEffect, useMemo, useState } from "react";
import type { AnalyzeResponse, PositionSize } from "../lib/api";
import { size } from "../lib/api";
import { buildPayoff } from "../lib/payoff";
import { PayoffChart } from "./PayoffChart";

interface Props {
  result: AnalyzeResponse;
}

const DEFAULT_ACCOUNT = {
  cash: 100_000,
  kelly_fraction: 0.25,
  max_pct_per_trade: 0.05,
  max_total_deployed_pct: 0.5,
};

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

function money(n: number): string {
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

export function TradeCard({ result }: Props) {
  const { setup, spot, iv_rank, iv_percentile, ticker, bias } = result;
  const [sized, setSized] = useState<PositionSize | null>(null);

  useEffect(() => {
    if (!setup || setup.strategy === "skip") {
      setSized(null);
      return;
    }
    let cancelled = false;
    size(setup, DEFAULT_ACCOUNT)
      .then((s) => {
        if (!cancelled) setSized(s);
      })
      .catch(() => setSized(null));
    return () => {
      cancelled = true;
    };
  }, [setup]);

  const payoff = useMemo(
    () => (setup && setup.legs.length ? buildPayoff(setup, spot) : []),
    [setup, spot],
  );

  if (!setup) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-6">
        No setup returned. Provider may be offline.
      </div>
    );
  }

  const isSkip = setup.strategy === "skip";
  const isUndefinedRisk = setup.strategy === "short_strangle";

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
      <div className="flex items-center justify-between p-4 border-b border-slate-800">
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-400">Sosnoff / Tastytrade</div>
          <div className="text-2xl font-semibold">
            {ticker}{" "}
            <span className="text-slate-500 text-sm font-normal">
              spot {money(spot)} · bias {bias}
            </span>
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs uppercase text-slate-400">IVR / IVP</div>
          <div className="text-xl font-mono">
            {iv_rank.toFixed(0)} <span className="text-slate-500">/</span> {iv_percentile.toFixed(0)}
          </div>
        </div>
      </div>

      <div className="p-4 space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className="bg-slate-800 px-2 py-1 rounded text-xs uppercase tracking-wide">
            {setup.strategy.replace(/_/g, " ")}
          </span>
          <span className="text-slate-400 text-sm">{setup.dte} DTE</span>
          {setup.pop !== null && (
            <span className="text-slate-400 text-sm">POP {(setup.pop * 100).toFixed(0)}%</span>
          )}
        </div>
        <p className="text-slate-300">{setup.thesis}</p>

        {!isSkip && (
          <>
            {/* Risk is always shown before reward — a deliberate guardrail. */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
              <Metric label="Max loss" value={money(setup.max_loss * 100)} emphasis="risk" warn={isUndefinedRisk} />
              <Metric label="Max profit" value={money(setup.max_profit * 100)} emphasis="good" />
              <Metric label="Net credit" value={money(setup.net_credit * 100)} />
              <Metric label="Reward : Risk" value={(setup.max_profit / (setup.max_loss || 1)).toFixed(2)} />
            </div>

            {setup.breakevens.length > 0 && (
              <div className="text-sm text-slate-400">
                Breakevens:{" "}
                {setup.breakevens.map((b) => money(b)).join(" and ")}
              </div>
            )}

            <div className="bg-slate-950 border border-slate-800 rounded p-2">
              <div className="text-xs uppercase text-slate-500 mb-1 px-2">Payoff at expiry</div>
              <PayoffChart points={payoff} spot={spot} breakevens={setup.breakevens} />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
              <div className="bg-slate-950 border border-slate-800 rounded p-3">
                <div className="text-xs uppercase text-slate-500 mb-1">Legs</div>
                <ul className="font-mono text-xs space-y-1">
                  {setup.legs.map((leg, i) => (
                    <li key={i}>
                      {leg.quantity > 0 ? "+" : ""}
                      {leg.quantity} {leg.contract.right} {leg.contract.strike}
                      {"  "}
                      <span className="text-slate-500">
                        exp {leg.contract.expiry} · Δ{" "}
                        {leg.contract.delta !== null ? leg.contract.delta.toFixed(2) : "—"}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="bg-slate-950 border border-slate-800 rounded p-3">
                <div className="text-xs uppercase text-slate-500 mb-1">
                  Sizing · $100k paper account
                </div>
                {sized ? (
                  <div className="space-y-1 text-sm">
                    <div>
                      <span className="text-slate-400">Contracts: </span>
                      <span className="font-mono">{sized.contracts}</span>
                    </div>
                    <div>
                      <span className="text-slate-400">Capital at risk: </span>
                      <span className="font-mono">{money(sized.capital_at_risk)}</span>{" "}
                      <span className="text-slate-500">({pct(sized.pct_of_account)})</span>
                    </div>
                    <div className="text-xs text-slate-500">{sized.rationale}</div>
                  </div>
                ) : (
                  <div className="text-slate-500 text-sm">Sizing…</div>
                )}
              </div>
            </div>
          </>
        )}

        {setup.notes.length > 0 && (
          <ul className="text-xs text-amber-500 list-disc list-inside space-y-1">
            {setup.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  emphasis,
  warn,
}: {
  label: string;
  value: string;
  emphasis?: "risk" | "good";
  warn?: boolean;
}) {
  const colour =
    emphasis === "risk"
      ? "text-red-400"
      : emphasis === "good"
        ? "text-emerald-400"
        : "text-slate-200";
  return (
    <div className="bg-slate-950 border border-slate-800 rounded p-3">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className={`text-lg font-mono ${colour}`}>{value}</div>
      {warn && (
        <div className="text-[10px] uppercase tracking-wide text-amber-500 mt-1">
          undefined risk
        </div>
      )}
    </div>
  );
}
