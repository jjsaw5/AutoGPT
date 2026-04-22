import { FormEvent, useState } from "react";
import { Banner } from "./components/Banner";
import { TradeCard } from "./components/TradeCard";
import { analyze } from "./lib/api";
import type { AnalyzeResponse, Bias } from "./lib/api";

export function App() {
  const [ticker, setTicker] = useState("SPY");
  const [bias, setBias] = useState<Bias>("neutral");
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const r = await analyze(ticker.trim().toUpperCase(), bias);
      setResult(r);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  const banner =
    result?.banner ??
    "Educational tool. Not financial advice. Paper trading only in v1.";

  return (
    <div className="min-h-screen flex flex-col">
      <Banner text={banner} />
      <div className="max-w-4xl w-full mx-auto p-6 space-y-6">
        <header>
          <h1 className="text-3xl font-semibold">Options Analysis Tool</h1>
          <p className="text-slate-400 text-sm mt-1">
            Phase 1 · Sosnoff / Tastytrade premium-selling module
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
          <button
            type="submit"
            disabled={loading}
            className="bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 rounded px-4 py-2 text-sm font-medium"
          >
            {loading ? "Analyzing…" : "Analyze"}
          </button>
          {error && <span className="text-red-400 text-sm">{error}</span>}
        </form>

        {result && <TradeCard result={result} />}

        {!result && !error && (
          <div className="text-slate-500 text-sm">
            Enter a ticker to run the Sosnoff module. The default Mock provider
            returns a deterministic chain so the UI works offline.
          </div>
        )}
      </div>
    </div>
  );
}
