import { useState } from "react";

import { TradingViewChart } from "@/components/TradingViewChart";
import { TradingViewWidget } from "@/components/TradingViewWidget";
import { Badge } from "@/components/ui/Badge";
import { formatDisplayTime } from "@/lib/timezone";
import type { AnalysisDecision } from "@/types/chart";
import { directionBadgeClass, stageLabel } from "@/lib/strategyPattern";
import { cn } from "@/lib/utils";

type Props = {
  items: AnalysisDecision[];
  kind: "rejection" | "approval";
  expanded: string | null;
  onToggle: (id: string) => void;
  emptyMessage: string;
  utcOffsetHours?: number;
};

type ChartView = "snapshot" | "live";

export function AnalysisDecisionList({
  items,
  kind,
  expanded,
  onToggle,
  emptyMessage,
  utcOffsetHours = 0,
}: Props) {
  const isApproval = kind === "approval";

  return (
    <div className="max-h-[70vh] space-y-3 overflow-auto pr-1">
      {items.map((item, i) => {
        const id = String(item.id ?? i);
        const isOpen = expanded === id;
        const when = isApproval ? item.approved_at : item.rejected_at;
        const label = isApproval ? item.summary : item.reason;

        return (
          <DecisionCard
            key={id}
            item={item}
            isApproval={isApproval}
            isOpen={isOpen}
            when={when}
            label={label}
            utcOffsetHours={utcOffsetHours}
            onToggle={() => onToggle(isOpen ? "" : id)}
          />
        );
      })}
      {!items.length && <p className="text-slate-500">{emptyMessage}</p>}
    </div>
  );
}

function DecisionCard({
  item,
  isApproval,
  isOpen,
  when,
  label,
  utcOffsetHours,
  onToggle,
}: {
  item: AnalysisDecision;
  isApproval: boolean;
  isOpen: boolean;
  when?: string;
  label?: string;
  utcOffsetHours: number;
  onToggle: () => void;
}) {
  const [chartView, setChartView] = useState<ChartView>("snapshot");
  const snap = item.chart_snapshot;

  return (
    <div
      className={cn(
        "rounded-xl border bg-void/40 p-4 transition",
        isApproval ? "border-profit/20" : "border-surface-border hover:border-surface-border/80",
      )}
    >
      <button
        type="button"
        className="flex w-full items-start justify-between gap-3 text-left"
        onClick={onToggle}
      >
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-white">{item.symbol}</span>
            {item.direction && (
              <span
                className={`rounded px-1.5 py-0.5 text-xs ${directionBadgeClass(item.direction)}`}
              >
                {item.direction}
              </span>
            )}
            {isApproval ? (
              <Badge variant="profit">Aprovado</Badge>
            ) : (
              <Badge variant="neutral">{stageLabel(String(item.stage ?? ""))}</Badge>
            )}
            {item.strategy && <Badge variant="brand">{item.strategy}</Badge>}
            <span className="text-xs text-slate-600">{item.source}</span>
            {item.confidence != null && (
              <span className="font-mono text-xs tabular-nums text-brand">
                P(win) {(item.confidence * 100).toFixed(0)}%
              </span>
            )}
          </div>
          <div className="mt-1 text-sm text-slate-400">{label}</div>
          {when && (
            <div className="mt-1 text-xs text-slate-600">
              {formatDisplayTime(String(when), utcOffsetHours)}
            </div>
          )}
        </div>
        <span className="shrink-0 text-xs font-medium text-brand">{isOpen ? "Fechar" : "Ver foto"}</span>
      </button>

      {isOpen && (
        <div className="mt-4 space-y-3 border-t border-surface-border pt-4">
          <p className="text-xs text-slate-500">
            Foto congelada: 120 candles no momento da decisão. Indicadores Pine rodam via PineTS
            em cima desse snapshot.
          </p>

          <div className="flex gap-2">
            <ChartTab
              active={chartView === "snapshot"}
              onClick={() => setChartView("snapshot")}
              label="Foto do momento"
            />
            {item.symbol && (
              <ChartTab
                active={chartView === "live"}
                onClick={() => setChartView("live")}
                label="TradingView live"
              />
            )}
          </div>

          {chartView === "snapshot" && snap && (
            <TradingViewChart snapshot={snap} utcOffsetHours={utcOffsetHours} />
          )}

          {chartView === "snapshot" && !snap && (
            <p className="text-xs text-slate-500">
              Snapshot indisponível — só decisões novas após esta atualização.
            </p>
          )}

          {chartView === "live" && item.symbol && (
            <TradingViewWidget symbol={item.symbol} timeframe={snap?.timeframe ?? "5m"} />
          )}
        </div>
      )}
    </div>
  );
}

function ChartTab({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-lg px-3 py-1.5 text-xs font-medium transition",
        active ? "bg-brand/15 text-brand" : "bg-void/50 text-slate-400 hover:text-white",
      )}
    >
      {label}
    </button>
  );
}
