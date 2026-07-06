import type { Trade } from "@/api/client";

export type EquityPoint = {
  time: string;
  symbol: string;
  cumulative: number;
};

export function realizedPnlUsd(trade: Trade): number {
  const amount = trade.amount ?? 0;
  const exit = trade.exit_price;
  if (amount > 0 && exit != null && trade.entry_price > 0) {
    if (trade.direction === "LONG") {
      return (exit - trade.entry_price) * amount;
    }
    return (trade.entry_price - exit) * amount;
  }
  if (trade.pnl_pct != null && amount > 0 && trade.entry_price > 0) {
    return amount * trade.entry_price * (trade.pnl_pct / 100);
  }
  return 0;
}

export function buildEquityCurveFromTrades(trades: Trade[]): EquityPoint[] {
  const closed = trades
    .filter((t) => t.status === "closed" && t.closed_at)
    .sort(
      (a, b) =>
        new Date(a.closed_at as string).getTime() - new Date(b.closed_at as string).getTime(),
    );

  let cumulative = 0;
  return closed.map((trade) => {
    const pnl = realizedPnlUsd(trade);
    cumulative = Math.round((cumulative + pnl) * 100) / 100;
    return {
      time: trade.closed_at as string,
      symbol: trade.symbol,
      cumulative,
    };
  });
}

type ChartEquityRow = {
  time: string;
  symbol: string;
  cumulative_pnl_usd?: number;
  cumulative_pnl_pct?: number;
};

export function equityCurveFromChartPayload(rows: ChartEquityRow[]): EquityPoint[] | null {
  if (!rows.length) return [];
  if (typeof rows[0].cumulative_pnl_usd === "number") {
    return rows.map((row) => ({
      time: row.time,
      symbol: row.symbol,
      cumulative: row.cumulative_pnl_usd as number,
    }));
  }
  return null;
}
