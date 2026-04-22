import { useEffect, useState } from "react";
import type { AnalyticsResponse, JournalEntry } from "../lib/api";
import { journalAnalytics, listJournal } from "../lib/api";

function money(n: number): string {
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

export function JournalPanel() {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [analytics, setAnalytics] = useState<AnalyticsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const [e, a] = await Promise.all([listJournal(), journalAnalytics()]);
      setEntries(e);
      setAnalytics(a);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg">
      <div className="flex items-center justify-between p-4 border-b border-slate-800">
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-400">
            Trade Journal · paper fills
          </div>
          <div className="text-lg font-semibold">
            {analytics
              ? `${analytics.trades} trades · ${pct(analytics.win_rate)} win rate · expectancy ${money(analytics.expectancy)}`
              : "Loading…"}
          </div>
        </div>
        <button
          type="button"
          onClick={refresh}
          className="text-sm bg-slate-800 hover:bg-slate-700 px-3 py-1 rounded"
        >
          Refresh
        </button>
      </div>

      {error && <div className="p-4 text-red-400 text-sm">{error}</div>}

      {analytics && analytics.closed_trades > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 p-4 text-sm">
          <Metric label="Closed" value={analytics.closed_trades.toString()} />
          <Metric label="Avg winner" value={money(analytics.average_winner)} emphasis="good" />
          <Metric label="Avg loser" value={money(analytics.average_loser)} emphasis="risk" />
          <Metric
            label="Profit factor"
            value={isFinite(analytics.profit_factor) ? analytics.profit_factor.toFixed(2) : "∞"}
          />
          <Metric label="Avg R" value={analytics.average_r.toFixed(2)} />
        </div>
      )}

      {analytics && analytics.kelly_implied_vs_actual.length > 0 && (
        <div className="px-4 pb-3">
          <div className="text-xs uppercase text-slate-500 mb-1">Kelly-implied vs actual (drift)</div>
          <div className="flex flex-wrap gap-2">
            {analytics.kelly_implied_vs_actual.map((d) => (
              <span
                key={d.id}
                className={`text-xs px-2 py-1 rounded border ${
                  Math.abs(d.drift_pct) > 0.5
                    ? "border-amber-500 text-amber-400"
                    : "border-slate-700 text-slate-400"
                }`}
              >
                {d.ticker} · {d.strategist}: {d.planned} → {d.actual} ({pct(d.drift_pct)})
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-950 text-slate-400">
            <tr>
              <Th>When</Th>
              <Th>Ticker</Th>
              <Th>Strategist</Th>
              <Th>Strategy</Th>
              <Th>Qty</Th>
              <Th>Outcome</Th>
              <Th>P/L</Th>
              <Th>R</Th>
            </tr>
          </thead>
          <tbody>
            {entries.length === 0 && (
              <tr>
                <td colSpan={8} className="text-center text-slate-500 py-6 text-xs">
                  No journal entries yet. POST to /api/journal/entries to record one.
                </td>
              </tr>
            )}
            {entries.map((e) => {
              const risk = e.max_loss * e.contracts * 100;
              const r = e.outcome === "open" || risk <= 0 ? null : e.realized_pnl / risk;
              return (
                <tr key={e.id ?? Math.random()} className="border-t border-slate-800">
                  <Td>{new Date(e.opened_at).toISOString().slice(0, 16).replace("T", " ")}</Td>
                  <Td className="font-mono">{e.ticker}</Td>
                  <Td>{e.strategist}</Td>
                  <Td>{e.strategy.replace(/_/g, " ")}</Td>
                  <Td className="font-mono">{e.contracts}</Td>
                  <Td>
                    <span className={outcomeColour(e.outcome)}>{e.outcome}</span>
                  </Td>
                  <Td className="font-mono">{e.outcome === "open" ? "—" : money(e.realized_pnl)}</Td>
                  <Td className="font-mono">{r === null ? "—" : r.toFixed(2)}</Td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function outcomeColour(outcome: string): string {
  switch (outcome) {
    case "win":
      return "text-emerald-400";
    case "loss":
      return "text-red-400";
    case "scratch":
      return "text-slate-400";
    default:
      return "text-slate-300";
  }
}

function Metric({
  label,
  value,
  emphasis,
}: {
  label: string;
  value: string;
  emphasis?: "risk" | "good";
}) {
  const colour =
    emphasis === "risk" ? "text-red-400" : emphasis === "good" ? "text-emerald-400" : "text-slate-200";
  return (
    <div className="bg-slate-950 border border-slate-800 rounded p-3">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className={`text-lg font-mono ${colour}`}>{value}</div>
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="text-left px-3 py-2 font-medium">{children}</th>;
}

function Td({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <td className={`px-3 py-2 ${className ?? ""}`}>{children}</td>;
}
