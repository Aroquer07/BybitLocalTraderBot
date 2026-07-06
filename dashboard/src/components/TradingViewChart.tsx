import { useEffect, useMemo, useRef } from "react";
import {
  ColorType,
  CrosshairMode,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";

import { IndicatorLegend } from "@/components/IndicatorLegend";
import { SniperDashboard } from "@/components/SniperDashboard";
import { usePineSnapshot } from "@/hooks/usePineSnapshot";
import { SNIPER_TP_COUNT } from "@/lib/pineCompat";
import { isSniperTradeLabel, mergeSnapshotWithPine } from "@/lib/pineToChart";
import { toChartTime, utcOffsetLabel } from "@/lib/timezone";
import type { PinePriceLine } from "@/lib/pineToChart";
import type { ChartOverlay, ChartSnapshot, TradeSetup } from "@/types/chart";

type Props = {
  snapshot: ChartSnapshot;
  height?: number;
  utcOffsetHours?: number;
};

function formatPrice(p: number): string {
  if (p >= 100) return p.toFixed(2);
  if (p >= 1) return p.toFixed(3);
  if (p >= 0.01) return p.toFixed(4);
  return p.toFixed(6);
}

function addEmaRibbonSeries(
  chart: IChartApi,
  overlay: ChartOverlay,
  chartTime: (ms: number) => UTCTimestamp,
): ISeriesApi<"Line">[] {
  const values = overlay.values ?? [];
  if (!values.length) return [];

  const bullColor = overlay.color_bull ?? "#22c55e";
  const bearColor = overlay.color_bear ?? "#ef4444";
  const seriesList: ISeriesApi<"Line">[] = [];

  const addRibbonLine = (pick: (pt: (typeof values)[0]) => number | undefined, title: string) => {
    let segment: { time: Time; value: number }[] = [];
    let segmentBull: boolean | null = null;

    const flush = () => {
      if (segment.length < 2 || segmentBull === null) return;
      const line = chart.addLineSeries({
        color: segmentBull ? bullColor : bearColor,
        lineWidth: 2,
        title,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      line.setData(segment);
      seriesList.push(line);
      segment = [];
    };

    for (const pt of values) {
      const v = pick(pt);
      if (v == null || Number.isNaN(v)) continue;
      const bull = pt.bull ?? true;
      if (segmentBull !== null && bull !== segmentBull) {
        segment.push({ time: chartTime(pt.t), value: v });
        flush();
        segment = [{ time: chartTime(pt.t), value: v }];
        segmentBull = bull;
      } else {
        segment.push({ time: chartTime(pt.t), value: v });
        segmentBull = bull;
      }
    }
    flush();
  };

  addRibbonLine((pt) => pt.ema9, overlay.label ?? "EMA Ribbon 9");
  addRibbonLine((pt) => pt.ema21, "EMA Ribbon 21");
  return seriesList;
}

function addTrendLineSeries(
  chart: IChartApi,
  overlay: ChartOverlay,
  chartTime: (ms: number) => UTCTimestamp,
): ISeriesApi<"Line">[] {
  const values = overlay.values ?? [];
  if (!values.length) return [];

  const bullColor = overlay.color_bull ?? "#84cc16";
  const bearColor = overlay.color_bear ?? "#ef4444";
  const seriesList: ISeriesApi<"Line">[] = [];
  let segment: { time: Time; value: number }[] = [];
  let segmentBull: boolean | null = null;

  const flush = () => {
    if (segment.length < 2 || segmentBull === null) return;
    const line = chart.addLineSeries({
      color: segmentBull ? bullColor : bearColor,
      lineWidth: overlay.id?.includes("vwap") ? 2 : 1,
      title: overlay.label,
      priceLineVisible: false,
      lastValueVisible: overlay.id?.includes("vwap") ?? false,
    });
    line.setData(segment);
    seriesList.push(line);
    segment = [];
  };

  for (const pt of values) {
    const bull = pt.bull ?? true;
    const color = pt.color ?? (bull ? bullColor : bearColor);
    if (segmentBull !== null && bull !== segmentBull) {
      segment.push({ time: chartTime(pt.t), value: pt.v });
      flush();
      segment = [{ time: chartTime(pt.t), value: pt.v }];
      segmentBull = bull;
    } else {
      segment.push({ time: chartTime(pt.t), value: pt.v });
      segmentBull = bull;
    }
    void color;
  }
  flush();
  return seriesList;
}

function barDurationMs(candles: { t: number }[]): number {
  if (candles.length < 2) return 300_000;
  return candles[candles.length - 1].t - candles[candles.length - 2].t;
}

function decisionTimeMs(candles: { t: number }[], snapshotAt?: number): number {
  return snapshotAt ?? candles[candles.length - 1]?.t ?? 0;
}

type TradeLevel = {
  price: number;
  color: string;
  title: string;
  dashed?: boolean;
  width?: number;
};

function tradeLevelsFromSetup(setup: TradeSetup): TradeLevel[] {
  const levels: TradeLevel[] = [
    {
      price: setup.entry,
      color: "#3b82f6",
      title: `ENTRY: ${formatPrice(setup.entry)}`,
      width: 2,
    },
    {
      price: setup.stop_loss,
      color: "#ef4444",
      title: `SL: ${formatPrice(setup.stop_loss)}`,
      width: 2,
    },
  ];
  setup.take_profits.slice(0, SNIPER_TP_COUNT).forEach((tp, i) => {
    const hit = setup.tp_hits?.[i];
    levels.push({
      price: tp,
      color: hit ? "#40e0d0" : "#22c55e",
      title: `TP${i + 1}: ${formatPrice(tp)}${hit ? " 🔥" : ""}`,
      dashed: true,
      width: 2,
    });
  });
  return levels;
}

function addTradeSegmentLines(
  chart: IChartApi,
  chartTime: (ms: number) => UTCTimestamp,
  fromMs: number,
  toMs: number,
  levels: TradeLevel[],
) {
  const fromTime = chartTime(fromMs);
  let toTime = chartTime(toMs);
  if (toTime <= fromTime) {
    toTime = (fromTime + 1) as UTCTimestamp;
  }

  for (const lvl of levels) {
    const series = chart.addLineSeries({
      color: lvl.color,
      lineWidth: (lvl.width ?? 2) as 1 | 2 | 3 | 4,
      lineStyle: lvl.dashed ? LineStyle.Dashed : LineStyle.Solid,
      title: lvl.title,
      priceLineVisible: false,
      lastValueVisible: true,
    });
    series.setData([
      { time: fromTime, value: lvl.price },
      { time: toTime, value: lvl.price },
    ]);
  }
}

function addFullWidthPriceLines(
  candleSeries: ISeriesApi<"Candlestick">,
  lines: PinePriceLine[],
) {
  for (const pl of lines) {
    candleSeries.createPriceLine({
      price: pl.price,
      color: pl.color,
      lineWidth: (pl.width ?? 1) as 1 | 2 | 3 | 4,
      lineStyle: pl.dashed ? LineStyle.Dashed : LineStyle.Solid,
      axisLabelVisible: true,
      title: pl.title,
    });
  }
}

function tradeLevelsFromPriceLines(lines: PinePriceLine[]): TradeLevel[] {
  return lines
    .filter((pl) => pl.from_t != null && isSniperTradeLabel(pl.title))
    .map((pl) => ({
      price: pl.price,
      color: pl.color,
      title: pl.title,
      dashed: pl.dashed,
      width: pl.width,
    }));
}

export function TradingViewChart({ snapshot, height = 400, utcOffsetHours = 0 }: Props) {
  const mainRef = useRef<HTMLDivElement>(null);
  const histRef = useRef<HTMLDivElement>(null);
  const { pine, loading, error } = usePineSnapshot(snapshot);

  const candles = snapshot.candles ?? [];
  const histPanel = snapshot.panels?.find((p) => p.type === "histogram");

  const render = useMemo(
    () => mergeSnapshotWithPine(snapshot, pine, loading),
    [pine, snapshot, loading],
  );

  const chartTime = (ms: number) => toChartTime(ms, utcOffsetHours) as UTCTimestamp;

  useEffect(() => {
    if (!mainRef.current || !candles.length) return;

    const chart = createChart(mainRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#0b0f19" },
        textColor: "#94a3b8",
      },
      grid: {
        vertLines: { color: "#1e293b" },
        horzLines: { color: "#1e293b" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#334155" },
      timeScale: { borderColor: "#334155", timeVisible: true, secondsVisible: false, rightOffset: 20 },
      width: mainRef.current.clientWidth,
      height,
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });

    candleSeries.setData(
      candles.map((c) => ({
        time: chartTime(c.t),
        open: c.o,
        high: c.h,
        low: c.l,
        close: c.c,
      })),
    );

    if (render.markers.length) {
      const markers: SeriesMarker<Time>[] = render.markers.map((m) => {
        if (m.shape === "decision") {
          return {
            time: chartTime(m.t),
            position: "aboveBar",
            color: "#facc15",
            shape: "circle",
            text: m.text ?? "DECISÃO",
          };
        }
        return {
          time: chartTime(m.t),
          position: m.shape === "buy" ? "belowBar" : "aboveBar",
          color: m.shape === "buy" ? "#22c55e" : "#ef4444",
          shape: m.shape === "buy" ? "arrowUp" : "arrowDown",
          text: m.text ?? (m.shape === "buy" ? "BUY" : "SELL"),
        };
      });
      candleSeries.setMarkers(markers);
    }

    for (const overlay of render.overlays) {
      if (overlay.type === "ema_ribbon") {
        addEmaRibbonSeries(chart, overlay, chartTime);
      }
      if (overlay.type === "trend_line" || overlay.type === "line") {
        addTrendLineSeries(chart, overlay, chartTime);
      }
      if (overlay.type === "breakout_levels" && overlay.levels?.length) {
        for (const lvl of overlay.levels) {
          const step = lvl.step_index != null && lvl.step_index > 0 ? ` L${lvl.step_index + 1}` : "";
          candleSeries.createPriceLine({
            price: lvl.price,
            color: lvl.color ?? (lvl.side === "high" ? "#22c55e" : "#ef4444"),
            lineWidth: lvl.step_index === 0 ? 2 : 1,
            lineStyle: LineStyle.Solid,
            axisLabelVisible: true,
            title: `${lvl.side === "high" ? "High" : "Low"}${step} ${lvl.prob_pct?.toFixed(1) ?? "?"}%`,
          });
        }
      }
    }

    const decisionT = decisionTimeMs(candles, snapshot.meta?.snapshot_at);
    const segmentEnd = decisionT + barDurationMs(candles) * 20;

    const tradeLevels = render.trade_setup
      ? tradeLevelsFromSetup(render.trade_setup)
      : tradeLevelsFromPriceLines(render.price_lines);

    if (tradeLevels.length) {
      addTradeSegmentLines(chart, chartTime, decisionT, segmentEnd, tradeLevels);
    }

    addFullWidthPriceLines(
      candleSeries,
      render.price_lines.filter((pl) => pl.from_t == null),
    );

    chart.timeScale().fitContent();

    let histChart: IChartApi | null = null;
    if (histRef.current && histPanel?.values?.length) {
      histChart = createChart(histRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: "#0b0f19" },
          textColor: "#64748b",
        },
        grid: { vertLines: { visible: false }, horzLines: { color: "#1e293b" } },
        rightPriceScale: { borderColor: "#334155" },
        timeScale: { borderColor: "#334155", visible: false },
        width: histRef.current.clientWidth,
        height: 100,
      });
      const hist = histChart.addHistogramSeries({
        priceFormat: { type: "volume" },
        priceLineVisible: false,
        lastValueVisible: false,
      });
      hist.setData(
        histPanel.values.map((v) => ({
          time: chartTime(v.t),
          value: v.v,
          color: v.color ?? (v.v >= 0 ? "#82ffc3" : "#f78c8c"),
        })),
      );
      histChart.timeScale().fitContent();
    }

    const onResize = () => {
      if (mainRef.current) chart.applyOptions({ width: mainRef.current.clientWidth });
      if (histRef.current && histChart) {
        histChart.applyOptions({ width: histRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
      histChart?.remove();
    };
  }, [snapshot, render, height, candles.length, histPanel, utcOffsetHours]);

  if (!candles.length) {
    return (
      <div className="flex h-32 items-center justify-center rounded-lg bg-black/20 text-xs text-slate-500">
        Sem snapshot de gráfico
      </div>
    );
  }

  const mergedSnapshot: ChartSnapshot = {
    ...snapshot,
    sniper_panel: render.sniper_panel,
    breakout: render.breakout,
    markers: render.markers,
    trade_setup: render.trade_setup,
  };

  return (
    <div className="space-y-3">
      <IndicatorLegend snapshot={mergedSnapshot} />
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span>
          Foto congelada · {snapshot.timeframe ?? "5m"} · {candles.length} candles ·{" "}
          {utcOffsetLabel(utcOffsetHours)}
        </span>
        {loading && <span className="text-amber-400">Traduzindo Pine…</span>}
        {render.usePine && !loading && (
          <span className="rounded bg-violet-500/20 px-1.5 py-0.5 text-violet-300">PineTS</span>
        )}
        {error && !render.usePine && (
          <span className="text-amber-500" title={error}>
            fallback Python
          </span>
        )}
      </div>
      <div className="relative w-full overflow-hidden rounded-lg">
        {render.sniper_panel && <SniperDashboard panel={render.sniper_panel} />}
        <div ref={mainRef} className="w-full" style={{ minHeight: loading ? height : undefined }} />
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/40 text-sm text-slate-300">
            Rodando indicadores Pine no snapshot…
          </div>
        )}
      </div>
      {histPanel?.values?.length ? (
        <div>
          <div className="mb-1 text-xs text-slate-500">{histPanel.label ?? "Histogram"}</div>
          <div ref={histRef} className="w-full overflow-hidden rounded-lg" />
        </div>
      ) : null}
    </div>
  );
}
