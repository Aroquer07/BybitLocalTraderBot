import { cn } from "@/lib/utils";

type Props = {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  description?: string;
  className?: string;
};

export function Switch({ label, checked, onChange, description, className }: Props) {
  return (
    <label className={cn("toggle-row cursor-pointer", className)}>
      <div className="min-w-0">
        <span className="text-slate-200">{label}</span>
        {description && <p className="mt-0.5 text-xs text-slate-500">{description}</p>}
      </div>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 shrink-0 rounded border-surface-border accent-brand"
      />
    </label>
  );
}
