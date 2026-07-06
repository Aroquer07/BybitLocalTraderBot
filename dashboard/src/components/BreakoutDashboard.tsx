import type { ChartSnapshot } from "@/types/chart";

type Props = {
  breakout: NonNullable<ChartSnapshot["breakout"]>;
};

export function BreakoutDashboard({ breakout }: Props) {
  const bt = breakout.backtest;
  if (!bt) return null;

  return (
    <div className="min-w-[140px] overflow-hidden rounded border border-slate-600/60 bg-black/50 text-[10px] shadow-sm">
      <div className="border-b border-slate-600/40 px-2 py-1 text-center text-[9px] font-medium uppercase tracking-wide text-slate-400">
        Breakout backtest
      </div>
      <div className="px-2 py-1 text-center font-semibold text-emerald-400">WIN: {bt.wins}</div>
      <div className="px-2 py-1 text-center font-semibold text-rose-400">LOSS: {bt.losses}</div>
      <div className="border-t border-slate-600/40 px-2 py-1 text-center text-slate-200">
        Profitability: {bt.win_rate_pct.toFixed(1)}%
      </div>
      <div className="border-t border-slate-600/40 px-2 py-1 text-center text-violet-300">
        {breakout.bias} · {breakout.probability_pct?.toFixed(1)}%
      </div>
    </div>
  );
}
