import {
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export type ChartSnapshot = {
  timeframe?: string;
  candles?: {
    t: number;
    o: number;
    h: number;
    l: number;
    c: number;
    v?: number;
  }[];
  levels?: Record<string, number | number[]>;
};

type Props = {
  snapshot: ChartSnapshot;
  height?: number;
};

export function RejectionChart({ snapshot, height = 180 }: Props) {
  const candles = snapshot.candles ?? [];
  if (!candles.length) {
    return (
      <div className="flex h-32 items-center justify-center rounded-lg bg-black/20 text-xs text-slate-500">
        Sem snapshot de gráfico (apenas rejeições novas)
      </div>
    );
  }

  const data = candles.map((c) => ({
    t: c.t,
    close: c.c,
    high: c.h,
    low: c.l,
  }));

  const levels = snapshot.levels ?? {};
  const levelLines = Object.entries(levels).flatMap(([name, value]) => {
    if (Array.isArray(value)) {
      return value.map((v, i) => ({ name: `${name}${i + 1}`, value: v }));
    }
    return [{ name, value: Number(value) }];
  });

  return (
    <div className="space-y-2">
      <div className="text-xs text-slate-500">
        Snapshot {snapshot.timeframe ?? "5m"} · {candles.length} candles
      </div>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data}>
            <CartesianGrid stroke="#1f2937" strokeDasharray="3 3" />
            <XAxis
              dataKey="t"
              hide
            />
            <YAxis
              stroke="#94a3b8"
              fontSize={10}
              domain={["auto", "auto"]}
              tickFormatter={(v) => Number(v).toFixed(4)}
            />
            <Tooltip
              contentStyle={{ background: "#111827", border: "1px solid #1f2937" }}
              labelFormatter={(t) => new Date(Number(t)).toLocaleString()}
              formatter={(value, name) => [Number(value).toFixed(6), String(name)]}
            />
            <Line type="monotone" dataKey="close" stroke="#22d3ee" dot={false} strokeWidth={1.5} />
            {levelLines.map((lvl) => (
              <Line
                key={lvl.name}
                type="monotone"
                dataKey={() => lvl.value}
                stroke="#a78bfa"
                strokeDasharray="4 4"
                dot={false}
                strokeWidth={1}
                name={lvl.name}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
