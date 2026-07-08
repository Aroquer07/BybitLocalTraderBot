import { cn } from "@/lib/utils";
import type { InputHTMLAttributes } from "react";

type Props = InputHTMLAttributes<HTMLInputElement> & {
  label?: string;
  hint?: string;
};

export function Input({ label, hint, className, id, ...props }: Props) {
  const inputId = id ?? label?.toLowerCase().replace(/\s+/g, "-");
  return (
    <label className="block space-y-1.5 text-sm" htmlFor={inputId}>
      {label && <span className="data-label">{label}</span>}
      <input id={inputId} className={cn("input-field", className)} {...props} />
      {hint && <span className="text-xs text-slate-500">{hint}</span>}
    </label>
  );
}
