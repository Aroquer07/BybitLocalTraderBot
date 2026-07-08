import { useEffect, useState } from "react";
import { Brain, Target, TrendingDown, TrendingUp } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { MetricTile } from "@/components/ui/MetricTile";
import { Badge } from "@/components/ui/Badge";
import { api, type LearningPayload } from "@/api/client";
import { formatPct } from "@/lib/utils";

export function LearningPage() {
  const [data, setData] = useState<LearningPayload | null>(null);

  useEffect(() => {
    api.learning().then(setData).catch(() => setData(null));
  }, []);

  if (!data) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-slate-500">
        Carregando dados de aprendizado...
      </div>
    );
  }

  const { report } = data;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Aprendizado"
        description="Padrões que funcionam, calibração do P(win) e recomendações do motor de learning."
        badge={<Badge variant="brand">{report.total_closed} trades analisados</Badge>}
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Trades fechados" value={report.total_closed} icon={<Target className="h-4 w-4" />} />
        <MetricTile label="Com features" value={report.with_features} />
        <MetricTile label="Rejeições logadas" value={data.rejections_total} />
        <MetricTile
          label="Calibração"
          value={`${report.calibration.length} faixas`}
          icon={<Brain className="h-4 w-4" />}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-profit">
              <TrendingUp className="h-4 w-4" />
              Melhores padrões
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {report.best_patterns.map((p) => (
              <div key={p.pattern} className="rounded-lg border border-profit/15 bg-profit/5 p-4">
                <div className="font-mono text-sm font-semibold tabular-nums text-profit">
                  WR {p.winrate_pct.toFixed(0)}% · n={p.sample_n}
                </div>
                <div className="mt-1 text-sm text-slate-300">{p.pattern}</div>
                <div className="mt-2 font-mono text-xs tabular-nums text-slate-500">{formatPct(p.avg_pnl_pct)} médio</div>
              </div>
            ))}
            {!report.best_patterns.length && (
              <p className="text-sm text-slate-500">Amostras insuficientes</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-loss">
              <TrendingDown className="h-4 w-4" />
              Piores padrões
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {report.worst_patterns.map((p) => (
              <div key={p.pattern} className="rounded-lg border border-loss/15 bg-loss/5 p-4">
                <div className="font-mono text-sm font-semibold tabular-nums text-loss">
                  WR {p.winrate_pct.toFixed(0)}% · n={p.sample_n}
                </div>
                <div className="mt-1 text-sm text-slate-300">{p.pattern}</div>
                <div className="mt-2 font-mono text-xs tabular-nums text-slate-500">{formatPct(p.avg_pnl_pct)} médio</div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Calibração P(win)</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {report.calibration.map((c) => (
              <div key={c.predicted_range} className="rounded-lg border border-surface-border bg-void/40 p-4">
                <div className="font-semibold text-white">{c.predicted_range}</div>
                <div className="mt-1 font-mono text-sm tabular-nums text-slate-400">
                  WR real {c.actual_winrate_pct.toFixed(0)}% · n={c.sample_n}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recomendações</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="space-y-3">
            {report.recommendations.map((r) => (
              <li key={r} className="flex gap-3 text-sm text-slate-300">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand" />
                {r}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
