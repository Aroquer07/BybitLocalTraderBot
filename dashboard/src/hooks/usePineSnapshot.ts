import { useEffect, useState } from "react";

import { runPineOnSnapshot } from "@/lib/pineRunner";
import type { PineRenderData } from "@/lib/pineToChart";
import type { ChartSnapshot } from "@/types/chart";

export function usePineSnapshot(snapshot: ChartSnapshot) {
  const [pine, setPine] = useState<PineRenderData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setPine(null);
    setLoading(true);
    setError(null);

    runPineOnSnapshot(snapshot)
      .then((data) => {
        if (cancelled) return;
        setPine(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setPine(null);
        setError(err instanceof Error ? err.message : "PineTS falhou");
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [snapshot]);

  return { pine, loading, error };
}
