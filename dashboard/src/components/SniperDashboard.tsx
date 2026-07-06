import type { SniperPanel } from "@/types/chart";

type Props = {
  panel: SniperPanel;
};

function toneClass(tone?: string): string {
  if (tone === "bull") return "text-emerald-400";
  if (tone === "bear") return "text-rose-400";
  if (tone === "info") return "text-sky-400";
  return "text-slate-200";
}

function biasBg(bias: string): string {
  if (bias.includes("STRONG BULL")) return "bg-emerald-600";
  if (bias.includes("STRONG BEAR")) return "bg-rose-600";
  if (bias.includes("MILD BULL")) return "bg-emerald-700/80";
  if (bias.includes("MILD BEAR")) return "bg-rose-700/80";
  return "bg-slate-600";
}

export function SniperDashboard({ panel }: Props) {
  return (
    <div className="pointer-events-none absolute left-2 top-2 z-10 max-w-[220px] overflow-hidden rounded border border-slate-600/60 bg-[#fff9c4]/10 text-[10px] shadow-lg backdrop-blur-sm">
      <div className="grid grid-cols-2 border-b border-slate-600/40">
        <div className="bg-emerald-600 px-2 py-1 font-semibold text-white">BULL SCORE</div>
        <div className="bg-emerald-600 px-2 py-1 text-right font-semibold text-white">
          {panel.bull_pct.toFixed(0)}%
        </div>
        <div className="bg-rose-600 px-2 py-1 font-semibold text-white">BEAR SCORE</div>
        <div className="bg-rose-600 px-2 py-1 text-right font-semibold text-white">
          {panel.bear_pct.toFixed(0)}%
        </div>
      </div>
      <div className="grid grid-cols-2 border-b border-slate-600/40">
        <div className="bg-black/50 px-2 py-1 text-slate-300">MARKET BIAS</div>
        <div className={`px-2 py-1 text-right font-medium text-white ${biasBg(panel.bias)}`}>
          {panel.bias}
        </div>
      </div>
      <div className="divide-y divide-slate-700/40 bg-black/40">
        {panel.rows.map((row) => (
          <div key={row.label} className="grid grid-cols-2 px-2 py-0.5">
            <span className="text-slate-400">{row.label}</span>
            <span className={`text-right font-medium ${toneClass(row.tone)}`}>{row.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
