import { NavLink, useLocation } from "react-router-dom";
import {
  Activity,
  BarChart3,
  Brain,
  CandlestickChart,
  Eye,
  LayoutDashboard,
  LineChart,
  Settings,
  Target,
  TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Badge } from "@/components/ui/Badge";
import type { AuthMe, BotStatus } from "@/api/client";
import { accountModeLabel } from "@/lib/strategyPattern";

const navGroups: {
  label: string;
  items: { to: string; label: string; icon: typeof LayoutDashboard; end?: boolean }[];
}[] = [
  {
    label: "Mercado",
    items: [
      { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
      { to: "/watchlist", label: "Watchlist", icon: Eye },
      { to: "/analytics", label: "Performance", icon: LineChart },
    ],
  },
  {
    label: "Operações",
    items: [
      { to: "/trades", label: "Trades", icon: Activity },
      { to: "/analysis", label: "Decisões", icon: BarChart3 },
    ],
  },
  {
    label: "Inteligência",
    items: [
      { to: "/strategies", label: "Estratégias", icon: Target },
      { to: "/learning", label: "Aprendizado", icon: Brain },
    ],
  },
  {
    label: "Sistema",
    items: [{ to: "/settings", label: "Configurações", icon: Settings }],
  },
];

type Props = {
  status: BotStatus | null;
  auth?: AuthMe | null;
};

function modeBadgeVariant(mode: string): "loss" | "warn" | "brand" {
  if (mode === "live") return "loss";
  if (mode === "demo") return "warn";
  return "brand";
}

export function Sidebar({ status, auth }: Props) {
  const location = useLocation();
  const mode = status?.bybit_mode ?? "—";

  return (
    <aside className="flex h-screen w-[17.5rem] shrink-0 flex-col border-r border-surface-border bg-surface/95 backdrop-blur-xl">
      <div className="border-b border-surface-border px-5 py-5">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-brand/20 bg-brand/10 shadow-glow">
            <CandlestickChart className="h-5 w-5 text-brand" />
          </div>
          <div className="min-w-0">
            <div className="truncate text-base font-bold tracking-tight text-white">BybitBot</div>
            <div className="flex items-center gap-1 text-[11px] text-slate-500">
              <TrendingUp className="h-3 w-3" />
              Trading terminal
            </div>
          </div>
        </div>

        <div className="mt-4 space-y-2">
          <StatusBadge
            status={status?.running ? "online" : "offline"}
            label={status?.running ? "Bot ativo" : "Bot parado"}
          />
          <Badge variant={modeBadgeVariant(mode)} className="w-full justify-center normal-case">
            {accountModeLabel(mode)}
          </Badge>
          {auth?.email && (
            <div className="truncate rounded-lg border border-surface-border bg-void/50 px-3 py-2 text-[11px] text-slate-400">
              {auth.email}
            </div>
          )}
          {status?.ngrok_url && (
            <a
              href={status.ngrok_url}
              target="_blank"
              rel="noreferrer"
              className="block truncate rounded-lg border border-profit/20 bg-profit/5 px-3 py-2 text-[11px] font-medium text-profit hover:bg-profit/10"
              title={status.ngrok_url}
            >
              ngrok · acesso remoto
            </a>
          )}
        </div>
      </div>

      <nav className="flex-1 space-y-5 overflow-y-auto p-3">
        {navGroups.map((group) => (
          <div key={group.label}>
            <div className="mb-2 px-3 text-[10px] font-bold uppercase tracking-widest text-slate-600">
              {group.label}
            </div>
            <div className="space-y-0.5">
              {group.items.map(({ to, label, icon: Icon, end }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition",
                      isActive
                        ? "border border-brand/20 bg-brand/10 text-brand shadow-glow"
                        : "text-slate-400 hover:bg-surface-hover hover:text-slate-100",
                    )
                  }
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  {label}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      <div className="border-t border-surface-border p-4">
        <div className="rounded-lg border border-surface-border bg-void/40 px-3 py-2.5">
          <div className="data-label">Atividade</div>
          <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-400">
            {status?.activity ?? "Aguardando sinal do bot..."}
          </p>
          {location.pathname !== "/" && (
            <p className="mt-2 font-mono text-[10px] tabular-nums text-slate-600">
              {status?.open_positions ?? 0} pos. abertas
            </p>
          )}
        </div>
      </div>
    </aside>
  );
}
