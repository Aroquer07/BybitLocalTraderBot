import { useEffect, useState } from "react";
import { BarChart3 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { api, type ExchangePnlPayload } from "@/api/client";
import { formatPct, formatUsd } from "@/lib/utils";

export function ExchangePnlCard() {
  const [data, setData] = useState<ExchangePnlPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .exchangePnl("week")
      .then((payload) => {
        setData(payload);
        setError(payload.error ?? null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Falha ao carregar PnL"));
  }, []);

  const fills = data?.fills ?? {};
  const groups = data?.position_groups ?? {};

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-brand" />
          PnL Bybit (7d)
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-5 text-sm">
        {error && <p className="text-loss">{error}</p>}
        {!data?.available && !error && (
          <p className="text-slate-500">Carregando dados da exchange...</p>
        )}
        {data?.available && (
          <>
            <div className="rounded-lg border border-surface-border bg-void/40 p-4">
              <p className="data-label">Fills (API bruta)</p>
              <p className="mt-2 text-slate-400">
                {fills.closed_trades ?? 0} fechamentos · {fills.wins ?? 0}W / {fills.losses ?? 0}L · WR{" "}
                {formatPct(fills.winrate_pct ?? 0)}
              </p>
              <p className="mt-2 font-mono text-2xl font-bold tabular-nums text-white">
                {formatUsd(fills.total_pnl_usd ?? 0)}
              </p>
            </div>
            <div className="rounded-lg border border-profit/15 bg-profit/5 p-4">
              <p className="data-label text-profit">Posições agrupadas</p>
              <p className="mt-2 text-slate-400">
                {groups.position_trades ?? 0} trades · {groups.total_fills ?? 0} fills · {groups.wins ?? 0}W /{" "}
                {groups.losses ?? 0}L · WR {formatPct(groups.winrate_pct ?? 0)}
              </p>
              <p className="mt-2 font-mono text-xs tabular-nums text-slate-500">
                Avg W/L: {formatUsd(groups.avg_win_usd ?? 0)} / {formatUsd(groups.avg_loss_usd ?? 0)}
                {groups.profit_factor != null && ` · PF ${groups.profit_factor}`}
              </p>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
