import { Card, CardContent } from "@/components/ui/Card";
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
    <Card className="overflow-hidden">
      <CardContent className={compact ? "space-y-3 p-4" : "space-y-4 p-5"}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`rounded-md px-2 py-0.5 text-xs font-semibold ${directionBadgeClass(
                  parsed.direction,
                )}`}
              >
                {parsed.direction ?? "—"}
              </span>
              <span className="text-sm font-medium text-white">{row.display_name}</span>
            </div>
            {!compact && row.kind === "pattern" && (
              <p className="mt-1 text-xs text-slate-500">{row.strategy.replace("pattern:", "")}</p>
            )}
          </div>
          <div className="text-right">
            <div
              className={`text-lg font-semibold ${pnlPositive ? "text-emerald-400" : "text-rose-400"}`}
            >
              {formatUsd(row.total_pnl_usd)}
            </div>
            <div className="text-xs text-slate-400">{formatPct(row.total_pnl_pct)}</div>
          </div>
        </div>

        {row.kind === "pattern" && (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {DISPLAY_KEYS.map((key) => {
              const value = parsed[key];
              if (!value || key === "direction" || key === "source") return null;
              return (
                <div key={key} className="rounded-lg bg-black/25 px-3 py-2">
                  <div className="text-[10px] uppercase tracking-wide text-slate-500">
                    {patternFieldLabel(key)}
                  </div>
                  <div className="text-sm text-slate-200">{value}</div>
                </div>
              );
            })}
          </div>
        )}

        <div className="flex flex-wrap gap-4 border-t border-surface-border pt-3 text-sm text-slate-400">
          <span>
            <span className="text-slate-500">Trades:</span> {row.trades}
          </span>
          <span>
            <span className="text-slate-500">Win rate:</span> {row.win_rate_pct.toFixed(1)}%
          </span>
          <span>
            <span className="text-slate-500">W/L:</span> {row.wins}/{row.losses}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
