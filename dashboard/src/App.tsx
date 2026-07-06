import { useCallback, useEffect, useState } from "react";
import { Routes, Route } from "react-router-dom";
import { Sidebar } from "@/components/layout/Sidebar";
import { useBotStatus, useSSE } from "@/hooks/useBotStatus";
import { DashboardPage } from "@/pages/DashboardPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { StrategiesPage } from "@/pages/StrategiesPage";
import { TradesPage } from "@/pages/TradesPage";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { LearningPage } from "@/pages/LearningPage";
import { AnalysisPage } from "@/pages/AnalysisPage";
import { WatchlistPage } from "@/pages/WatchlistPage";
import type { BotStatus } from "@/api/client";

export default function App() {
  const { status: polled, auth, error, accessDenied } = useBotStatus();
  const [status, setStatus] = useState<BotStatus | null>(null);

  useEffect(() => {
    if (polled) setStatus(polled);
  }, [polled]);

  const onSSE = useCallback((s: BotStatus) => setStatus(s), []);
  useSSE(onSSE);

  if (accessDenied) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface p-6">
        <div className="max-w-md rounded-2xl border border-rose-500/30 bg-rose-500/10 p-8 text-center">
          <h1 className="text-xl font-bold text-white">Acesso negado</h1>
          <p className="mt-3 text-sm text-rose-100">{error}</p>
          <p className="mt-4 text-xs text-slate-400">
            Acesso remoto bloqueado. Use a URL local ou configure o admin.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar status={status ?? polled} auth={auth} />
      <main className="flex-1 overflow-y-auto p-6 lg:p-8">
        {error && (
          <div className="mb-4 rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
            API unreachable: {error}. Start the dashboard API via start.bat.
          </div>
        )}
        <Routes>
          <Route path="/" element={<DashboardPage status={status ?? polled} />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/strategies" element={<StrategiesPage />} />
          <Route path="/trades" element={<TradesPage />} />
          <Route path="/watchlist" element={<WatchlistPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/learning" element={<LearningPage />} />
          <Route path="/analysis" element={<AnalysisPage />} />
        </Routes>
      </main>
    </div>
  );
}
