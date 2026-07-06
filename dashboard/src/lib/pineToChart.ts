import { SNIPER_TP_COUNT } from "@/lib/pineCompat";
import type {
  ChartCandle,
  ChartMarker,
  ChartOverlay,
  ChartSnapshot,
  SniperPanel,
  SniperPanelRow,
  TradeSetup,
} from "@/types/chart";

export type PinePlotPoint = {
  time: number;
  value: number | boolean | null;
  title?: string;
  options?: {
    color?: string;
    text?: string;
    textcolor?: string;
    shape?: string;
    location?: string;
  };
};

type PineTableCell = {
  text?: string;
  text_color?: string;
  bgcolor?: string;
};

type PineLine = {
  y1: number;
  y2: number;
  color?: string;
  style?: string;
  extend?: string;
};

type PineLabel = {
  y: number;
  text?: string;
  color?: string;
};

export type PinePriceLine = {
  price: number;
  color: string;
  title: string;
  dashed?: boolean;
  width?: number;
  from_t?: number;
};

export function isSniperTradeLabel(title: string): boolean {
  return /^(ENTRY:|SL:|TP[1-3]:)/i.test(title);
}

function formatTradePrice(p: number): string {
  if (p >= 100) return p.toFixed(2);
  if (p >= 1) return p.toFixed(3);
  if (p >= 0.01) return p.toFixed(4);
  return p.toFixed(6);
}

function priceNear(a: number, b: number): boolean {
  if (a === b) return true;
  const scale = Math.max(Math.abs(a), Math.abs(b), 1e-12);
  return Math.abs(a - b) <= scale * 1e-6;
}

function labelPrefix(text: string): string | null {
  const m = text.match(/^(ENTRY:|SL:|TP[1-3]:)/i);
  return m ? m[1].toUpperCase() : null;
}

function buildLabelMaps(labels: PineLabel[] | undefined) {
  const byPrice = new Map<number, string>();
  const byPrefix = new Map<string, PineLabel>();
  for (const lb of labels ?? []) {
    if (!lb.text || lb.y == null || Number.isNaN(lb.y)) continue;
    byPrice.set(lb.y, lb.text);
    const prefix = labelPrefix(lb.text);
    if (prefix) byPrefix.set(prefix, lb);
  }
  return { byPrice, byPrefix };
}

function resolveLineTitle(
  line: PineLine,
  maps: ReturnType<typeof buildLabelMaps>,
  tpDashedIndex: number,
): string {
  const price = line.y1;
  let title = maps.byPrice.get(price) ?? "";
  if (!title) {
    for (const [y, text] of maps.byPrice) {
      if (priceNear(y, price)) {
        title = text;
        break;
      }
    }
  }

  const isTpDashed = line.style?.includes("dashed") ?? false;
  if (!title && isTpDashed && tpDashedIndex > 0) {
    const lb = maps.byPrefix.get(`TP${tpDashedIndex}:`);
    title = lb?.text ?? `TP${tpDashedIndex}: ${formatTradePrice(price)}`;
  }

  const isSl =
    /^SL:/i.test(title) ||
    (line.style === "style_solid" &&
      !/^ENTRY:/i.test(title) &&
      (line.color?.toUpperCase().includes("F23645") ||
        line.color?.toLowerCase().includes("ef4444") ||
        line.color?.toLowerCase().includes("red")));
  if (isSl && !title) title = `SL: ${formatTradePrice(price)}`;

  if (!title && /^#2196F3$/i.test(line.color ?? "") && line.style === "style_solid") {
    title = maps.byPrefix.get("ENTRY:")?.text ?? `ENTRY: ${formatTradePrice(price)}`;
  }

  if (/^TP[1-3]:/i.test(title)) {
    const n = title.match(/^TP([1-3]):/i)?.[1];
    const hit = title.includes("🔥");
    title = `TP${n}: ${formatTradePrice(price)}${hit ? " 🔥" : ""}`;
  } else if (/^ENTRY:/i.test(title)) {
    title = `ENTRY: ${formatTradePrice(price)}`;
  } else if (/^SL:/i.test(title)) {
    title = `SL: ${formatTradePrice(price)}`;
  }

  return title;
}

function isSniperTpLine(line: PineLine): boolean {
  if (!line.style?.includes("dashed")) return false;
  const c = (line.color ?? "").toLowerCase();
  return c.includes("4caf50") || c.includes("22c55e") || c.includes("green") || c.includes("40e0d0");
}

function decisionTimeMs(candles: ChartCandle[]): number {
  return candles[candles.length - 1]?.t ?? 0;
}

export type PineRenderData = {
  overlays: ChartOverlay[];
  markers: ChartMarker[];
  sniper_panel?: SniperPanel;
  trade_setup?: TradeSetup;
  price_lines: PinePriceLine[];
  breakout?: ChartSnapshot["breakout"];
  source: "pinets";
};

function bullFromPlotColor(color?: string): boolean {
  if (!color) return true;
  const c = color.toLowerCase();
  if (c.includes("f23645") || c.includes("ef4444") || c.includes("red")) return false;
  return true;
}

function extractTableCells(tables: PinePlotPoint[] | undefined): PineTableCell[][] | undefined {
  const raw = tables?.[0]?.value;
  if (!raw) return undefined;
  if (Array.isArray(raw)) {
    const first = raw[0] as { cells?: PineTableCell[][] } | undefined;
    return first?.cells;
  }
  return (raw as { cells?: PineTableCell[][] }).cells;
}

const SNIPER_LINE_IDS = new Set(["sniper_ema9", "sniper_ema21", "sniper_vwap"]);

function isUsableSniperPanel(panel: SniperPanel | undefined): panel is SniperPanel {
  if (!panel) return false;
  return panel.bull_pct > 0 || panel.bear_pct > 0 || panel.rows.length > 0;
}

function mergeOverlays(snapshot: ChartOverlay[], pine: ChartOverlay[]): ChartOverlay[] {
  if (!pine.length) return snapshot;
  const pineLabels = new Set(pine.map((o) => o.label).filter(Boolean));
  const kept = snapshot.filter((o) => {
    if (o.type === "ema_ribbon") return true;
    if (!SNIPER_LINE_IDS.has(o.id)) return true;
    // Mantém linha Python se PineTS não gerou equivalente (ex.: VWAP vazio)
    return Boolean(o.label && !pineLabels.has(o.label));
  });
  return [...kept, ...pine];
}

function mergeMarkers(pine: ChartMarker[] = [], snap: ChartMarker[] = []): ChartMarker[] {
  const pineTrades = pine.filter((m) => m.shape === "buy" || m.shape === "sell");
  const snapTrades = snap.filter((m) => m.shape === "buy" || m.shape === "sell");
  const trades = pineTrades.length ? pineTrades : snapTrades;
  const decision = pine.find((m) => m.shape === "decision") ?? snap.find((m) => m.shape === "decision");
  return decision ? [...trades, decision] : trades.length ? trades : snap;
}

function sliceTradeSetup(setup: TradeSetup): TradeSetup {
  return {
    ...setup,
    take_profits: setup.take_profits.slice(0, SNIPER_TP_COUNT),
    tp_hits: setup.tp_hits?.slice(0, SNIPER_TP_COUNT),
  };
}

type BotDecisionLevels = {
  entry: number;
  stop_loss: number;
  take_profits: number[];
};

function botLevelsFromSnapshot(snapshot: ChartSnapshot): BotDecisionLevels | undefined {
  const raw = snapshot.levels;
  if (!raw) return undefined;

  const entry = raw.entry;
  const stopLoss = raw.stop_loss;
  const tps = raw.take_profits;

  if (typeof entry !== "number" || typeof stopLoss !== "number" || !Array.isArray(tps) || !tps.length) {
    return undefined;
  }

  const take_profits = tps
    .filter((p): p is number => typeof p === "number" && !Number.isNaN(p))
    .slice(0, SNIPER_TP_COUNT);

  if (!take_profits.length) return undefined;

  return { entry, stop_loss: stopLoss, take_profits };
}

function applyBotLevelsToSetup(setup: TradeSetup, bot: BotDecisionLevels): TradeSetup {
  const direction: TradeSetup["direction"] =
    bot.stop_loss < bot.entry ? "LONG" : bot.stop_loss > bot.entry ? "SHORT" : setup.direction;

  const tp_hits = setup.tp_hits?.slice(0, bot.take_profits.length);
  while (tp_hits && tp_hits.length < bot.take_profits.length) {
    tp_hits.push(false);
  }

  return {
    ...setup,
    direction,
    entry: bot.entry,
    stop_loss: bot.stop_loss,
    take_profits: bot.take_profits,
    tp_hits: tp_hits?.length ? tp_hits : setup.tp_hits,
  };
}

function setupFromBotLevels(snapshot: ChartSnapshot, bot: BotDecisionLevels): TradeSetup {
  const signal_t = snapshot.meta?.snapshot_at ?? snapshot.candles?.[snapshot.candles.length - 1]?.t ?? 0;
  const direction: TradeSetup["direction"] = bot.stop_loss < bot.entry ? "LONG" : "SHORT";
  return {
    direction,
    signal_t,
    entry: bot.entry,
    stop_loss: bot.stop_loss,
    take_profits: bot.take_profits,
    tp_hits: bot.take_profits.map(() => false),
  };
}

function finalizeTradeSetup(
  snapshot: ChartSnapshot,
  setup: TradeSetup | undefined,
): TradeSetup | undefined {
  const bot = botLevelsFromSnapshot(snapshot);
  if (!bot) return setup ? sliceTradeSetup(setup) : undefined;
  const base = setup ?? setupFromBotLevels(snapshot, bot);
  return sliceTradeSetup(applyBotLevelsToSetup(base, bot));
}

function applyBotLevelsToPriceLines(lines: PinePriceLine[], bot: BotDecisionLevels): PinePriceLine[] {
  return lines.map((pl) => {
    const prefix = labelPrefix(pl.title);
    if (!prefix) return pl;

    if (prefix.startsWith("ENTRY")) {
      return { ...pl, price: bot.entry, title: `ENTRY: ${formatTradePrice(bot.entry)}` };
    }
    if (prefix.startsWith("SL")) {
      return { ...pl, price: bot.stop_loss, title: `SL: ${formatTradePrice(bot.stop_loss)}` };
    }

    const tpIdx = parseInt(prefix.charAt(2), 10) - 1;
    if (tpIdx >= 0 && tpIdx < bot.take_profits.length) {
      const price = bot.take_profits[tpIdx];
      const hit = pl.title.includes("🔥");
      return {
        ...pl,
        price,
        title: `TP${tpIdx + 1}: ${formatTradePrice(price)}${hit ? " 🔥" : ""}`,
      };
    }
    return pl;
  });
}

export type ChartRenderData = {
  usePine: boolean;
  overlays: ChartOverlay[];
  markers: ChartMarker[];
  sniper_panel?: SniperPanel;
  trade_setup?: TradeSetup;
  price_lines: PinePriceLine[];
  breakout?: ChartSnapshot["breakout"];
};

export function mergeSnapshotWithPine(
  snapshot: ChartSnapshot,
  pine: PineRenderData | null,
  loading: boolean,
): ChartRenderData {
  const snapOverlays = snapshot.overlays ?? [];
  const snapMarkers = snapshot.markers ?? [];
  const bot = botLevelsFromSnapshot(snapshot);

  const baseSetup = pine?.trade_setup ?? snapshot.trade_setup;
  const trade_setup = finalizeTradeSetup(snapshot, baseSetup);

  if (!pine || loading) {
    return {
      usePine: false,
      overlays: snapOverlays,
      markers: snapMarkers,
      sniper_panel: snapshot.sniper_panel,
      trade_setup,
      price_lines: [],
      breakout: snapshot.breakout,
    };
  }

  const price_lines = bot
    ? applyBotLevelsToPriceLines(pine.price_lines ?? [], bot)
    : (pine.price_lines ?? []);

  return {
    usePine: true,
    overlays: mergeOverlays(snapOverlays, pine.overlays ?? []),
    markers: mergeMarkers(pine.markers ?? [], snapMarkers),
    sniper_panel: isUsableSniperPanel(pine.sniper_panel)
      ? pine.sniper_panel
      : snapshot.sniper_panel,
    trade_setup,
    price_lines,
    breakout: { ...snapshot.breakout, ...pine.breakout },
  };
}

function plotSeriesToLine(
  id: string,
  label: string,
  data: PinePlotPoint[] | undefined,
  defaultColor: string,
): ChartOverlay | null {
  if (!data?.length) return null;
  const values = data
    .filter((p) => typeof p.value === "number" && !Number.isNaN(p.value))
    .map((p) => ({
      t: p.time,
      v: p.value as number,
      bull: bullFromPlotColor(p.options?.color),
      color: p.options?.color ?? defaultColor,
    }));
  if (!values.length) return null;
  return {
    id,
    type: "trend_line",
    label,
    values,
    color_bull: defaultColor,
    color_bear: defaultColor,
  };
}

function parseSniperTable(tables: PinePlotPoint[] | undefined): SniperPanel | undefined {
  const cells = extractTableCells(tables);
  if (!cells?.length) return undefined;

  const rows: SniperPanelRow[] = [];
  let bull_pct = 0;
  let bear_pct = 0;
  let bias = "NEUTRAL";

  for (let r = 0; r < cells.length; r++) {
    const left = cells[r]?.[0]?.text ?? "";
    const right = cells[r]?.[1]?.text ?? "";
    if (r === 0 && left === "BULL SCORE") bull_pct = parseFloat(right) || 0;
    if (r === 1 && left === "BEAR SCORE") bear_pct = parseFloat(right) || 0;
    if (r === 2 && left === "MARKET BIAS") bias = right;
    if (r >= 3 && left) {
      const tone =
        right.includes("BULL") || right === "ABOVE" || right === "HIGH" || right === "STRONG"
          ? "bull"
          : right.includes("BEAR") || right === "BELOW" || right === "WEAK"
            ? "bear"
            : "neutral";
      rows.push({ label: left, value: right, tone });
    }
  }

  return { bull_pct, bear_pct, bias, rows };
}

function parseBreakoutTable(tables: PinePlotPoint[] | undefined): ChartSnapshot["breakout"] | undefined {
  const cells = extractTableCells(tables);
  if (!cells?.length) return undefined;
  const texts = cells.map((row) => row[0]?.text ?? "");
  const wins = parseInt((texts[0]?.match(/\d+/) ?? ["0"])[0], 10);
  const losses = parseInt((texts[1]?.match(/\d+/) ?? ["0"])[0], 10);
  const wrMatch = texts[2]?.match(/[\d.]+/);
  const win_rate_pct = wrMatch ? parseFloat(wrMatch[0]) : 0;
  return {
    backtest: { wins, losses, win_rate_pct },
  };
}

function parsePlotMarkers(plot: PinePlotPoint[] | undefined, candles: ChartCandle[]): ChartMarker[] {
  if (!plot?.length) return [];
  const markers: ChartMarker[] = [];
  const timeSet = new Set(candles.map((c) => c.t));

  for (const p of plot) {
    if (p.value !== true) continue;
    const text = p.options?.text;
    if (text !== "BUY" && text !== "SELL") continue;
    const t = timeSet.has(p.time) ? p.time : candles.find((c) => Math.abs(c.t - p.time) < 60_000)?.t;
    if (!t) continue;
    markers.push({
      t,
      shape: text === "BUY" ? "buy" : "sell",
      text,
    });
  }
  return markers;
}

function parseTradeFromDrawings(
  labels: PineLabel[] | undefined,
  lines: PineLine[] | undefined,
  candles: ChartCandle[],
): TradeSetup | undefined {
  const entryLabel = labels?.find((l) => l.text?.startsWith("ENTRY:"));
  if (!entryLabel?.text) return undefined;

  const entryFromY = entryLabel.y;
  const entryFromText = parseFloat(entryLabel.text.replace("ENTRY:", "").trim());
  const entry =
    entryFromY != null && !Number.isNaN(entryFromY) ? entryFromY : entryFromText;
  if (Number.isNaN(entry)) return undefined;

  const tps: number[] = [];
  const tpHits: boolean[] = [];
  for (let i = 1; i <= SNIPER_TP_COUNT; i++) {
    const lb = labels?.find((l) => l.text?.startsWith(`TP${i}:`));
    if (!lb?.text) continue;
    const fromY = lb.y;
    const fromText = parseFloat(lb.text.replace(`TP${i}:`, "").replace("🔥", "").trim());
    const price = fromY != null && !Number.isNaN(fromY) ? fromY : fromText;
    if (!Number.isNaN(price)) {
      tps.push(price);
      tpHits.push(lb.text.includes("🔥"));
    }
  }

  const slLine = lines?.find((l) => l.color?.toUpperCase().includes("F23645") || l.style === "style_solid");
  const slCandidates = lines?.filter((l) => l.style === "style_solid") ?? [];
  const sl =
    slCandidates.find((l) => Math.abs(l.y1 - entry) > 0.0001 && l.color?.includes("F23645"))?.y1 ??
    slLine?.y1;

  const lastT = candles[candles.length - 1]?.t ?? 0;
  const direction: "LONG" | "SHORT" =
    sl != null && sl < entry ? "LONG" : sl != null && sl > entry ? "SHORT" : "LONG";

  return {
    direction,
    signal_t: lastT,
    entry,
    stop_loss: sl ?? entry,
    take_profits: tps,
    tp_hits: tpHits,
  };
}

function parseHorizontalLines(
  lines: PineLine[] | undefined,
  labels: PineLabel[] | undefined,
  candles: ChartCandle[] = [],
  options?: { tradeOnly?: boolean },
): PinePriceLine[] {
  if (!lines?.length) return [];
  const out: PinePriceLine[] = [];
  const labelMaps = buildLabelMaps(labels);

  const tradeOnly = options?.tradeOnly ?? false;
  const fromT = decisionTimeMs(candles);
  let tpDashedIndex = 0;

  for (const line of lines) {
    const price = line.y1;
    if (line.style?.includes("dashed") && isSniperTpLine(line)) tpDashedIndex += 1;

    let title = resolveLineTitle(line, labelMaps, tpDashedIndex);
    const isSl =
      /^SL:/i.test(title) ||
      (line.style === "style_solid" &&
        !/^ENTRY:/i.test(title) &&
        (line.color?.toUpperCase().includes("F23645") ||
          line.color?.toLowerCase().includes("ef4444") ||
          line.color?.toLowerCase().includes("red")));

    if (tradeOnly && !isSniperTradeLabel(title) && !isSl && !isSniperTpLine(line)) continue;
    if (/^TP[4-9]:/i.test(title)) continue;
    if (!title) title = `Level ${formatTradePrice(price)}`;
    const dashed = line.style?.includes("dashed") ?? false;
    out.push({
      price,
      color: line.color ?? "#94a3b8",
      title,
      dashed,
      width: dashed ? 2 : 2,
      from_t: tradeOnly ? fromT : undefined,
    });
  }
  return out;
}

function parseBreakoutLevels(
  lines: PineLine[] | undefined,
  labels: PineLabel[] | undefined,
): ChartOverlay | null {
  if (!lines?.length) return null;
  const levels = lines.map((line, i) => {
    const lb = labels?.[i];
    const pctMatch = lb?.text?.match(/[\d.]+/);
    const side = line.y1 > (lines[0]?.y1 ?? 0) ? "high" : "low";
    return {
      price: line.y1,
      prob_pct: pctMatch ? parseFloat(pctMatch[0]) : undefined,
      side: side as "high" | "low",
      color: line.color ?? (side === "high" ? "#22c55e" : "#ef4444"),
      step_index: i,
    };
  });
  return {
    id: "breakout_levels_pinets",
    type: "breakout_levels",
    label: "Breakout Probability",
    levels,
  };
}

function extractDrawings(plots: Record<string, { data?: PinePlotPoint[] }>) {
  const labelsBlock = plots.__labels__?.data?.[0]?.value as PineLabel[] | undefined;
  const linesBlock = plots.__lines__?.data?.[0]?.value as PineLine[] | undefined;
  return { labelsBlock, linesBlock };
}

export function sniperPlotsToChart(
  plots: Record<string, { data?: PinePlotPoint[] }>,
  candles: ChartCandle[],
): Partial<PineRenderData> {
  const overlays: ChartOverlay[] = [];
  const ema9 = plotSeriesToLine("pinets_ema9", "EMA 9", plots["EMA 9"]?.data, "#22c55e");
  const ema21 = plotSeriesToLine("pinets_ema21", "EMA 21", plots["EMA 21"]?.data, "#ef4444");
  const vwap = plotSeriesToLine("pinets_vwap", "VWAP", plots.VWAP?.data, "#22c55e");
  if (ema9) overlays.push(ema9);
  if (ema21) overlays.push(ema21);
  if (vwap) overlays.push(vwap);

  const { labelsBlock, linesBlock } = extractDrawings(plots);
  const sniper_panel = parseSniperTable(plots.__tables__?.data);
  const markers = parsePlotMarkers(plots.plot?.data, candles);
  const trade_setup = parseTradeFromDrawings(labelsBlock, linesBlock, candles);
  const price_lines = parseHorizontalLines(linesBlock, labelsBlock, candles, { tradeOnly: true });

  if (candles.length) {
    markers.push({ t: candles[candles.length - 1].t, shape: "decision", text: "DECISÃO" });
  }

  return { overlays, markers, sniper_panel, trade_setup, price_lines };
}

export function breakoutPlotsToChart(
  plots: Record<string, { data?: PinePlotPoint[] }>,
): Partial<PineRenderData> {
  const { labelsBlock, linesBlock } = extractDrawings(plots);
  const overlay = parseBreakoutLevels(linesBlock, labelsBlock);
  const breakout = parseBreakoutTable(plots.__tables__?.data);
  const overlays = overlay ? [overlay] : [];
  const price_lines = parseHorizontalLines(linesBlock, labelsBlock);
  return { overlays, breakout, price_lines };
}

export function mergePineRender(parts: Partial<PineRenderData>[]): PineRenderData {
  const merged: PineRenderData = {
    overlays: [],
    markers: [],
    price_lines: [],
    source: "pinets",
  };
  for (const p of parts) {
    if (p.overlays) merged.overlays.push(...p.overlays);
    if (p.markers) merged.markers.push(...p.markers);
    if (p.price_lines) merged.price_lines.push(...p.price_lines);
    if (p.sniper_panel) merged.sniper_panel = p.sniper_panel;
    if (p.trade_setup) merged.trade_setup = p.trade_setup;
    if (p.breakout) merged.breakout = { ...merged.breakout, ...p.breakout };
  }
  return merged;
}

export function candlesToPineInput(candles: ChartCandle[]) {
  return candles.map((c) => ({
    open: c.o,
    high: c.h,
    low: c.l,
    close: c.c,
    volume: c.v ?? 0,
    openTime: c.t,
  }));
}
