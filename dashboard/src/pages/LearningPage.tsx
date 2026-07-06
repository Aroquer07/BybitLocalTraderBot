import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { api, type LearningPayload } from "@/api/client";
import { formatPct } from "@/lib/utils";

export function LearningPage() {
  const [data, setData] = useState<LearningPayload | null>(null);

  useEffect(() => {
    api.learning().then(setData).catch(() => setData(null));
  }, []);

  if (!data) {
    return <p className="text-slate-400">Loading learning data...</p>;
  }

  const { report } = data;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Learning</h1>
        <p className="mt-1 text-sm text-slate-400">
          {report.total_closed} closed trades · {report.with_features} with features ·{" "}
          {data.rejections_total} rejections logged
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Best patterns</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {report.best_patterns.map((p) => (
              <div key={p.pattern} className="rounded-lg bg-black/20 p-3 font-mono text-xs">
                <div className="text-emerald-300">WR {p.winrate_pct.toFixed(0)}% (n={p.sample_n})</div>
                <div className="mt-1 text-slate-400">{p.pattern}</div>
                <div className="mt-1">{formatPct(p.avg_pnl_pct)} avg</div>
              </div>
            ))}
            {!report.best_patterns.length && (
              <p className="text-slate-500">Not enough samples yet</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Worst patterns</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {report.worst_patterns.map((p) => (
              <div key={p.pattern} className="rounded-lg bg-black/20 p-3 font-mono text-xs">
                <div className="text-rose-300">WR {p.winrate_pct.toFixed(0)}% (n={p.sample_n})</div>
                <div className="mt-1 text-slate-400">{p.pattern}</div>
                <div className="mt-1">{formatPct(p.avg_pnl_pct)} avg</div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>P(win) calibration</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-2">
            {report.calibration.map((c) => (
              <div
                key={c.predicted_range}
                className="rounded-lg border border-surface-border p-3 text-sm"
              >
                <div className="font-medium">{c.predicted_range}</div>
                <div className="text-slate-400">
                  Actual WR {c.actual_winrate_pct.toFixed(0)}% · n={c.sample_n}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recommendations</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="list-disc space-y-2 pl-5 text-sm text-slate-300">
            {report.recommendations.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
