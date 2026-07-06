import { NavLink } from "react-router-dom";

import {

  Activity,

  BarChart3,

  Brain,

  Eye,

  LayoutDashboard,

  LineChart,

  Settings,

  Target,

} from "lucide-react";

import { cn } from "@/lib/utils";

import { StatusBadge } from "@/components/ui/StatusBadge";

import type { AuthMe, BotStatus } from "@/api/client";

import { accountModeLabel } from "@/lib/strategyPattern";



const links = [

  { to: "/", label: "Dashboard", icon: LayoutDashboard },

  { to: "/watchlist", label: "Watchlist", icon: Eye },

  { to: "/strategies", label: "Estratégias", icon: Target },

  { to: "/trades", label: "Trades", icon: Activity },

  { to: "/analytics", label: "Analytics", icon: LineChart },

  { to: "/learning", label: "Aprendizado", icon: Brain },

  { to: "/analysis", label: "Análise", icon: BarChart3 },

  { to: "/settings", label: "Configurações", icon: Settings },

];



type Props = {

  status: BotStatus | null;

  auth?: AuthMe | null;

};



export function Sidebar({ status, auth }: Props) {

  const mode = status?.bybit_mode ?? "—";

  const modeClass =

    mode === "live" ? "text-rose-300" : mode === "demo" ? "text-amber-300" : "text-cyan-300";



  return (

    <aside className="flex h-screen w-64 flex-col border-r border-surface-border bg-surface-raised/50 backdrop-blur">

      <div className="border-b border-surface-border px-5 py-6">

        <div className="text-lg font-bold tracking-tight text-white">BybitBot</div>

        <p className="mt-1 text-xs text-slate-400">Centro de controle</p>

        <div className="mt-4 space-y-2">

          <StatusBadge

            status={status?.running ? "online" : "offline"}

            label={status?.running ? "Bot ativo" : "Bot parado"}

          />

          <div

            className={`inline-flex items-center rounded-lg border border-surface-border bg-black/30 px-3 py-1.5 text-xs font-semibold ${modeClass}`}

          >

            Conta: {accountModeLabel(mode)}

          </div>

          {auth?.email && (
            <div className="truncate rounded-lg border border-surface-border bg-black/30 px-3 py-1.5 text-xs text-slate-300">
              Admin: {auth.email}
            </div>
          )}
          {status?.ngrok_url && (

            <a

              href={status.ngrok_url}

              target="_blank"

              rel="noreferrer"

              className="block truncate rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-xs text-emerald-300 hover:bg-emerald-500/20"

              title={status.ngrok_url}

            >

              Acesso remoto (ngrok)

            </a>

          )}

        </div>

      </div>

      <nav className="flex-1 space-y-1 p-3">

        {links.map(({ to, label, icon: Icon }) => (

          <NavLink

            key={to}

            to={to}

            end={to === "/"}

            className={({ isActive }) =>

              cn(

                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors",

                isActive

                  ? "bg-accent/15 text-accent"

                  : "text-slate-300 hover:bg-slate-800 hover:text-white",

              )

            }

          >

            <Icon className="h-4 w-4" />

            {label}

          </NavLink>

        ))}

      </nav>

      <div className="border-t border-surface-border p-4 text-xs text-slate-500">

        Modo: <span className={modeClass}>{accountModeLabel(mode)}</span>

      </div>

    </aside>

  );

}

