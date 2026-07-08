import { cn } from "@/lib/utils";

type Tab = { id: string; label: string; count?: number };

type Props = {
  tabs: Tab[];
  active: string;
  onChange: (id: string) => void;
  className?: string;
};

export function Tabs({ tabs, active, onChange, className }: Props) {
  return (
    <div className={cn("flex flex-wrap gap-1 rounded-xl border border-surface-border bg-void/50 p-1", className)} role="tablist">
      {tabs.map((tab) => {
        const isActive = tab.id === active;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(tab.id)}
            className={cn(
              "rounded-lg px-4 py-2 text-sm font-medium transition",
              isActive
                ? "bg-brand/15 text-brand shadow-sm"
                : "text-slate-400 hover:bg-surface-hover hover:text-slate-200",
            )}
          >
            {tab.label}
            {tab.count != null && (
              <span className={cn("ml-2 font-mono text-xs tabular-nums", isActive ? "text-brand/80" : "text-slate-500")}>
                {tab.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
