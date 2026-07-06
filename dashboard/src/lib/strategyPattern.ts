export type ParsedPattern = {
  raw?: string;
  source?: string;
  direction?: string;
  imba?: string;
  conf?: string;
  kalman?: string;
  lev?: string;
  sl?: string;
  spread?: string;
  chart?: string;
};

export type StrategyRank = {
  strategy: string;
  kind: "pattern" | "pipeline" | "other";
  display_name: string;
  parsed: ParsedPattern;
  trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  total_pnl_pct: number;
  total_pnl_usd: number;
  avg_pnl_pct: number;
};

const LABELS: Record<string, string> = {
  source: "Fonte",
  direction: "Direção",
  imba: "IMBA",
  conf: "Confluência",
  kalman: "Kalman",
  lev: "Alavancagem",
  sl: "Stop loss",
  spread: "Spread",
  chart: "Padrão gráfico",
};

export function patternFieldLabel(key: string): string {
  return LABELS[key] ?? key;
}

export function directionBadgeClass(direction?: string): string {
  if (direction === "LONG") return "bg-emerald-500/15 text-emerald-300";
  if (direction === "SHORT") return "bg-rose-500/15 text-rose-300";
  return "bg-slate-700 text-slate-300";
}

export function stageLabel(stage: string): string {
  const map: Record<string, string> = {
    smc: "SMC",
    levels: "Níveis",
    filters: "Filtros",
    kalman: "Kalman",
    pattern: "Padrão",
    pwin: "P(win)",
    llm: "LLM",
    imba: "IMBA",
  };
  return map[stage] ?? stage;
}

export function accountModeLabel(mode: string): string {
  const map: Record<string, string> = {
    testnet: "Testnet",
    demo: "Demo",
    live: "Live",
  };
  return map[mode] ?? mode;
}
