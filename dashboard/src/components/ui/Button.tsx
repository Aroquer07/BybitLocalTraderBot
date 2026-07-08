import { cn } from "@/lib/utils";
import type { ButtonHTMLAttributes } from "react";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "outline" | "ghost" | "danger" | "profit";
  size?: "sm" | "md" | "lg";
};

export function Button({
  className,
  variant = "default",
  size = "md",
  ...props
}: Props) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40 disabled:pointer-events-none disabled:opacity-50",
        size === "sm" && "h-8 px-3 text-xs",
        size === "md" && "h-10 px-4 text-sm",
        size === "lg" && "h-11 px-5 text-sm",
        variant === "default" && "bg-brand text-white shadow-glow hover:bg-brand-muted",
        variant === "outline" &&
          "border border-surface-border bg-surface-raised text-slate-200 hover:border-brand/30 hover:bg-surface-hover",
        variant === "ghost" && "text-slate-300 hover:bg-surface-hover hover:text-white",
        variant === "danger" && "bg-loss-muted text-white hover:bg-loss",
        variant === "profit" && "bg-profit-muted text-void hover:bg-profit",
        className,
      )}
      {...props}
    />
  );
}
