const TF_TO_TV: Record<string, string> = {
  "1m": "1",
  "3m": "3",
  "5m": "5",
  "15m": "15",
  "30m": "30",
  "1h": "60",
  "2h": "120",
  "4h": "240",
  "1d": "D",
  "1w": "W",
};

/** PORTAL/USDT → BYBIT:PORTALUSDT.P (perp USDT na TV) */
export function toTradingViewSymbol(symbol: string): string {
  const clean = symbol.trim().toUpperCase();
  if (clean.includes(":")) return clean;
  const [base, quote = "USDT"] = clean.split("/");
  return `BYBIT:${base}${quote}.P`;
}

export function toTradingViewInterval(timeframe?: string): string {
  if (!timeframe) return "5";
  const key = timeframe.toLowerCase();
  return TF_TO_TV[key] ?? "5";
}

export function tradingViewChartUrl(symbol: string, timeframe?: string): string {
  const tvSymbol = toTradingViewSymbol(symbol);
  const interval = toTradingViewInterval(timeframe);
  const params = new URLSearchParams({ symbol: tvSymbol, interval });
  return `https://www.tradingview.com/chart/?${params.toString()}`;
}
