import { FormEvent, useState } from "react";
import { BacktestPanel } from "./components/BacktestPanel";
import { Banner } from "./components/Banner";
import { JournalPanel } from "./components/JournalPanel";
import { RiskDashboardPanel } from "./components/RiskDashboardPanel";
import { TradeCard } from "./components/TradeCard";
import { UnifiedCard } from "./components/UnifiedCard";
import { ZeroDTEPanel } from "./components/ZeroDTEPanel";
import { analyze, unifiedAnalyze } from "./lib/api";
import type { AnalyzeResponse, Bias, UnifiedResponse } from "./lib/api";

type Mode = "unified" | "sosnoff";
type Tab = "analyze" | "risk" | "journal" | "zero-dte" | "backtest";

export function App() {
  const [ticker, setTicker] = useState("SPY");
  const [bias, setBias] = useState<Bias>("neutral");
  const [mode, setMode] = useState<Mode>("unified");
  const [single, setSingle] = useState<AnalyzeResponse | null>(null);
  const [unified, setUnified] = useState<UnifiedResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("analyze");

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const t = ticker.trim().toUpperCase();
      if (mode === "unified") {
        setUnified(await unifiedAnalyze(t, bias));
        setSingle(null);
      } else {
        setSingle(await analyze(t, bias));
        setUnified(null);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  const banner =
    unified?.banner ??
    single?.banner ??
    "Educational tool. Not financial advice. Paper trading only in v1.";

  return (
    <div className="min-h-screen flex flex-col">
      <Banner text={banner} />
      <div className="max-w-5xl w-full mx-auto p-6 space-y-6">
        <header className="flex items-end justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-3xl font-semibold">Options Analysis Tool</h1>
            <p className="text-slate-400 text-sm mt-1">
              Phase 3 · all five strategists · journal + 0DTE signals
            </p>
          </div>
          <nav className="flex gap-1 text-sm bg-slate-900 border border-slate-800 rounded overflow-hidden">
            {(["analyze", "risk", "journal", "zero-dte", "backtest"] as Tab[]).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={`px-3 py-1.5 ${
                  tab === t ? "bg-slate-800 text-slate-100" : "text-slate-400 hover:bg-slate-800/50"
                }`}
              >
                {t === "analyze"
                  ? "Analyze"
                  : t === "risk"
                    ? "Risk"
                    : t === "journal"
                      ? "Journal"
                      : t === "zero-dte"
                        ? "0DTE"
                        : "Backtest"}
              </button>
            ))}
          </nav>
        </header>

        {tab === "analyze" && (
          <>
            <form
              onSubmit={onSubmit}
              className="flex flex-wrap gap-3 items-end bg-slate-900 border border-slate-800 rounded-lg p-4"
            >
              <label className="flex flex-col text-sm">
                <span className="text-slate-400 text-xs uppercase mb-1">Ticker</span>
                <input
                  value={ticker}
                  onChange={(e) => setTicker(e.target.value)}
                  className="bg-slate-950 border border-slate-800 rounded px-3 py-2 font-mono w-28"
                  maxLength={8}
                />
              </label>
              <label className="flex flex-col text-sm">
                <span className="text-slate-400 text-xs uppercase mb-1">Bias</span>
                <select
                  value={bias}
                  onChange={(e) => setBias(e.target.value as Bias)}
                  className="bg-slate-950 border border-slate-800 rounded px-3 py-2"
                >
                  <option value="neutral">Neutral</option>
                  <option value="bullish">Bullish</option>
                  <option value="bearish">Bearish</option>
                </select>
              </label>
              <label className="flex flex-col text-sm">
                <span className="text-slate-400 text-xs uppercase mb-1">Mode</span>
                <select
                  value={mode}
                  onChange={(e) => setMode(e.target.value as Mode)}
                  className="bg-slate-950 border border-slate-800 rounded px-3 py-2"
                >
                  <option value="unified">Unified (all strategists)</option>
                  <option value="sosnoff">Sosnoff only</option>
                </select>
              </label>
              <button
                type="submit"
                disabled={loading}
                className="bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 rounded px-4 py-2 text-sm font-medium"
              >
                {loading ? "Analyzing…" : "Analyze"}
              </button>
              {error && <span className="text-red-400 text-sm">{error}</span>}
            </form>

            {unified && <UnifiedCard data={unified} />}
            {single && <TradeCard result={single} />}

            {!unified && !single && !error && (
              <div className="text-slate-500 text-sm">
                Enter a ticker. The unified card runs all five strategists side-by-side.
              </div>
            )}
          </>
        )}

        {tab === "risk" && <RiskDashboardPanel />}
        {tab === "journal" && <JournalPanel />}
        {tab === "zero-dte" && <ZeroDTEPanel />}
        {tab === "backtest" && <BacktestPanel />}
      </div>
    </div>
  );
}
