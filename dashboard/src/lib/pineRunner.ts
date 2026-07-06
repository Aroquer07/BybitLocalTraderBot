import { PineTS } from "pinets";

import { pineFilesForSnapshot, preprocessSniperPine } from "@/lib/pineCompat";
import {
  breakoutPlotsToChart,
  candlesToPineInput,
  mergePineRender,
  sniperPlotsToChart,
  type PineRenderData,
} from "@/lib/pineToChart";
import type { ChartSnapshot } from "@/types/chart";

const pineSourceCache = new Map<string, string>();
const renderCache = new Map<string, PineRenderData>();

function cacheKey(snapshot: ChartSnapshot): string {
  const candles = snapshot.candles ?? [];
  const last = candles[candles.length - 1]?.t ?? 0;
  return `${snapshot.meta?.entry_strategy ?? "sniper"}:${candles.length}:${last}`;
}

async function fetchPineSource(name: string): Promise<string> {
  const cached = pineSourceCache.get(name);
  if (cached) return cached;
  const res = await fetch(`/api/indicators/pine/${encodeURIComponent(name)}`);
  if (!res.ok) throw new Error(`Pine não encontrado: ${name}`);
  const text = await res.text();
  pineSourceCache.set(name, text);
  return text;
}

function prepareSource(name: string, source: string): string {
  if (name === "sniper entry") return preprocessSniperPine(source);
  return source;
}

export async function runPineOnSnapshot(snapshot: ChartSnapshot): Promise<PineRenderData | null> {
  const candles = snapshot.candles ?? [];
  if (candles.length < 30) return null;

  const key = cacheKey(snapshot);
  const hit = renderCache.get(key);
  if (hit) return hit;

  const files = pineFilesForSnapshot(
    snapshot.meta?.entry_strategy,
    snapshot.meta?.active_indicators,
  );

  const parts: Partial<PineRenderData>[] = [];
  const pineInput = candlesToPineInput(candles);
  const pineTS = new PineTS(pineInput);

  for (const file of files) {
    try {
      const raw = await fetchPineSource(file);
      const source = prepareSource(file, raw);
      const result = await pineTS.run(source);
      const plots = result.plots as Record<string, { data?: import("@/lib/pineToChart").PinePlotPoint[] }>;

      if (file === "sniper entry") {
        parts.push(sniperPlotsToChart(plots, candles));
      } else if (file === "breakout Probability") {
        parts.push(breakoutPlotsToChart(plots));
      }
    } catch (err) {
      console.warn(`PineTS falhou em ${file}:`, err);
    }
  }

  if (!parts.length) return null;
  const merged = mergePineRender(parts);
  renderCache.set(key, merged);
  return merged;
}
