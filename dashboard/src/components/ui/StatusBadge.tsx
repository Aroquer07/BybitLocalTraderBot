import { cn } from "@/lib/utils";

type Props = {
  status: "online" | "offline" | "warning";
  label: string;
};

export function StatusBadge({ status, label }: Props) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium",
        status === "online" && "bg-emerald-500/15 text-emerald-300",
        status === "offline" && "bg-rose-500/15 text-rose-300",
        status === "warning" && "bg-amber-500/15 text-amber-300",
      )}
    >
      <span
        className={cn(
          "h-2 w-2 rounded-full",
          status === "online" && "bg-emerald-400 animate-pulse",
          status === "offline" && "bg-rose-400",
          status === "warning" && "bg-amber-400",
        )}
      />
      {label}
    </span>
  );
}
