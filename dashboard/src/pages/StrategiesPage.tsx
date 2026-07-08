import { useEffect, useState } from "react";
import { SlidersHorizontal, Trophy } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { Alert } from "@/components/ui/Alert";
import { Switch } from "@/components/ui/Switch";
import { Input } from "@/components/ui/Input";
import { StrategyCard } from "@/components/StrategyCard";
import { api } from "@/api/client";
import type { StrategyRank } from "@/lib/strategyPattern";

const SCANNER_TOGGLES: { key: string; label: string; description?: string }[] = [
  { key: "imba", label: "IMBA", description: "Sinal multi-timeframe principal" },
  { key: "smc", label: "SMC", description: "Smart Money Concepts" },
  { key: "screener", label: "Screener", description: "Filtro de liquidez/volume" },
  { key: "quality_filters", label: "Filtros de qualidade" },
  { key: "market_patterns", label: "Padrões de mercado" },
  { key: "kalman_hard_block", label: "Bloqueio Kalman" },
  { key: "pwin", label: "P(win)", description: "Modelo de probabilidade" },
  { key: "learning", label: "Aprendizado", description: "Bloqueio por padrões ruins" },
  { key: "llm", label: "LLM", description: "Validação por IA" },
];

const INDICATOR_TOGGLES: { key: string; label: string; type?: "boolean" | "number" }[] = [
  { key: "trend_speed", label: "Trend Speed" },
  { key: "range_detector", label: "Range Detector" },
  { key: "sniper", label: "Sniper Entry" },
  { key: "require_all", label: "Exigir todos" },
  { key: "sniper_required", label: "Sniper obrigatório" },
  { key: "allow_trend_without_pullback", label: "Trend sem pullback" },
  { key: "min_sniper_score_pct", label: "Score sniper mín. (%)", type: "number" },
  { key: "min_breakout_probability_pct", label: "Breakout mín. (%)", type: "number" },
];

export function StrategiesPage() {
  const [ranking, setRanking] = useState<StrategyRank[]>([]);
  const [settings, setSettings] = useState<Record<string, unknown> | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = () => {
    Promise.all([api.strategyRanking(), api.settings()])
      .then(([rank, cfg]) => {
        setRanking(rank.ranking.filter((r) => r.kind === "pattern"));
        setSettings(cfg);
      })
      .catch((e) => setMessage(e.message));
  };

  useEffect(() => {
    load();
  }, []);

  const patchScanner = async (path: string[], value: unknown) => {
    if (!settings) return;
    const next = structuredClone(settings);
    let cur = (next.strategies as Record<string, Record<string, unknown>>).scanner;
    for (let i = 0; i < path.length - 1; i++) {
      const key = path[i];
      if (!cur[key]) cur[key] = {};
      cur = cur[key] as Record<string, unknown>;
    }
    cur[path[path.length - 1]] = value;
    const saved = await api.saveSettings(next);
    setSettings(saved);
    setMessage("Estratégia atualizada.");
    load();
  };

  const scanner = ((settings?.strategies as Record<string, unknown>)?.scanner ?? {}) as Record<string, unknown>;
  const indicators = (scanner.indicators ?? {}) as Record<string, unknown>;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Estratégias"
        description="Pipeline do scanner, indicadores ativos e ranking por padrão de mercado."
      />

      {message && <Alert variant="success">{message}</Alert>}

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <SlidersHorizontal className="h-4 w-4 text-brand" />
              Pipeline do scanner
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <div>
              <div className="data-label mb-3">Estratégia de entrada</div>
              <div className="flex flex-wrap gap-2">
                {(["combined", "imba", "sniper"] as const).map((strategy) => (
                  <Button
                    key={strategy}
                    size="sm"
                    variant={scanner.entry_strategy === strategy ? "default" : "outline"}
                    onClick={() => patchScanner(["entry_strategy"], strategy)}
                  >
                    {strategy}
                  </Button>
                ))}
              </div>
            </div>

            <div>
              <div className="data-label mb-3">Modo</div>
              <div className="flex flex-wrap gap-2">
                {["autonomous", "assisted"].map((mode) => (
                  <Button
                    key={mode}
                    size="sm"
                    variant={scanner.mode === mode ? "default" : "outline"}
                    onClick={() => patchScanner(["mode"], mode)}
                  >
                    {mode}
                  </Button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              {SCANNER_TOGGLES.map(({ key, label, description }) => (
                <Switch
                  key={key}
                  label={label}
                  description={description}
                  checked={Boolean(scanner[key])}
                  onChange={(checked) => patchScanner([key], checked)}
                />
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Indicadores</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {INDICATOR_TOGGLES.map(({ key, label, type = "boolean" }) =>
              type === "number" ? (
                <Input
                  key={key}
                  label={label}
                  type="number"
                  value={String(indicators[key] ?? "")}
                  onChange={(e) => patchScanner(["indicators", key], Number(e.target.value))}
                />
              ) : (
                <Switch
                  key={key}
                  label={label}
                  checked={Boolean(indicators[key])}
                  onChange={(checked) => patchScanner(["indicators", key], checked)}
                />
              ),
            )}
          </CardContent>
        </Card>
      </div>

      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <Trophy className="h-5 w-5 text-warn" />
          <h2 className="text-lg font-semibold text-white">Ranking por padrão</h2>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          {ranking.map((row) => (
            <StrategyCard key={row.strategy} row={row} />
          ))}
          {!ranking.length && (
            <p className="text-sm text-slate-500 lg:col-span-2">Sem trades fechados com features ainda</p>
          )}
        </div>
      </section>
    </div>
  );
}
