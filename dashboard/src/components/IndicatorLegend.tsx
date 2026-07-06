import type { ChartSnapshot, IndicatorModule } from "@/types/chart";

import { BreakoutDashboard } from "@/components/BreakoutDashboard";



type Props = {

  snapshot: ChartSnapshot;

};



export function IndicatorLegend({ snapshot }: Props) {

  const active = new Set(snapshot.meta?.active_indicators ?? []);

  const hasActiveFilter = active.size > 0;



  const modules = (snapshot.modules ?? []).filter(

    (m) => !hasActiveFilter || active.has(m.name),

  );

  const breakout = snapshot.breakout;

  const showBreakout = breakout && (!hasActiveFilter || active.has("breakout_probability"));



  if (!modules.length && !showBreakout) {

    return null;

  }



  return (

    <div className="rounded-lg border border-surface-border bg-black/30 p-3">

      <div className="mb-2 flex flex-wrap items-center gap-2">

        <div className="text-xs font-medium uppercase tracking-wide text-slate-500">

          Indicadores (TradingView)

        </div>

        {snapshot.meta?.entry_strategy && (

          <span className="rounded bg-slate-800 px-2 py-0.5 text-[10px] uppercase text-slate-400">

            estratégia: {snapshot.meta.entry_strategy}

          </span>

        )}

      </div>

      <div className="flex flex-wrap gap-2">

        {modules.map((mod) => (

          <ModuleChip key={mod.name} mod={mod} />

        ))}

        {!modules.some((m) => m.name === "sniper") &&

          (snapshot.overlays ?? []).some((o) => o.id?.startsWith("sniper_")) && (

            <div className="rounded-lg border border-slate-700 bg-slate-800/50 px-2.5 py-1.5 text-xs text-slate-400">

              <div className="font-medium">Sniper Entry/Exit</div>

              <div className="mt-0.5">EMA 9 · EMA 21 · VWAP</div>

            </div>

          )}

      </div>

      {showBreakout && breakout && (
        <div className="mt-3 flex flex-wrap items-start gap-3">
          <div className="min-w-[200px] flex-1 rounded-md bg-slate-900/60 px-2 py-1.5 text-xs text-slate-400">
            <span className="font-medium text-violet-300">Breakout Probability</span>
            <div>
              {breakout.bias} · {breakout.probability_pct?.toFixed(1)}% · candle{" "}
              {breakout.prev_candle}
            </div>
            {(breakout.prob_high_pct != null || breakout.prob_low_pct != null) && (
              <div className="text-slate-500">
                High {breakout.prob_high_pct?.toFixed(1)}% · Low{" "}
                {breakout.prob_low_pct?.toFixed(1)}%
              </div>
            )}
            {breakout.reason && <div className="text-slate-500">{breakout.reason}</div>}
          </div>
          {breakout.backtest && <BreakoutDashboard breakout={breakout} />}
        </div>
      )}

    </div>

  );

}



function ModuleChip({ mod }: { mod: IndicatorModule }) {

  const ok = mod.triggered;

  return (

    <div

      className={`rounded-lg border px-2.5 py-1.5 text-xs ${

        ok

          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"

          : "border-slate-700 bg-slate-800/50 text-slate-400"

      }`}

      title={mod.reason}

    >

      <div className="font-medium">{mod.display_name ?? mod.name}</div>

      <div className="mt-0.5 flex flex-wrap gap-1.5">

        <span>{ok ? "✓ validou" : "✗ não validou"}</span>

        {mod.direction && <span>{mod.direction}</span>}

        {mod.confidence != null && <span>{(mod.confidence * 100).toFixed(0)}%</span>}

      </div>

    </div>

  );

}


