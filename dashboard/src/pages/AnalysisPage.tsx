import { useEffect, useState } from "react";
import { FileText, ScrollText } from "lucide-react";
import { AnalysisDecisionList } from "@/components/AnalysisDecisionList";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { Tabs } from "@/components/ui/Tabs";
import { MetricTile } from "@/components/ui/MetricTile";
import { readUtcOffsetHours } from "@/lib/timezone";
import { api, type AnalysisPayload } from "@/api/client";

export function AnalysisPage() {
  const [data, setData] = useState<AnalysisPayload | null>(null);
  const [settings, setSettings] = useState<Record<string, unknown> | null>(null);
  const [tab, setTab] = useState<"rejections" | "approvals">("rejections");
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.analysis(), api.settings()])
      .then(([analysis, cfg]) => {
        setData(analysis);
        setSettings(cfg);
      })
      .catch(() => setData(null));
  }, []);

  if (!data) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-slate-500">
        Carregando análise...
      </div>
    );
  }

  const utcOffsetHours =
    typeof data.utc_offset_hours === "number" && !Number.isNaN(data.utc_offset_hours)
      ? data.utc_offset_hours
      : readUtcOffsetHours(settings);

  const rejections = [...data.rejections].reverse();
  const approvals = [...(data.approvals ?? [])].reverse();

  return (
    <div className="space-y-8">
      <PageHeader
        title="Decisões"
        description="Rejeições e aprovações com snapshot do gráfico no momento da decisão."
      />

      <div className="grid gap-4 sm:grid-cols-3">
        <MetricTile label="Rejeições" value={rejections.length} />
        <MetricTile label="Aprovações" value={approvals.length} />
        <MetricTile label="UTC offset" value={`${utcOffsetHours}h`} subValue="Fuso do gráfico" />
      </div>

      <Tabs
        tabs={[
          { id: "rejections", label: "Rejeições", count: rejections.length },
          { id: "approvals", label: "Aprovações", count: approvals.length },
        ]}
        active={tab}
        onChange={(id) => setTab(id as "rejections" | "approvals")}
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-4 w-4 text-brand" />
            {tab === "rejections" ? "Rejeições recentes" : "Aprovações recentes"}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {tab === "rejections" ? (
            <AnalysisDecisionList
              items={rejections}
              kind="rejection"
              expanded={expanded}
              onToggle={(id) => setExpanded(id || null)}
              emptyMessage="Nenhuma rejeição registrada"
              utcOffsetHours={utcOffsetHours}
            />
          ) : (
            <AnalysisDecisionList
              items={approvals}
              kind="approval"
              expanded={expanded}
              onToggle={(id) => setExpanded(id || null)}
              emptyMessage="Nenhuma aprovação registrada ainda"
              utcOffsetHours={utcOffsetHours}
            />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ScrollText className="h-4 w-4 text-slate-500" />
            Log do bot
          </CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="max-h-80 overflow-auto rounded-lg border border-surface-border bg-void/60 p-4 font-mono text-xs leading-relaxed text-slate-400">
            {data.log_tail.join("\n") || "Sem logs"}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}
