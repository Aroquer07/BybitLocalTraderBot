import { useEffect, useState } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";

import { api, type Trade } from "@/api/client";

import { realizedPnlUsd } from "@/lib/equityCurve";

import { formatPct, formatUsd } from "@/lib/utils";



export function TradesPage() {

  const [trades, setTrades] = useState<Trade[]>([]);

  const [stats, setStats] = useState<Record<string, number>>({});



  useEffect(() => {

    api.trades().then((data) => {

      setTrades(data.trades);

      setStats(data.stats);

    });

  }, []);



  const sorted = [...trades].sort(

    (a, b) => new Date(b.opened_at).getTime() - new Date(a.opened_at).getTime(),

  );



  const pnlUsd = (t: Trade) =>

    t.pnl_usd != null ? t.pnl_usd : realizedPnlUsd(t);



  return (

    <div className="space-y-6">

      <div>

        <h1 className="text-2xl font-bold text-white">Trades</h1>

        <p className="mt-1 text-sm text-slate-400">

          {stats.total_trades ?? 0} total · {stats.open_trades ?? 0} abertos · win rate{" "}

          {formatPct(stats.winrate_pct ?? 0)}

        </p>

      </div>



      <Card>

        <CardHeader>

          <CardTitle>Histórico</CardTitle>

        </CardHeader>

        <CardContent>

          <div className="overflow-x-auto">

            <table className="w-full text-left text-sm">

              <thead className="text-slate-400">

                <tr>

                  <th className="pb-2">Símbolo</th>

                  <th className="pb-2">Dir.</th>

                  <th className="pb-2">Fonte</th>

                  <th className="pb-2">Status</th>

                  <th className="pb-2">Entrada</th>

                  <th className="pb-2">PnL</th>

                  <th className="pb-2">Conf.</th>

                  <th className="pb-2">Aberto em</th>

                </tr>

              </thead>

              <tbody>

                {sorted.map((t) => {

                  const usd = pnlUsd(t);

                  const positive = (t.pnl_pct ?? 0) >= 0;

                  return (

                    <tr key={t.id} className="border-t border-surface-border">

                      <td className="py-2 font-medium">{t.symbol}</td>

                      <td className="py-2">{t.direction}</td>

                      <td className="py-2">{t.source}</td>

                      <td className="py-2 capitalize">{t.status}</td>

                      <td className="py-2">{t.entry_price}</td>

                      <td className={positive ? "py-2 text-emerald-400" : "py-2 text-rose-400"}>

                        {t.pnl_pct != null ? (

                          <div>

                            <div>{formatPct(t.pnl_pct)}</div>

                            <div className="text-xs opacity-80">{formatUsd(usd)}</div>

                          </div>

                        ) : (

                          "—"

                        )}

                      </td>

                      <td className="py-2">{(t.confidence * 100).toFixed(0)}%</td>

                      <td className="py-2 text-xs text-slate-400">

                        {new Date(t.opened_at).toLocaleString()}

                      </td>

                    </tr>

                  );

                })}

              </tbody>

            </table>

          </div>

        </CardContent>

      </Card>

    </div>

  );

}

