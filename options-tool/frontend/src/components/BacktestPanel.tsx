import { FormEvent, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { BacktestRequest, BacktestResult, BacktestStrategist } from "../lib/api";
import { runBacktest } from "../lib/api";

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

function fmt(n: number): string {
  if (!isFinite(n)) return "∞";
  return n.toFixed(2);
}

export function BacktestPanel() {
  const [form, setForm] = useState<{
    strategist: BacktestStrategist;
    start: string;
    end: string;
    base_spot: number;
    base_iv: number;
    fixed_contracts: string;
  }>({
    strategist: "saliba",
    start: "2025-06-02",
    end: "2025-09-30",
    base_spot: 100,
    base_iv: 0.35,
    fixed_contracts: "2",
  });
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const req: BacktestRequest = {
        ticker: "SPY",
        strategist: form.strategist,
        start: form.start,
        end: form.end,
        account: DEFAULT_ACCOUNT,
        base_spot: form.base_spot,
        base_iv: form.base_iv,
        fixed_contracts: form.fixed_contracts.trim() === "" ? null : Number(form.fixed_contracts),
      };
      setResult(await runBacktest(req));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
        <div className="text-xs uppercase tracking-wide text-slate-400">Backtest harness</div>
        <div className="text-lg font-semibold mb-3">
          Replay a strategist against a synthetic market path
        </div>
        <form onSubmit={onSubmit} className="flex flex-wrap gap-3 items-end">
          <label className="flex flex-col text-sm">
            <span className="text-slate-400 text-xs uppercase mb-1">Strategist</span>
            <select
              value={form.strategist}
              onChange={(e) =>
                setForm({ ...form, strategist: e.target.value as BacktestStrategist })
              }
              className="bg-slate-950 border border-slate-800 rounded px-3 py-2"
            >
              <option value="saliba">Saliba</option>
              <option value="sosnoff">Sosnoff</option>
              <option value="thorp">Thorp</option>
              <option value="high_volume">High-volume</option>
            </select>
          </label>
          <label className="flex flex-col text-sm">
            <span className="text-slate-400 text-xs uppercase mb-1">Start</span>
            <input
              type="date"
              value={form.start}
              onChange={(e) => setForm({ ...form, start: e.target.value })}
              className="bg-slate-950 border border-slate-800 rounded px-3 py-2 font-mono"
            />
          </label>
          <label className="flex flex-col text-sm">
            <span className="text-slate-400 text-xs uppercase mb-1">End</span>
            <input
              type="date"
              value={form.end}
              onChange={(e) => setForm({ ...form, end: e.target.value })}
              className="bg-slate-950 border border-slate-800 rounded px-3 py-2 font-mono"
            />
          </label>
          <label className="flex flex-col text-sm">
            <span className="text-slate-400 text-xs uppercase mb-1">Base IV</span>
            <input
              type="number"
              step="0.01"
              value={form.base_iv}
              onChange={(e) => setForm({ ...form, base_iv: Number(e.target.value) })}
              className="bg-slate-950 border border-slate-800 rounded px-3 py-2 font-mono w-24"
            />
          </label>
          <label className="flex flex-col text-sm">
            <span className="text-slate-400 text-xs uppercase mb-1">Fixed contracts</span>
            <input
              type="number"
              value={form.fixed_contracts}
              onChange={(e) => setForm({ ...form, fixed_contracts: e.target.value })}
              className="bg-slate-950 border border-slate-800 rounded px-3 py-2 font-mono w-24"
              placeholder="(Kelly)"
            />
          </label>
          <button
            type="submit"
            disabled={loading}
            className="bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 rounded px-4 py-2 text-sm font-medium"
          >
            {loading ? "Running…" : "Run backtest"}
          </button>
        </form>
        {error && <div className="text-red-400 text-sm mt-2">{error}</div>}
        <p className="text-xs text-amber-500 mt-3">
          Synthetic market path — numbers are for engine validation, not strategy evaluation.
        </p>
      </div>

      {result && (
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4 space-y-4">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <div className="text-xs uppercase text-slate-400">
                {result.strategist.toUpperCase()} · {result.ticker}
              </div>
              <div className="text-lg font-semibold">
                {result.start} → {result.end}
              </div>
            </div>
            <div className="text-right">
              <div className="text-xs uppercase text-slate-400">Ending equity</div>
              <div className="text-2xl font-mono">{money(result.final_cash)}</div>
              <div className="text-xs text-slate-500">
                from {money(result.initial_cash)} · {result.trade_count} trades
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-6 gap-2 text-sm">
            <Metric label="CAGR" value={pct(result.metrics.cagr)} tone="good" />
            <Metric label="Max DD" value={pct(result.metrics.max_drawdown)} tone="risk" />
            <Metric label="Sharpe" value={fmt(result.metrics.sharpe)} />
            <Metric label="Sortino" value={fmt(result.metrics.sortino)} />
            <Metric label="Win rate" value={pct(result.metrics.win_rate)} />
            <Metric label="Profit factor" value={fmt(result.metrics.profit_factor)} />
          </div>

          <div className="bg-slate-950 border border-slate-800 rounded p-2">
            <div className="text-xs uppercase text-slate-500 mb-1 px-2">Equity curve</div>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart
                data={result.equity_curve}
                margin={{ top: 8, right: 16, bottom: 8, left: 16 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis
                  dataKey="date"
                  stroke="#94a3b8"
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v: string) => v.slice(5)}
                />
                <YAxis
                  stroke="#94a3b8"
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v: number) => `$${Math.round(v / 1000)}k`}
                />
                <Tooltip
                  contentStyle={{ background: "#0f172a", border: "1px solid #334155" }}
                  formatter={(v: number) => [money(v), "equity"]}
                />
                <Line
                  type="monotone"
                  dataKey="equity"
                  stroke="#22d3ee"
                  dot={false}
                  strokeWidth={2}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "good" | "risk";
}) {
  const colour =
    tone === "good" ? "text-emerald-400" : tone === "risk" ? "text-red-400" : "text-slate-200";
  return (
    <div className="bg-slate-950 border border-slate-800 rounded p-3">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className={`text-lg font-mono ${colour}`}>{value}</div>
    </div>
  );
}
