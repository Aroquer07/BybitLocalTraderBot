import { cn } from "@/lib/utils";
import type { ButtonHTMLAttributes } from "react";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "outline" | "ghost" | "danger";
  size?: "sm" | "md";
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
        "inline-flex items-center justify-center rounded-lg font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-xs" : "h-10 px-4 text-sm",
        variant === "default" && "bg-accent text-slate-950 hover:bg-accent-muted",
        variant === "outline" && "border border-surface-border bg-surface-raised hover:bg-slate-800",
        variant === "ghost" && "hover:bg-slate-800",
        variant === "danger" && "bg-rose-600 text-white hover:bg-rose-500",
        className,
      )}
      {...props}
    />
  );
}
