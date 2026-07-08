import { cn } from "@/lib/utils";
import type { HTMLAttributes } from "react";

type Variant = "default" | "profit" | "loss" | "warn" | "brand" | "neutral";

type Props = HTMLAttributes<HTMLSpanElement> & {
  variant?: Variant;
};

const variants: Record<Variant, string> = {
  default: "border-surface-border bg-surface-hover text-slate-300",
  profit: "border-profit/25 bg-profit/10 text-profit",
  loss: "border-loss/25 bg-loss/10 text-loss",
  warn: "border-warn/25 bg-warn/10 text-warn",
  brand: "border-brand/25 bg-brand/10 text-brand",
  neutral: "border-surface-border bg-void/50 text-slate-400",
};

export function Badge({ variant = "default", className, ...props }: Props) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}
