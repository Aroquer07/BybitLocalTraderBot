import type { StrategyRank } from "@/lib/strategyPattern";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    let detail = text || `Request failed: ${res.status}`;
    try {
      const parsed = JSON.parse(text) as { detail?: string };
      if (parsed.detail) detail = parsed.detail;
    } catch {
      /* plain text */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export type AuthMe = {
  email: string | null;
  admin_email: string | null;
  admin_configured: boolean;
  is_admin: boolean;
  ngrok_auth: boolean;
  created_at?: string | null;
};

export type BotStatus = {
  running: boolean;
  pid: number | null;
  bybit_mode: string;
  scanner_enabled: boolean;
  entry_strategy: string;
  scanner_mode: string;
  learning_enabled: boolean;
  open_positions: number;
  journal_stats: Record<string, number>;
  activity: string;
  ngrok_url?: string | null;
};

export type Trade = {
  id: string;
  symbol: string;
  direction: string;
  source: string;
  status: string;
  entry_price: number;
  exit_price?: number | null;
  amount?: number | null;
  pnl_pct?: number | null;
  pnl_usd?: number | null;
  confidence: number;
  leverage: number;
  opened_at: string;
  closed_at?: string | null;
  notes?: string;
};

export type AccountInfo = {
  mode: string;
  market_type: string;
  available: boolean;
  balance_usdt: number | null;
  total_usdt: number | null;
  used_usdt: number | null;
  error: string | null;
};

export type ChartPayload = {
  equity_curve: {
    time: string;
    symbol: string;
    pnl_usd: number;
    cumulative_pnl_usd: number;
  }[];
  pnl_by_source: { source: string; pnl_pct: number; pnl_usd: number }[];
  top_symbols: { symbol: string; pnl_pct: number; pnl_usd: number }[];
};

export type ExchangePnlPayload = {
  period: string;
  available: boolean;
  fills: Record<string, number>;
  position_groups: Record<string, number | null>;
  group_rows?: Record<string, unknown>[];
  error: string | null;
};

export type LearningPayload = {
  report: {
    total_closed: number;
    with_features: number;
    best_patterns: { pattern: string; winrate_pct: number; sample_n: number; avg_pnl_pct: number }[];
    worst_patterns: { pattern: string; winrate_pct: number; sample_n: number; avg_pnl_pct: number }[];
    calibration: { predicted_range: string; actual_winrate_pct: number; sample_n: number }[];
    recommendations: string[];
  };
  learning_config: Record<string, unknown>;
  strategies: Record<string, unknown>;
  rejections_recent: Record<string, unknown>[];
  rejections_total: number;
};

export type Rejection = {
  id?: string;
  symbol?: string;
  direction?: string;
  source?: string;
  stage?: string;
  reason?: string;
  rejected_at?: string;
  confidence?: number;
  predicted_probability?: number;
  chart_snapshot?: import("@/types/chart").ChartSnapshot;
  probability_features?: Record<string, unknown>;
};

export type Approval = {
  id?: string;
  symbol?: string;
  direction?: string;
  source?: string;
  strategy?: string;
  summary?: string;
  approved_at?: string;
  confidence?: number;
  predicted_probability?: number;
  chart_snapshot?: import("@/types/chart").ChartSnapshot;
  probability_features?: Record<string, unknown>;
};

export type AnalysisPayload = {
  rejections: Rejection[];
  approvals: Approval[];
  recent_signals: Record<string, unknown>[];
  log_tail: string[];
  utc_offset_hours?: number;
};

export type { StrategyRank };

export type BreakoutOutlook = {
  symbol: string;
  bias?: string;
  probability_pct?: number;
  prob_high_pct?: number;
  prob_low_pct?: number;
  prev_candle?: string;
  reason?: string;
  meets_threshold?: boolean;
  error?: string;
};

export type BreakoutPayload = {
  timeframe: string;
  min_probability_pct: number;
  outlooks: BreakoutOutlook[];
  error?: string | null;
  updated_at?: string;
};

export const api = {
  health: () => request<{ ok: boolean }>("/api/health"),
  authMe: () => request<AuthMe>("/api/auth/me"),
  status: () => request<BotStatus>("/api/status"),
  logs: (limit = 100) => request<{ lines: string[] }>(`/api/status/logs?limit=${limit}`),
  settings: () => request<Record<string, unknown>>("/api/settings"),
  saveSettings: (data: Record<string, unknown>) =>
    request<Record<string, unknown>>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  account: () => request<AccountInfo>("/api/account"),
  setAccountMode: (mode: string) =>
    request<{ mode: string; requires_restart: boolean; message: string }>("/api/account/mode", {
      method: "PUT",
      body: JSON.stringify({ mode }),
    }),
  watchlist: () => request<{ symbols: string[]; path: string }>("/api/watchlist"),
  breakoutOutlook: (limit = 25) =>
    request<BreakoutPayload>(`/api/watchlist/breakout?limit=${limit}`),
  saveWatchlist: (symbols: string[]) =>
    request<{ symbols: string[]; path: string }>("/api/watchlist", {
      method: "PUT",
      body: JSON.stringify({ symbols }),
    }),
  trades: () =>
    request<{ trades: Trade[]; stats: Record<string, number> }>("/api/trades"),
  strategyRanking: () =>
    request<{ ranking: StrategyRank[] }>("/api/trades/strategies/ranking"),
  charts: () => request<ChartPayload>("/api/trades/charts"),
  exchangePnl: (period = "week") =>
    request<ExchangePnlPayload>(`/api/trades/exchange-pnl?period=${period}`),
  learning: () => request<LearningPayload>("/api/learning"),
  analysis: () => request<AnalysisPayload>("/api/analysis"),
};
