import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";

import { StrategyCard } from "@/components/StrategyCard";

import { api } from "@/api/client";

import type { StrategyRank } from "@/lib/strategyPattern";



const SCANNER_TOGGLES: { key: string; label: string }[] = [

  { key: "imba", label: "IMBA" },

  { key: "smc", label: "SMC" },

  { key: "screener", label: "Screener" },

  { key: "quality_filters", label: "Filtros de qualidade" },

  { key: "market_patterns", label: "Padrões de mercado" },

  { key: "kalman_hard_block", label: "Bloqueio Kalman" },

  { key: "pwin", label: "P(win)" },

  { key: "learning", label: "Aprendizado" },

  { key: "llm", label: "LLM" },

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



  const scanner = ((settings?.strategies as Record<string, unknown>)?.scanner ??

    {}) as Record<string, unknown>;

  const indicators = (scanner.indicators ?? {}) as Record<string, unknown>;



  return (

    <div className="space-y-6">

      <div>

        <h1 className="text-2xl font-bold text-white">Estratégias</h1>

        <p className="mt-1 text-sm text-slate-400">

          Configure o pipeline do scanner e veja o ranking por padrão

        </p>

      </div>



      {message && (

        <div className="rounded-lg border border-surface-border bg-surface-raised px-4 py-3 text-sm">

          {message}

        </div>

      )}



      <div className="grid gap-4 lg:grid-cols-2">

        <Card>

          <CardHeader>

            <CardTitle>Pipeline do scanner</CardTitle>

          </CardHeader>

          <CardContent className="space-y-4">

            <div>

              <div className="mb-2 text-xs text-slate-500">Estratégia de entrada</div>

              <div className="flex gap-2">

                <Button

                  variant={scanner.entry_strategy === "combined" ? "default" : "outline"}

                  onClick={() => patchScanner(["entry_strategy"], "combined")}

                >

                  Combined

                </Button>

                <Button

                  variant={scanner.entry_strategy === "imba" ? "default" : "outline"}

                  onClick={() => patchScanner(["entry_strategy"], "imba")}

                >

                  IMBA

                </Button>

                <Button

                  variant={scanner.entry_strategy === "sniper" ? "default" : "outline"}

                  onClick={() => patchScanner(["entry_strategy"], "sniper")}

                >

                  Sniper

                </Button>

              </div>

            </div>

            <div>

              <div className="mb-2 text-xs text-slate-500">Modo</div>

              <div className="flex gap-2">

                {["autonomous", "assisted"].map((mode) => (

                  <Button

                    key={mode}

                    variant={scanner.mode === mode ? "default" : "outline"}

                    onClick={() => patchScanner(["mode"], mode)}

                  >

                    {mode}

                  </Button>

                ))}

              </div>

            </div>

            <div className="space-y-2">

              {SCANNER_TOGGLES.map(({ key, label }) => (

                <label key={key} className="flex items-center justify-between rounded-lg bg-black/20 px-3 py-2 text-sm">

                  <span className="text-slate-300">{label}</span>

                  <input

                    type="checkbox"

                    checked={Boolean(scanner[key])}

                    onChange={(e) => patchScanner([key], e.target.checked)}

                    className="h-4 w-4 accent-emerald-500"

                  />

                </label>

              ))}

            </div>

          </CardContent>

        </Card>



        <Card>

          <CardHeader>

            <CardTitle>Indicadores do scanner</CardTitle>

          </CardHeader>

          <CardContent className="space-y-2">

            {INDICATOR_TOGGLES.map(({ key, label, type = "boolean" }) =>

              type === "number" ? (

                <label key={key} className="block space-y-1 text-sm">

                  <span className="text-slate-400">{label}</span>

                  <input

                    type="number"

                    value={String(indicators[key] ?? "")}

                    onChange={(e) =>

                      patchScanner(["indicators", key], Number(e.target.value))

                    }

                    className="w-full rounded-lg border border-surface-border bg-black/30 px-3 py-2"

                  />

                </label>

              ) : (

                <label key={key} className="flex items-center justify-between rounded-lg bg-black/20 px-3 py-2 text-sm">

                  <span className="text-slate-300">{label}</span>

                  <input

                    type="checkbox"

                    checked={Boolean(indicators[key])}

                    onChange={(e) => patchScanner(["indicators", key], e.target.checked)}

                    className="h-4 w-4 accent-emerald-500"

                  />

                </label>

              ),

            )}

          </CardContent>

        </Card>

      </div>



      <div>

        <h2 className="mb-4 text-lg font-semibold text-white">Ranking por padrão</h2>

        <div className="grid gap-4 lg:grid-cols-2">

          {ranking.map((row) => (

            <StrategyCard key={row.strategy} row={row} />

          ))}

          {!ranking.length && (

            <p className="text-sm text-slate-500">Sem trades fechados com features ainda</p>

          )}

        </div>

      </div>

    </div>

  );

}

