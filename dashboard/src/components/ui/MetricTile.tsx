import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

type Props = {
  label: string;
  value: ReactNode;
  subValue?: ReactNode;
  trend?: "up" | "down" | "neutral";
  icon?: ReactNode;
  className?: string;
};

export function MetricTile({ label, value, subValue, trend, icon, className }: Props) {
  const valueClass =
    trend === "up" ? "text-profit" : trend === "down" ? "text-loss" : "text-slate-50";

  return (
    <div className={cn("panel p-4", className)}>
      <div className="flex items-start justify-between gap-2">
        <span className="data-label">{label}</span>
        {icon && <span className="text-slate-500">{icon}</span>}
      </div>
      <div className={cn("data-value mt-2", valueClass)}>{value}</div>
      {subValue && <div className="mt-1 font-mono text-xs tabular-nums text-slate-500">{subValue}</div>}
    </div>
  );
}
