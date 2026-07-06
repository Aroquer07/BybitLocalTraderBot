import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { formatPct, formatUsd } from "@/lib/utils";
import type { BotStatus } from "@/api/client";

type Props = {
  status: BotStatus | null;
};

export function StatGrid({ status }: Props) {
  const stats = status?.journal_stats ?? {};
  const totalPnlUsd = stats.total_pnl_usd ?? 0;
  const items = [
    { label: "Posições abertas", value: String(status?.open_positions ?? 0) },
    { label: "Trades fechados", value: String(stats.closed_trades ?? 0) },
    { label: "Win rate", value: formatPct(stats.winrate_pct ?? 0) },
    {
      label: "PnL total",
      value: formatUsd(totalPnlUsd),
      valueClass:
        totalPnlUsd >= 0 ? "text-emerald-400" : totalPnlUsd < 0 ? "text-rose-400" : "text-white",
    },
  ];

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => (
        <Card key={item.label}>
          <CardHeader>
            <CardTitle>{item.label}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-semibold ${item.valueClass ?? "text-white"}`}>
              {item.value}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
