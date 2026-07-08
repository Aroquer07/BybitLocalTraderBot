import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

type Column<T> = {
  key: string;
  header: string;
  className?: string;
  cell: (row: T) => ReactNode;
};

type Props<T> = {
  columns: Column<T>[];
  data: T[];
  keyFn: (row: T) => string;
  emptyMessage?: string;
  className?: string;
};

export function DataTable<T>({ columns, data, keyFn, emptyMessage = "Sem dados", className }: Props<T>) {
  if (!data.length) {
    return (
      <div className="rounded-lg border border-dashed border-surface-border px-6 py-12 text-center text-sm text-slate-500">
        {emptyMessage}
      </div>
    );
  }

  return (
    <div className={cn("overflow-x-auto rounded-lg border border-surface-border", className)}>
      <table className="w-full min-w-full text-left text-sm">
        <thead>
          <tr className="border-b border-surface-border bg-void/40">
            {columns.map((col) => (
              <th key={col.key} className={cn("data-label px-4 py-3 font-medium", col.className)}>
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row) => (
            <tr
              key={keyFn(row)}
              className="border-b border-surface-border/50 transition hover:bg-surface-hover/50"
            >
              {columns.map((col) => (
                <td key={col.key} className={cn("px-4 py-3 text-slate-300", col.className)}>
                  {col.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
