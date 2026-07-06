import { ChartsPanel } from "@/components/ChartsPanel";

export function AnalyticsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Analytics</h1>
        <p className="mt-1 text-sm text-slate-400">Performance charts and symbol breakdown</p>
      </div>
      <ChartsPanel />
    </div>
  );
}
