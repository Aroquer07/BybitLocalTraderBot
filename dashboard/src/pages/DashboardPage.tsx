import { useEffect, useState } from "react";
import { Activity, TrendingUp, Wallet, Zap } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { MetricTile } from "@/components/ui/MetricTile";
import { Badge } from "@/components/ui/Badge";
import { ExchangePnlCard } from "@/components/ExchangePnlCard";
import { ChartsPanel, ActivityLog } from "@/components/ChartsPanel";
import { AccountBalance } from "@/components/AccountBalance";
import { StrategyCard } from "@/components/StrategyCard";
import { api } from "@/api/client";
import type { BotStatus } from "@/api/client";
import type { StrategyRank } from "@/lib/strategyPattern";
import { formatPct, formatUsd } from "@/lib/utils";

type Props = {
  status: BotStatus | null;
};

export function DashboardPage({ status }: Props) {
  const [ranking, setRanking] = useState<StrategyRank[]>([]);
  const stats = status?.journal_stats ?? {};
  const totalPnlUsd = stats.total_pnl_usd ?? 0;

  useEffect(() => {
    api
      .strategyRanking()
      .then((r) => setRanking(r.ranking.filter((row) => row.kind === "pattern").slice(0, 6)))
      .catch(() => setRanking([]));
  }, []);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Overview"
        description={status?.activity ?? "Monitoramento em tempo real do bot e da conta Bybit."}
        badge={
          status?.running ? (
            <Badge variant="profit">Operacional</Badge>
          ) : (
            <Badge variant="neutral">Parado</Badge>
          )
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricTile
          label="Posições abertas"
          value={status?.open_positions ?? 0}
          icon={<Activity className="h-4 w-4" />}
        />
        <MetricTile
          label="Trades fechados"
          value={stats.closed_trades ?? 0}
          subValue={`${stats.wins ?? 0}W / ${stats.losses ?? 0}L`}
          icon={<TrendingUp className="h-4 w-4" />}
        />
        <MetricTile
          label="Win rate"
          value={formatPct(stats.winrate_pct ?? 0)}
          trend={(stats.winrate_pct ?? 0) >= 50 ? "up" : (stats.winrate_pct ?? 0) > 0 ? "down" : "neutral"}
        />
        <MetricTile
          label="PnL journal"
          value={formatUsd(totalPnlUsd)}
          trend={totalPnlUsd >= 0 ? "up" : totalPnlUsd < 0 ? "down" : "neutral"}
          icon={<Wallet className="h-4 w-4" />}
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-12">
        <div className="space-y-6 xl:col-span-8">
          <AccountBalance />
          <ChartsPanel />
        </div>
        <div className="space-y-6 xl:col-span-4">
          <ExchangePnlCard />
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Zap className="h-4 w-4 text-brand" />
                Top padrões
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {ranking.map((row) => (
                <StrategyCard key={row.strategy} row={row} compact />
              ))}
              {!ranking.length && (
                <p className="py-6 text-center text-sm text-slate-500">Sem dados de estratégia ainda</p>
              )}
            </CardContent>
          </Card>
          <ActivityLog />
        </div>
      </div>
    </div>
  );
}
