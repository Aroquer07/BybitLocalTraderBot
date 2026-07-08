import { ChartsPanel, ActivityLog } from "@/components/ChartsPanel";
import { PageHeader } from "@/components/ui/PageHeader";

export function AnalyticsPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Performance"
        description="Curva de equity, PnL por fonte e breakdown por símbolo."
      />
      <ChartsPanel />
      <ActivityLog />
    </div>
  );
}
