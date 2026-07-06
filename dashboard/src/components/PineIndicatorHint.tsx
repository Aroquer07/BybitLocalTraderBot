type Props = {
  strategy?: string;
  activeIndicators?: string[];
};

const STRATEGY_PINE: Record<string, string[]> = {
  sniper: ["sniper entry", "breakout Probability"],
  combined: ["sniper entry", "breakout Probability", "trend speed analyzer", "Range detector"],
  imba: ["ALGO", "Kalman"],
};

export function PineIndicatorHint({ strategy, activeIndicators }: Props) {
  const fromMeta = activeIndicators?.length
    ? activeIndicators.map((n) => {
        if (n === "breakout_probability") return "breakout Probability";
        if (n === "trend_speed") return "trend speed analyzer";
        if (n === "range_detector") return "Range detector";
        if (n === "sniper") return "sniper entry";
        return n;
      })
    : null;

  const files = fromMeta ?? STRATEGY_PINE[strategy ?? "sniper"] ?? STRATEGY_PINE.sniper;

  return (
    <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs text-amber-100/90">
      <div className="font-medium text-amber-200">Indicadores Pine desta estratégia</div>
      <ul className="mt-1 list-inside list-disc text-amber-100/80">
        {files.map((f) => (
          <li key={f}>
            <code className="text-amber-100">{f}</code>
          </li>
        ))}
      </ul>
      <p className="mt-1.5 text-[11px] text-amber-100/60">
        Arquivo em <code>indicators/</code> → TradingView → Pine Editor → colar → Add to chart
      </p>
    </div>
  );
}
