import { useCallback, useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { api, type ChartPayload } from "@/api/client";
import {
  buildEquityCurveFromTrades,
  equityCurveFromChartPayload,
  type EquityPoint,
} from "@/lib/equityCurve";
import { formatPct, formatUsd } from "@/lib/utils";

type ChartsView = ChartPayload & { equitySeries: EquityPoint[] };

const GRID = "rgba(148,163,184,0.08)";
const AXIS = "#64748B";

function SourceTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { payload: { pnl_pct: number; pnl_usd: number } }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised px-3 py-2 text-sm shadow-panel">
      <div className="font-medium text-white">{label}</div>
      <div className="font-mono tabular-nums text-profit">{formatUsd(row.pnl_usd)}</div>
      <div className="font-mono text-xs tabular-nums text-slate-500">{formatPct(row.pnl_pct)}</div>
    </div>
  );
}

function SymbolTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { payload: { pnl_pct: number; pnl_usd: number } }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised px-3 py-2 text-sm shadow-panel">
      <div className="font-medium text-white">{label}</div>
      <div className="font-mono tabular-nums text-brand">{formatUsd(row.pnl_usd)}</div>
      <div className="font-mono text-xs tabular-nums text-slate-500">{formatPct(row.pnl_pct)}</div>
    </div>
  );
}

export function ChartsPanel() {
  const [data, setData] = useState<ChartsView | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const charts = await api.charts();
        let equitySeries = equityCurveFromChartPayload(charts.equity_curve);
        if (equitySeries === null) {
          const { trades } = await api.trades();
          equitySeries = buildEquityCurveFromTrades(trades);
        }
        setData({ ...charts, equitySeries });
      } catch {
        setData(null);
      }
    })();
  }, []);

  if (!data) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-sm text-slate-500">Carregando gráficos...</CardContent>
      </Card>
    );
  }

  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <Card className="xl:col-span-2">
        <CardHeader>
          <CardTitle>Curva de equity</CardTitle>
        </CardHeader>
        <CardContent className="h-72 min-h-[18rem]">
          <ResponsiveContainer width="100%" height="100%" minHeight={288}>
            <AreaChart data={data.equitySeries}>
              <defs>
                <linearGradient id="pnl" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#34D399" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#34D399" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
              <XAxis dataKey="time" hide />
              <YAxis stroke={AXIS} fontSize={12} tickFormatter={(v) => `$${Number(v).toFixed(0)}`} />
              <Tooltip
                contentStyle={{ background: "#101722", border: "1px solid rgba(148,163,184,0.12)" }}
                labelFormatter={(v) => new Date(String(v)).toLocaleString()}
                formatter={(value) => {
                  const n = typeof value === "number" ? value : Number(value);
                  return [formatUsd(n), "PnL acumulado"];
                }}
              />
              <Area
                type="monotone"
                dataKey="cumulative"
                baseValue={0}
                stroke="#34D399"
                fill="url(#pnl)"
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>PnL por fonte</CardTitle>
        </CardHeader>
        <CardContent className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data.pnl_by_source}>
              <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
              <XAxis dataKey="source" stroke={AXIS} fontSize={12} />
              <YAxis stroke={AXIS} fontSize={12} tickFormatter={(v) => `$${v}`} />
              <Tooltip content={<SourceTooltip />} />
              <Bar dataKey="pnl_usd" fill="#3D7EFF" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Top símbolos</CardTitle>
        </CardHeader>
        <CardContent className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data.top_symbols} layout="vertical">
              <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
              <XAxis type="number" stroke={AXIS} fontSize={12} tickFormatter={(v) => `$${v}`} />
              <YAxis type="category" dataKey="symbol" width={90} stroke={AXIS} fontSize={11} />
              <Tooltip content={<SymbolTooltip />} />
              <Bar dataKey="pnl_usd" fill="#FBBF24" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
    </div>
  );
}

export function ActivityLog() {
  const [lines, setLines] = useState<string[]>([]);
  const refresh = useCallback(() => {
    api.logs(60).then((r) => setLines(r.lines)).catch(() => setLines([]));
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 8000);
    return () => clearInterval(id);
  }, [refresh]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Log de atividade</CardTitle>
      </CardHeader>
      <CardContent>
        <pre className="max-h-80 overflow-auto rounded-lg border border-surface-border bg-void/60 p-4 font-mono text-xs leading-relaxed text-slate-400">
          {lines.length ? lines.join("\n") : "Sem logs. Inicie o bot via start.bat."}
        </pre>
      </CardContent>
    </Card>
  );
}
