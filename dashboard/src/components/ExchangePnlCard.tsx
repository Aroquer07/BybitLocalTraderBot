import { useEffect, useState } from "react";

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
        <CardTitle>PnL Bybit (semana)</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {error && <p className="text-rose-400">{error}</p>}
        {!data?.available && !error && (
          <p className="text-slate-500">Carregando dados da exchange...</p>
        )}
        {data?.available && (
          <>
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-500">Fills (API bruta)</p>
              <p className="mt-1 text-slate-300">
                {fills.closed_trades ?? 0} fechamentos · {fills.wins ?? 0}W / {fills.losses ?? 0}L ·{" "}
                WR {formatPct(fills.winrate_pct ?? 0)}
              </p>
              <p className="text-lg font-semibold text-white">
                {formatUsd(fills.total_pnl_usd ?? 0)}
              </p>
            </div>
            <div className="border-t border-slate-800 pt-3">
              <p className="text-xs uppercase tracking-wide text-emerald-500/80">
                Posições agrupadas
              </p>
              <p className="mt-1 text-slate-300">
                {groups.position_trades ?? 0} trades · {groups.total_fills ?? 0} fills ·{" "}
                {groups.wins ?? 0}W / {groups.losses ?? 0}L · WR{" "}
                {formatPct(groups.winrate_pct ?? 0)}
              </p>
              <p className="text-slate-400">
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
