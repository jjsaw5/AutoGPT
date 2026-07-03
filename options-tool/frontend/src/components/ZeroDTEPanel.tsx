import { useState } from "react";
import type { ZeroDTESignal } from "../lib/api";
import { zeroDteSignals } from "../lib/api";

function Vote({ label, value }: { label: string; value: boolean }) {
  return (
    <span
      className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded ${
        value ? "bg-emerald-700 text-emerald-100" : "bg-slate-800 text-slate-400"
      }`}
    >
      {label}
    </span>
  );
}

export function ZeroDTEPanel() {
  const [ticker, setTicker] = useState("SPY");
  const [signal, setSignal] = useState<ZeroDTESignal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      setSignal(await zeroDteSignals(ticker.trim().toUpperCase()));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg">
      <div className="flex items-center justify-between p-4 border-b border-slate-800 gap-3">
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-400">
            0DTE signal log · SPY / SPX / QQQ only
          </div>
          <div className="text-lg font-semibold">
            Intraday signals (ORB + VWAP + dealer-gamma proxy)
          </div>
        </div>
        <form onSubmit={onSubmit} className="flex gap-2">
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            className="bg-slate-950 border border-slate-800 rounded px-3 py-1 font-mono w-24 text-sm"
            maxLength={8}
          />
          <button
            type="submit"
            disabled={loading}
            className="bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 rounded px-3 py-1 text-sm font-medium"
          >
            {loading ? "…" : "Fetch"}
          </button>
        </form>
      </div>

      {error && <div className="p-4 text-red-400 text-sm">{error}</div>}

      {signal && (
        <div className="p-4 space-y-3 text-sm">
          <div className="flex flex-wrap gap-3 items-center">
            <span className="bg-slate-800 px-2 py-1 rounded font-mono">
              {signal.ticker} · {signal.session_date}
            </span>
            <span
              className={`px-2 py-1 rounded uppercase tracking-wide text-xs ${
                signal.direction === "long"
                  ? "bg-emerald-700 text-emerald-100"
                  : "bg-red-700 text-red-100"
              }`}
            >
              {signal.direction}
            </span>
            <span className="text-slate-400">score {signal.score}/3</span>
            {signal.would_trade ? (
              <span className="text-emerald-400 text-xs">Would trade</span>
            ) : (
              <span className="text-slate-500 text-xs">No-trade (score or halt)</span>
            )}
          </div>

          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            <Tile label="Last" value={signal.last_close.toFixed(2)} />
            <Tile label="VWAP" value={signal.vwap.toFixed(2)} />
            <Tile
              label="OR high / low"
              value={`${signal.opening_range_high.toFixed(2)} / ${signal.opening_range_low.toFixed(2)}`}
            />
            <Tile label="GEX proxy" value={signal.gex_proxy.toFixed(3)} />
            <div className="bg-slate-950 border border-slate-800 rounded p-2 flex flex-col gap-1 text-center">
              <div className="text-xs uppercase text-slate-500">Votes</div>
              <div className="flex gap-1 justify-center">
                <Vote label="ORB" value={signal.orb_vote} />
                <Vote label="VWAP" value={signal.vwap_vote} />
                <Vote label="GEX" value={signal.gex_vote} />
              </div>
            </div>
          </div>

          {signal.notes.length > 0 && (
            <ul className="text-xs text-amber-500 list-disc list-inside space-y-1">
              {signal.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {!signal && !error && (
        <div className="p-4 text-slate-500 text-sm">
          Fetch a 0DTE signal for SPY, SPX, or QQQ. Every setup carries a hard
          stop-loss and the session halts automatically after N losses or a
          drawdown cap.
        </div>
      )}
    </div>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-slate-950 border border-slate-800 rounded p-2 text-center">
      <div className="text-[10px] uppercase text-slate-500">{label}</div>
      <div className="text-sm font-mono">{value}</div>
    </div>
  );
}
