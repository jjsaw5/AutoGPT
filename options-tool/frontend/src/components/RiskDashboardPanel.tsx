import { useEffect, useState } from "react";
import type { DashboardResponse, ExposureRow } from "../lib/api";
import { fetchBankroll, fetchDashboard } from "../lib/api";
import type { BankrollResponse } from "../lib/api";

const DEFAULT_ACCOUNT = {
  cash: 100_000,
  kelly_fraction: 0.25,
  max_pct_per_trade: 0.05,
  max_total_deployed_pct: 0.5,
};

function money(n: number): string {
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

export function RiskDashboardPanel() {
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [bankroll, setBankroll] = useState<BankrollResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const [d, b] = await Promise.all([
        fetchDashboard(DEFAULT_ACCOUNT),
        fetchBankroll(DEFAULT_ACCOUNT),
      ]);
      setDashboard(d);
      setBankroll(b);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-400">Risk dashboard</div>
          <div className="text-lg font-semibold">Open positions · aggregated Greeks · concentration</div>
        </div>
        <button
          type="button"
          onClick={refresh}
          className="text-sm bg-slate-800 hover:bg-slate-700 px-3 py-1 rounded"
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      {error && <div className="text-red-400 text-sm">{error}</div>}

      {dashboard && (
        <>
          {dashboard.warnings.length > 0 && (
            <div className="bg-slate-900 border border-amber-700 rounded-lg p-3 space-y-1">
              <div className="text-xs uppercase text-amber-400">
                {dashboard.warnings.length} warning{dashboard.warnings.length === 1 ? "" : "s"}
              </div>
              {dashboard.warnings.map((w, i) => (
                <div
                  key={i}
                  className={`text-sm ${w.severity === "critical" ? "text-red-400" : "text-amber-400"}`}
                >
                  • {w.message}
                </div>
              ))}
            </div>
          )}

          <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
            <div className="text-xs uppercase text-slate-500 mb-2">Portfolio Greeks</div>
            <div className="grid grid-cols-2 md:grid-cols-6 gap-2 text-sm">
              <Tile label="Open positions" value={dashboard.open_positions.toString()} />
              <Tile label="Total contracts" value={dashboard.total_contracts.toString()} />
              <Tile label="Delta" value={dashboard.greeks.delta.toFixed(0)} />
              <Tile label="Gamma" value={dashboard.greeks.gamma.toFixed(2)} />
              <Tile label="Theta" value={dashboard.greeks.theta.toFixed(0)} />
              <Tile label="Vega" value={dashboard.greeks.vega.toFixed(0)} />
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-sm mt-2">
              <Tile label="Capital at risk" value={money(dashboard.total_capital_at_risk)} />
              <Tile
                label="Max theoretical loss"
                value={money(dashboard.total_max_theoretical_loss)}
                tone="risk"
              />
              <Tile label="Notional" value={money(dashboard.greeks.notional)} />
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <ExposureCard title="By ticker" rows={dashboard.by_ticker} />
            <ExposureCard title="By strategist" rows={dashboard.by_strategist} />
          </div>
        </>
      )}

      {bankroll && (
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs uppercase text-slate-500">Bankroll</div>
              <div className="text-sm">
                Deployed {money(bankroll.total_deployed)} of {money(bankroll.total_cap)} total cap (
                {pct(bankroll.total_utilization)})
              </div>
            </div>
            {bankroll.over_total_cap && (
              <span className="text-xs px-2 py-0.5 rounded bg-red-800 text-red-100">
                OVER TOTAL CAP
              </span>
            )}
          </div>
          <UtilizationBar
            deployed={bankroll.total_deployed}
            cap={bankroll.total_cap}
            over={bankroll.over_total_cap}
          />
          <div className="space-y-2">
            {bankroll.allocations.map((a) => (
              <div key={a.name} className="bg-slate-950 border border-slate-800 rounded p-3">
                <div className="flex items-center justify-between text-sm">
                  <div>
                    <span className="font-medium">{a.name}</span>{" "}
                    <span className="text-slate-500 text-xs">
                      · kelly {a.kelly_fraction.toFixed(2)} · per-trade {pct(a.max_pct_per_trade)}
                    </span>
                  </div>
                  <div className="font-mono text-xs text-slate-400">
                    {money(a.deployed)} / {money(a.allocation_cash)} ({pct(a.utilization)})
                  </div>
                </div>
                <UtilizationBar
                  deployed={a.deployed}
                  cap={a.allocation_cash}
                  over={a.over_limit}
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {!dashboard && !error && !loading && (
        <div className="text-slate-500 text-sm">
          No open positions. Run a backtest or record a paper fill to populate the dashboard.
        </div>
      )}
    </div>
  );
}

function ExposureCard({ title, rows }: { title: string; rows: ExposureRow[] }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
      <div className="text-xs uppercase text-slate-500 mb-2">{title}</div>
      {rows.length === 0 ? (
        <div className="text-slate-500 text-sm">No open exposure.</div>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-slate-400">
            <tr>
              <th className="text-left font-medium py-1">Key</th>
              <th className="text-right font-medium py-1">Pos</th>
              <th className="text-right font-medium py-1">Qty</th>
              <th className="text-right font-medium py-1">Capital</th>
              <th className="text-right font-medium py-1">Max loss</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className="border-t border-slate-800">
                <td className="py-1 font-mono">{r.key}</td>
                <td className="py-1 text-right">{r.positions}</td>
                <td className="py-1 text-right">{r.contracts}</td>
                <td className="py-1 text-right font-mono">{money(r.capital_at_risk)}</td>
                <td className="py-1 text-right font-mono text-red-400">
                  {money(r.max_theoretical_loss)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function UtilizationBar({
  deployed,
  cap,
  over,
}: {
  deployed: number;
  cap: number;
  over: boolean;
}) {
  const pct = cap > 0 ? Math.min(deployed / cap, 1.5) : 0;
  const barWidth = Math.min(pct * 100, 100);
  return (
    <div className="h-2 bg-slate-800 rounded overflow-hidden">
      <div
        className={`h-full ${
          over ? "bg-red-500" : pct > 0.8 ? "bg-amber-500" : "bg-emerald-500"
        }`}
        style={{ width: `${barWidth}%` }}
      />
    </div>
  );
}

function Tile({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "risk";
}) {
  const colour = tone === "risk" ? "text-red-400" : "text-slate-200";
  return (
    <div className="bg-slate-950 border border-slate-800 rounded p-3">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className={`text-lg font-mono ${colour}`}>{value}</div>
    </div>
  );
}
