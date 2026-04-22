import { useState } from "react";
import type { StrategistResult, UnifiedResponse } from "../lib/api";
import { TradeCard } from "./TradeCard";
import type { AnalyzeResponse } from "../lib/api";

const STRATEGIST_LABELS: Record<string, string> = {
  sosnoff: "Sosnoff · premium selling",
  thorp: "Thorp · quant edge",
  saliba: "Saliba · defined risk",
  high_volume: "High-volume · wide short strangle",
  zero_dte: "0DTE · intraday signal + hard stop",
};

function Verdict({ value }: { value: StrategistResult["verdict"] }) {
  const colours: Record<StrategistResult["verdict"], string> = {
    trade: "bg-emerald-700 text-emerald-100",
    skip: "bg-slate-700 text-slate-300",
    error: "bg-red-800 text-red-100",
  };
  const label: Record<StrategistResult["verdict"], string> = {
    trade: "trade",
    skip: "skip",
    error: "error",
  };
  return (
    <span className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded ${colours[value]}`}>
      {label[value]}
    </span>
  );
}

function StrategistRow({
  result,
  expanded,
  onToggle,
  parentHeader,
}: {
  result: StrategistResult;
  expanded: boolean;
  onToggle: () => void;
  parentHeader: Omit<UnifiedResponse, "results">;
}) {
  const canExpand = result.verdict === "trade" && result.setup !== null;
  return (
    <div className="border-b border-slate-800 last:border-b-0">
      <button
        type="button"
        onClick={canExpand ? onToggle : undefined}
        className={`w-full text-left p-3 flex items-center gap-3 ${
          canExpand ? "hover:bg-slate-800/50 cursor-pointer" : "cursor-default"
        }`}
        aria-expanded={expanded}
      >
        <div className="w-48 shrink-0">
          <div className="text-sm font-medium">
            {STRATEGIST_LABELS[result.name] ?? result.name}
          </div>
          <Verdict value={result.verdict} />
        </div>
        <div className="flex-1 text-sm text-slate-300">
          {result.error ? (
            <span className="text-red-400">{result.error}</span>
          ) : (
            result.headline
          )}
        </div>
        {canExpand && (
          <span className="text-slate-500 text-xs select-none">
            {expanded ? "collapse" : "expand"}
          </span>
        )}
      </button>
      {expanded && canExpand && result.setup && (
        <div className="bg-slate-950 p-4">
          <TradeCard
            result={
              {
                ticker: parentHeader.ticker,
                bias: parentHeader.bias,
                spot: parentHeader.spot,
                iv_rank: parentHeader.iv_rank,
                iv_percentile: parentHeader.iv_percentile,
                setup: result.setup,
                banner: parentHeader.banner,
              } as AnalyzeResponse
            }
          />
        </div>
      )}
    </div>
  );
}

export function UnifiedCard({ data }: { data: UnifiedResponse }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const { ticker, bias, spot, iv_rank, iv_percentile, banner, results } = data;
  const header = { ticker, bias, spot, iv_rank, iv_percentile, banner };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
      <div className="flex items-center justify-between p-4 border-b border-slate-800">
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-400">
            Unified Trade Card · all strategists
          </div>
          <div className="text-2xl font-semibold">
            {ticker}{" "}
            <span className="text-slate-500 text-sm font-normal">
              spot ${spot.toFixed(2)} · bias {bias}
            </span>
          </div>
        </div>
        <div className="text-right text-sm">
          <div className="text-xs uppercase text-slate-400">IVR / IVP</div>
          <div className="font-mono">
            {iv_rank.toFixed(0)} <span className="text-slate-500">/</span> {iv_percentile.toFixed(0)}
          </div>
        </div>
      </div>
      <div>
        {results.map((r) => (
          <StrategistRow
            key={r.name}
            result={r}
            expanded={expanded === r.name}
            onToggle={() => setExpanded((cur) => (cur === r.name ? null : r.name))}
            parentHeader={header}
          />
        ))}
      </div>
    </div>
  );
}
