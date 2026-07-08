import { cn } from "@/lib/utils";
import { AlertCircle, CheckCircle2, Info } from "lucide-react";
import type { ReactNode } from "react";

type Variant = "info" | "success" | "error";

type Props = {
  variant?: Variant;
  children: ReactNode;
  className?: string;
};

const styles: Record<Variant, { box: string; icon: typeof Info }> = {
  info: { box: "border-brand/25 bg-brand/8 text-slate-200", icon: Info },
  success: { box: "border-profit/25 bg-profit/8 text-slate-200", icon: CheckCircle2 },
  error: { box: "border-loss/25 bg-loss/8 text-slate-200", icon: AlertCircle },
};

export function Alert({ variant = "info", children, className }: Props) {
  const { box, icon: Icon } = styles[variant];
  return (
    <div className={cn("flex gap-3 rounded-xl border px-4 py-3 text-sm", box, className)} role="status">
      <Icon className="mt-0.5 h-4 w-4 shrink-0 opacity-80" />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
