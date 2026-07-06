import { useEffect, useState } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";

import { StatGrid } from "@/components/StatGrid";

import { ExchangePnlCard } from "@/components/ExchangePnlCard";

import { ChartsPanel, ActivityLog } from "@/components/ChartsPanel";

import { AccountBalance } from "@/components/AccountBalance";

import { StrategyCard } from "@/components/StrategyCard";

import { api } from "@/api/client";

import type { BotStatus } from "@/api/client";

import type { StrategyRank } from "@/lib/strategyPattern";



type Props = {

  status: BotStatus | null;

};



export function DashboardPage({ status }: Props) {

  const [ranking, setRanking] = useState<StrategyRank[]>([]);



  useEffect(() => {

    api.strategyRanking()

      .then((r) =>

        setRanking(r.ranking.filter((row) => row.kind === "pattern").slice(0, 6)),

      )

      .catch(() => setRanking([]));

  }, []);



  return (

    <div className="space-y-6">

      <div>

        <h1 className="text-2xl font-bold text-white">Dashboard</h1>

        <p className="mt-1 text-sm text-slate-400">

          {status?.activity ?? "Aguardando atividade do bot..."}

        </p>

      </div>



      <AccountBalance />

      <StatGrid status={status} />

      <ExchangePnlCard />

      <ChartsPanel />



      <div className="grid gap-4 xl:grid-cols-2">

        <Card>

          <CardHeader>

            <CardTitle>Top estratégias</CardTitle>

          </CardHeader>

          <CardContent className="space-y-3">

            {ranking.map((row) => (

              <StrategyCard key={row.strategy} row={row} compact />

            ))}

            {!ranking.length && (

              <p className="py-4 text-sm text-slate-500">Sem dados de estratégia ainda</p>

            )}

          </CardContent>

        </Card>

        <ActivityLog />

      </div>

    </div>

  );

}

