export type ChartCandle = {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v?: number;
};

export type OverlayPoint = {
  t: number;
  v: number;
  bull?: boolean;
  color?: string;
  ema9?: number;
  ema21?: number;
};

export type ChartMarker = {
  t: number;
  shape: "buy" | "sell" | "decision";
  price?: number;
  text?: string;
};

export type SniperPanelRow = {
  label: string;
  value: string;
  tone?: "bull" | "bear" | "neutral" | "info";
};

export type SniperPanel = {
  bull_pct: number;
  bear_pct: number;
  bias: string;
  rows: SniperPanelRow[];
};

export type TradeSetup = {
  direction: "LONG" | "SHORT";
  signal_t: number;
  entry: number;
  stop_loss: number;
  take_profits: number[];
  tp_hits?: boolean[];
};

export type ChartOverlay = {
  id: string;
  type: "line" | "trend_line" | "box" | "breakout_levels" | "ema_ribbon";
  label?: string;
  color?: string;
  color_bull?: string;
  color_bear?: string;
  values?: OverlayPoint[];
  top?: number;
  bottom?: number;
  mid?: number;
  from_t?: number;
  to_t?: number;
  opacity?: number;
  levels?: {
    price: number;
    prob_pct?: number;
    side?: "high" | "low";
    color?: string;
    step_index?: number;
  }[];
  bias?: string;
};

export type ChartPanel = {
  id: string;
  type: "histogram";
  label?: string;
  values?: OverlayPoint[];
};

export type IndicatorModule = {
  name: string;
  display_name?: string;
  triggered: boolean;
  direction?: string | null;
  confidence?: number;
  reason?: string;
  regime?: string;
};

export type ChartSnapshot = {
  timeframe?: string;
  candles?: ChartCandle[];
  levels?: Record<string, number | number[]>;
  modules?: IndicatorModule[];
  overlays?: ChartOverlay[];
  panels?: ChartPanel[];
  breakout?: {
    bias?: string;
    probability_pct?: number;
    prob_high_pct?: number;
    prob_low_pct?: number;
    prev_candle?: string;
    reason?: string;
    backtest?: { wins: number; losses: number; win_rate_pct: number };
  };
  markers?: ChartMarker[];
  sniper_panel?: SniperPanel;
  trade_setup?: TradeSetup;
  meta?: {
    entry_strategy?: string;
    active_indicators?: string[];
    indicators_config?: Record<string, unknown>;
    snapshot_at?: number;
  };
};

export type AnalysisDecision = {
  id?: string;
  symbol?: string;
  direction?: string;
  source?: string;
  stage?: string;
  reason?: string;
  summary?: string;
  strategy?: string;
  rejected_at?: string;
  approved_at?: string;
  confidence?: number;
  predicted_probability?: number;
  chart_snapshot?: ChartSnapshot;
};
