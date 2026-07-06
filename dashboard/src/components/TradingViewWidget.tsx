import { useEffect, useId, useRef } from "react";

import { toTradingViewInterval, toTradingViewSymbol, tradingViewChartUrl } from "@/lib/tvSymbol";

type Props = {
  symbol: string;
  timeframe?: string;
  height?: number;
};

type TvWidgetCtor = new (options: Record<string, unknown>) => void;

declare global {
  interface Window {
    TradingView?: { widget: TvWidgetCtor };
  }
}

let tvScriptPromise: Promise<void> | null = null;

function loadTradingViewScript(): Promise<void> {
  if (window.TradingView?.widget) return Promise.resolve();
  if (tvScriptPromise) return tvScriptPromise;
  tvScriptPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector('script[data-tv-widget="1"]');
    if (existing) {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("TradingView script failed")));
      return;
    }
    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/tv.js";
    script.async = true;
    script.dataset.tvWidget = "1";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("TradingView script failed"));
    document.head.appendChild(script);
  });
  return tvScriptPromise;
}

export function TradingViewWidget({ symbol, timeframe, height = 480 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const reactId = useId();
  const containerId = `tv_${reactId.replace(/:/g, "")}`;
  const tvSymbol = toTradingViewSymbol(symbol);
  const interval = toTradingViewInterval(timeframe);
  const chartUrl = tradingViewChartUrl(symbol, timeframe);

  useEffect(() => {
    let cancelled = false;
    const el = containerRef.current;
    if (!el) return;

    el.id = containerId;
    el.innerHTML = "";

    loadTradingViewScript()
      .then(() => {
        if (cancelled || !containerRef.current || !window.TradingView?.widget) return;
        containerRef.current.innerHTML = "";
        new window.TradingView.widget({
          autosize: true,
          symbol: tvSymbol,
          interval,
          timezone: "America/Sao_Paulo",
          theme: "dark",
          style: "1",
          locale: "br",
          enable_publishing: false,
          hide_top_toolbar: false,
          hide_legend: false,
          allow_symbol_change: false,
          container_id: containerId,
          studies: [],
        });
      })
      .catch(() => {
        if (containerRef.current) {
          containerRef.current.innerHTML =
            '<p class="p-4 text-sm text-slate-400">Não foi possível carregar o TradingView.</p>';
        }
      });

    return () => {
      cancelled = true;
      if (containerRef.current) containerRef.current.innerHTML = "";
    };
  }, [containerId, tvSymbol, interval]);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <span>
          {tvSymbol} · {timeframe ?? "5m"} · indicadores Pine da sua conta TradingView
        </span>
        <a
          href={chartUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent hover:underline"
        >
          Abrir no TradingView
        </a>
      </div>
      <div
        ref={containerRef}
        className="w-full overflow-hidden rounded-lg border border-surface-border bg-[#0b0f19]"
        style={{ height }}
      />
      <p className="text-[11px] leading-relaxed text-slate-500">
        Pine Script roda só no TradingView. Cole os arquivos da pasta{" "}
        <code className="text-slate-400">indicators/</code> no editor Pine da sua conta (uma vez).
        Depois eles aparecem aqui igual no print.
      </p>
    </div>
  );
}
