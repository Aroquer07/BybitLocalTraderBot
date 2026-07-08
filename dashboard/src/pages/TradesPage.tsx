import { useEffect, useMemo, useState } from "react";
import { Filter } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { Tabs } from "@/components/ui/Tabs";
import { MetricTile } from "@/components/ui/MetricTile";
import { DataTable } from "@/components/ui/DataTable";
import { Badge } from "@/components/ui/Badge";
import { api, type Trade } from "@/api/client";
import { realizedPnlUsd } from "@/lib/equityCurve";
import { formatPct, formatUsd, cn } from "@/lib/utils";

type FilterTab = "all" | "open" | "closed" | "wins" | "losses";

export function TradesPage() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [stats, setStats] = useState<Record<string, number>>({});
  const [filter, setFilter] = useState<FilterTab>("all");

  useEffect(() => {
    api.trades().then((data) => {
      setTrades(data.trades);
      setStats(data.stats);
    });
  }, []);

  const sorted = useMemo(
    () => [...trades].sort((a, b) => new Date(b.opened_at).getTime() - new Date(a.opened_at).getTime()),
    [trades],
  );

  const filtered = useMemo(() => {
    switch (filter) {
      case "open":
        return sorted.filter((t) => t.status === "open");
      case "closed":
        return sorted.filter((t) => t.status === "closed");
      case "wins":
        return sorted.filter((t) => (t.pnl_pct ?? 0) > 0);
      case "losses":
        return sorted.filter((t) => (t.pnl_pct ?? 0) < 0);
      default:
        return sorted;
    }
  }, [sorted, filter]);

  const pnlUsd = (t: Trade) => (t.pnl_usd != null ? t.pnl_usd : realizedPnlUsd(t));

  const tabs = [
    { id: "all", label: "Todos", count: sorted.length },
    { id: "open", label: "Abertos", count: sorted.filter((t) => t.status === "open").length },
    { id: "closed", label: "Fechados", count: sorted.filter((t) => t.status === "closed").length },
    { id: "wins", label: "Ganhos", count: sorted.filter((t) => (t.pnl_pct ?? 0) > 0).length },
    { id: "losses", label: "Perdas", count: sorted.filter((t) => (t.pnl_pct ?? 0) < 0).length },
  ];

  return (
    <div className="space-y-8">
      <PageHeader
        title="Trades"
        description="Histórico completo do journal com PnL, confiança e origem do sinal."
        badge={<Badge variant="brand">{stats.total_trades ?? 0} total</Badge>}
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Abertos" value={stats.open_trades ?? 0} />
        <MetricTile label="Fechados" value={stats.closed_trades ?? 0} />
        <MetricTile
          label="Win rate"
          value={formatPct(stats.winrate_pct ?? 0)}
          trend={(stats.winrate_pct ?? 0) >= 50 ? "up" : "down"}
        />
        <MetricTile
          label="PnL total"
          value={formatUsd(stats.total_pnl_usd ?? 0)}
          trend={(stats.total_pnl_usd ?? 0) >= 0 ? "up" : "down"}
        />
      </div>

      <div className="space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <Tabs tabs={tabs} active={filter} onChange={(id) => setFilter(id as FilterTab)} />
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Filter className="h-3.5 w-3.5" />
            {filtered.length} resultado(s)
          </div>
        </div>

        <DataTable
          data={filtered}
          keyFn={(t) => t.id}
          emptyMessage="Nenhum trade neste filtro"
          columns={[
            {
              key: "symbol",
              header: "Par",
              cell: (t) => <span className="font-semibold text-white">{t.symbol}</span>,
            },
            {
              key: "direction",
              header: "Dir.",
              cell: (t) => (
                <Badge variant={t.direction === "LONG" ? "profit" : "loss"} className="normal-case">
                  {t.direction}
                </Badge>
              ),
            },
            {
              key: "source",
              header: "Fonte",
              cell: (t) => <span className="text-slate-400">{t.source}</span>,
            },
            {
              key: "status",
              header: "Status",
              cell: (t) => (
                <Badge variant={t.status === "open" ? "brand" : "neutral"} className="normal-case">
                  {t.status}
                </Badge>
              ),
            },
            {
              key: "entry",
              header: "Entrada",
              className: "font-mono tabular-nums",
              cell: (t) => t.entry_price,
            },
            {
              key: "pnl",
              header: "PnL",
              cell: (t) => {
                const positive = (t.pnl_pct ?? 0) >= 0;
                const usd = pnlUsd(t);
                return t.pnl_pct != null ? (
                  <div className={cn("font-mono tabular-nums", positive ? "text-profit" : "text-loss")}>
                    <div className="font-semibold">{formatPct(t.pnl_pct)}</div>
                    <div className="text-xs opacity-80">{formatUsd(usd)}</div>
                  </div>
                ) : (
                  "—"
                );
              },
            },
            {
              key: "conf",
              header: "Conf.",
              className: "font-mono tabular-nums",
              cell: (t) => `${(t.confidence * 100).toFixed(0)}%`,
            },
            {
              key: "opened",
              header: "Aberto em",
              cell: (t) => (
                <span className="text-xs text-slate-500">{new Date(t.opened_at).toLocaleString()}</span>
              ),
            },
          ]}
        />
      </div>
    </div>
  );
}
