import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PayoffPoint } from "../lib/payoff";

interface Props {
  points: PayoffPoint[];
  spot: number;
  breakevens: number[];
}

export function PayoffChart({ points, spot, breakevens }: Props) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={points} margin={{ top: 8, right: 16, bottom: 8, left: 16 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis dataKey="price" stroke="#94a3b8" tick={{ fontSize: 11 }} />
        <YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} />
        <Tooltip
          contentStyle={{ background: "#0f172a", border: "1px solid #334155" }}
          formatter={(v: number) => [`$${v.toFixed(0)}`, "P/L"]}
          labelFormatter={(label) => `Spot at expiry: $${label}`}
        />
        <ReferenceLine y={0} stroke="#64748b" />
        <ReferenceLine x={spot} stroke="#0ea5e9" label={{ value: "spot", fill: "#0ea5e9", fontSize: 11 }} />
        {breakevens.map((b) => (
          <ReferenceLine
            key={b}
            x={Number(b.toFixed(2))}
            stroke="#f59e0b"
            strokeDasharray="4 4"
          />
        ))}
        <Line type="monotone" dataKey="pnl" stroke="#22d3ee" dot={false} strokeWidth={2} />
      </LineChart>
    </ResponsiveContainer>
  );
}
