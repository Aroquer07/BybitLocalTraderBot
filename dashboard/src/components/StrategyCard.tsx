import { Card, CardContent } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { formatPct, formatUsd } from "@/lib/utils";
import {
  directionBadgeClass,
  patternFieldLabel,
  type StrategyRank,
} from "@/lib/strategyPattern";

type Props = {
  row: StrategyRank;
  compact?: boolean;
};

const DISPLAY_KEYS = [
  "direction",
  "source",
  "imba",
  "conf",
  "kalman",
  "lev",
  "sl",
  "spread",
  "chart",
] as const;

export function StrategyCard({ row, compact = false }: Props) {
  const parsed = row.parsed ?? {};
  const pnlPositive = row.total_pnl_usd >= 0;

  return (
    <Card className="overflow-hidden transition hover:border-brand/20">
      <CardContent className={compact ? "space-y-3 p-4" : "space-y-4 p-5"}>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`rounded-md px-2 py-0.5 text-xs font-semibold ${directionBadgeClass(parsed.direction)}`}
              >
                {parsed.direction ?? "—"}
              </span>
              <span className="truncate text-sm font-semibold text-white">{row.display_name}</span>
            </div>
            {!compact && row.kind === "pattern" && (
              <p className="mt-1 truncate text-xs text-slate-500">{row.strategy.replace("pattern:", "")}</p>
            )}
          </div>
          <div className="text-right">
            <div
              className={`font-mono text-lg font-bold tabular-nums ${pnlPositive ? "text-profit" : "text-loss"}`}
            >
              {formatUsd(row.total_pnl_usd)}
            </div>
            <div className="font-mono text-xs tabular-nums text-slate-500">{formatPct(row.total_pnl_pct)}</div>
          </div>
        </div>

        {row.kind === "pattern" && !compact && (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {DISPLAY_KEYS.map((key) => {
              const value = parsed[key];
              if (!value || key === "direction" || key === "source") return null;
              return (
                <div key={key} className="rounded-lg border border-surface-border bg-void/40 px-3 py-2">
                  <div className="data-label">{patternFieldLabel(key)}</div>
                  <div className="mt-1 text-sm text-slate-200">{value}</div>
                </div>
              );
            })}
          </div>
        )}

        <div className="flex flex-wrap gap-4 border-t border-surface-border pt-3 text-xs text-slate-500">
          <span>
            <span className="text-slate-600">Trades</span>{" "}
            <span className="font-mono tabular-nums text-slate-300">{row.trades}</span>
          </span>
          <span>
            <span className="text-slate-600">WR</span>{" "}
            <span className="font-mono tabular-nums text-slate-300">{row.win_rate_pct.toFixed(1)}%</span>
          </span>
          <Badge variant="neutral" className="normal-case">
            {row.wins}W / {row.losses}L
          </Badge>
        </div>
      </CardContent>
    </Card>
  );
}
