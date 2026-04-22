import { FormEvent, useState } from "react";
import { Banner } from "./components/Banner";
import { TradeCard } from "./components/TradeCard";
import { UnifiedCard } from "./components/UnifiedCard";
import { analyze, unifiedAnalyze } from "./lib/api";
import type { AnalyzeResponse, Bias, UnifiedResponse } from "./lib/api";

type Mode = "unified" | "sosnoff";

export function App() {
  const [ticker, setTicker] = useState("SPY");
  const [bias, setBias] = useState<Bias>("neutral");
  const [mode, setMode] = useState<Mode>("unified");
  const [single, setSingle] = useState<AnalyzeResponse | null>(null);
  const [unified, setUnified] = useState<UnifiedResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
        <header>
          <h1 className="text-3xl font-semibold">Options Analysis Tool</h1>
          <p className="text-slate-400 text-sm mt-1">
            Phase 2 · Sosnoff · Thorp · Saliba — unified trade card
          </p>
        </header>

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
            Enter a ticker to run the unified trade card. Every strategist runs
            in isolation and reports its own verdict side-by-side.
          </div>
        )}
      </div>
    </div>
  );
}
