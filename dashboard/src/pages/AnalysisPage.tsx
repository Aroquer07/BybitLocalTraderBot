import { useEffect, useState } from "react";

import { AnalysisDecisionList } from "@/components/AnalysisDecisionList";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { readUtcOffsetHours } from "@/lib/timezone";
import { api, type AnalysisPayload } from "@/api/client";

type Tab = "rejections" | "approvals";

export function AnalysisPage() {
  const [data, setData] = useState<AnalysisPayload | null>(null);
  const [settings, setSettings] = useState<Record<string, unknown> | null>(null);
  const [tab, setTab] = useState<Tab>("rejections");
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
    return <p className="text-slate-400">Carregando análise...</p>;
  }

  const utcOffsetHours =
    typeof data.utc_offset_hours === "number" && !Number.isNaN(data.utc_offset_hours)
      ? data.utc_offset_hours
      : readUtcOffsetHours(settings);

  const rejections = [...data.rejections].reverse();
  const approvals = [...(data.approvals ?? [])].reverse();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Análise</h1>
        <p className="mt-1 text-sm text-slate-400">
          Rejeições e aprovações com foto do gráfico no momento da decisão (Pine traduzido)
        </p>
      </div>

      <div className="flex gap-2">
        <TabButton
          active={tab === "rejections"}
          onClick={() => setTab("rejections")}
          label={`Rejeições (${rejections.length})`}
        />
        <TabButton
          active={tab === "approvals"}
          onClick={() => setTab("approvals")}
          label={`Aprovações (${approvals.length})`}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
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
          <CardTitle>Log do bot</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="max-h-80 overflow-auto rounded-lg bg-black/40 p-4 font-mono text-xs text-slate-300">
            {data.log_tail.join("\n") || "Sem logs"}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
        active
          ? "bg-accent/20 text-accent"
          : "bg-slate-800/60 text-slate-400 hover:text-white"
      }`}
    >
      {label}
    </button>
  );
}
