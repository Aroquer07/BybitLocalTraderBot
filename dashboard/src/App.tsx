import { useCallback, useEffect, useState } from "react";
import { Routes, Route, useLocation } from "react-router-dom";
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
import { Alert } from "@/components/ui/Alert";
import type { BotStatus } from "@/api/client";

const routeTitles: Record<string, string> = {
  "/": "Overview",
  "/watchlist": "Watchlist",
  "/analytics": "Performance",
  "/trades": "Trades",
  "/analysis": "Decisões",
  "/strategies": "Estratégias",
  "/learning": "Aprendizado",
  "/settings": "Configurações",
};

export default function App() {
  const { status: polled, auth, error, accessDenied } = useBotStatus();
  const [status, setStatus] = useState<BotStatus | null>(null);
  const location = useLocation();

  useEffect(() => {
    if (polled) setStatus(polled);
  }, [polled]);

  const onSSE = useCallback((s: BotStatus) => setStatus(s), []);
  useSSE(onSSE);

  const liveStatus = status ?? polled;
  const pageTitle = routeTitles[location.pathname] ?? "BybitBot";

  if (accessDenied) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-void p-6">
        <div className="panel max-w-md p-8 text-center">
          <h1 className="text-xl font-bold text-white">Acesso negado</h1>
          <p className="mt-3 text-sm text-loss">{error}</p>
          <p className="mt-4 text-xs text-slate-500">
            Acesso remoto bloqueado. Use a URL local ou configure o admin.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-void">
      <Sidebar status={liveStatus} auth={auth} />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex items-center justify-between gap-4 border-b border-surface-border bg-surface/80 px-6 py-3 backdrop-blur-xl lg:px-8">
          <div className="min-w-0">
            <div className="text-[10px] font-bold uppercase tracking-widest text-slate-600">Terminal</div>
            <h2 className="truncate text-lg font-semibold text-white">{pageTitle}</h2>
          </div>
          <div className="hidden items-center gap-3 font-mono text-xs tabular-nums text-slate-500 sm:flex">
            <span className={liveStatus?.running ? "text-profit" : "text-loss"}>
              {liveStatus?.running ? "● LIVE" : "○ OFF"}
            </span>
            <span className="text-slate-700">|</span>
            <span>{liveStatus?.open_positions ?? 0} pos.</span>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-6 lg:p-8">
          {error && (
            <Alert variant="error" className="mb-6">
              API inacessível: {error}. Inicie o dashboard via <code className="font-mono text-xs">start.bat</code>.
            </Alert>
          )}
          <Routes>
            <Route path="/" element={<DashboardPage status={liveStatus} />} />
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
    </div>
  );
}
