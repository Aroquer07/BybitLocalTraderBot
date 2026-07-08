import { cn } from "@/lib/utils";

type Props = {
  status: "online" | "offline" | "warning";
  label: string;
  pulse?: boolean;
};

export function StatusBadge({ status, label, pulse = true }: Props) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-semibold",
        status === "online" && "border-profit/25 bg-profit/10 text-profit",
        status === "offline" && "border-loss/25 bg-loss/10 text-loss",
        status === "warning" && "border-warn/25 bg-warn/10 text-warn",
      )}
    >
      <span
        className={cn(
          "h-2 w-2 rounded-full",
          status === "online" && "bg-profit",
          status === "offline" && "bg-loss",
          status === "warning" && "bg-warn",
          status === "online" && pulse && "animate-pulse-soft",
        )}
      />
      {label}
    </span>
  );
}
