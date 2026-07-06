import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { api } from "@/api/client";
import { accountModeLabel } from "@/lib/strategyPattern";

type FieldProps = {
  label: string;
  value: unknown;
  onChange: (value: unknown) => void;
  type?: "number" | "text" | "boolean" | "string[]";
};

function Field({ label, value, onChange, type = "text" }: FieldProps) {
  if (type === "boolean") {
    return (
      <label className="flex items-center justify-between gap-4 rounded-lg bg-black/20 px-3 py-2.5 text-sm">
        <span className="text-slate-300">{label}</span>
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
          className="h-4 w-4 accent-emerald-500"
        />
      </label>
    );
  }
  if (type === "number") {
    return (
      <label className="block space-y-1 text-sm">
        <span className="text-slate-400">{label}</span>
        <input
          type="number"
          value={value === undefined || value === null ? "" : String(value)}
          onChange={(e) => onChange(e.target.value === "" ? 0 : Number(e.target.value))}
          className="w-full rounded-lg border border-surface-border bg-black/30 px-3 py-2 text-slate-100"
        />
      </label>
    );
  }
  if (type === "string[]") {
    const arr = Array.isArray(value) ? (value as string[]) : [];
    return (
      <label className="block space-y-1 text-sm">
        <span className="text-slate-400">{label}</span>
        <input
          type="text"
          value={arr.join(", ")}
          onChange={(e) =>
            onChange(
              e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
            )
          }
          className="w-full rounded-lg border border-surface-border bg-black/30 px-3 py-2 text-slate-100"
        />
      </label>
    );
  }
  return (
    <label className="block space-y-1 text-sm">
      <span className="text-slate-400">{label}</span>
      <input
        type="text"
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-surface-border bg-black/30 px-3 py-2 text-slate-100"
      />
    </label>
  );
}

function setNested(obj: Record<string, unknown>, path: string[], value: unknown) {
  const next = structuredClone(obj);
  let cur: Record<string, unknown> = next;
  for (let i = 0; i < path.length - 1; i++) {
    const key = path[i];
    if (typeof cur[key] !== "object" || cur[key] === null) cur[key] = {};
    cur = cur[key] as Record<string, unknown>;
  }
  cur[path[path.length - 1]] = value;
  return next;
}

export function SettingsForm() {
  const [settings, setSettings] = useState<Record<string, unknown> | null>(null);
  const [accountMode, setAccountMode] = useState("demo");
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    const [cfg, account] = await Promise.all([api.settings(), api.account()]);
    setSettings(cfg);
    setAccountMode(account.mode);
  }, []);

  useEffect(() => {
    load()
      .catch((e) => setMessage(e.message))
      .finally(() => setLoading(false));
    const id = setInterval(() => {
      api.settings().then(setSettings).catch(() => undefined);
    }, 10_000);
    return () => clearInterval(id);
  }, [load]);

  const patch = (path: string[], value: unknown) => {
    if (!settings) return;
    setSettings(setNested(settings, path, value));
  };

  const save = async () => {
    if (!settings) return;
    try {
      const saved = await api.saveSettings(settings);
      setSettings(saved);
      setMessage("Configurações salvas. O bot recarrega no próximo ciclo.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Erro ao salvar");
    }
  };

  const saveMode = async (mode: string) => {
    try {
      const res = await api.setAccountMode(mode);
      setAccountMode(res.mode);
      setMessage(res.message);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Erro ao alterar modo");
    }
  };

  if (loading || !settings) {
    return <p className="text-slate-400">Carregando configurações...</p>;
  }

  const risk = (settings.risk ?? {}) as Record<string, unknown>;
  const scanner = (settings.scanner ?? {}) as Record<string, unknown>;
  const screener = (scanner.screener ?? {}) as Record<string, unknown>;
  const quality = (scanner.quality ?? {}) as Record<string, unknown>;
  const imba = (settings.imba ?? {}) as Record<string, unknown>;
  const learning = (settings.learning ?? {}) as Record<string, unknown>;
  const timeframes = (settings.timeframes ?? {}) as Record<string, unknown>;
  const display = (settings.display ?? {}) as Record<string, unknown>;

  return (
    <div className="space-y-6">
      {message && (
        <div className="rounded-lg border border-surface-border bg-surface-raised px-4 py-3 text-sm text-slate-300">
          {message}
        </div>
      )}

      <div className="flex justify-end">
        <Button onClick={save}>Salvar configurações</Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Modo da conta (requer restart)</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {(["testnet", "demo", "live"] as const).map((mode) => (
            <Button
              key={mode}
              variant={accountMode === mode ? "default" : "outline"}
              onClick={() => saveMode(mode)}
            >
              {accountModeLabel(mode)}
            </Button>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Risco</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          <Field label="Risco por trade (%)" value={risk.risk_per_trade_pct} type="number" onChange={(v) => patch(["risk", "risk_per_trade_pct"], v)} />
          <Field label="Posição máxima (%)" value={risk.max_position_pct} type="number" onChange={(v) => patch(["risk", "max_position_pct"], v)} />
          <Field label="Trades simultâneos" value={risk.max_concurrent_trades} type="number" onChange={(v) => patch(["risk", "max_concurrent_trades"], v)} />
          <Field label="Risco portfolio (%)" value={risk.max_portfolio_risk_pct} type="number" onChange={(v) => patch(["risk", "max_portfolio_risk_pct"], v)} />
          <Field label="Alavancagem mín." value={risk.min_leverage} type="number" onChange={(v) => patch(["risk", "min_leverage"], v)} />
          <Field label="Alavancagem máx." value={risk.max_leverage} type="number" onChange={(v) => patch(["risk", "max_leverage"], v)} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Scanner</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          <Field label="Scanner ativo" value={scanner.enabled} type="boolean" onChange={(v) => patch(["scanner", "enabled"], v)} />
          <Field label="Intervalo (s)" value={scanner.interval_seconds} type="number" onChange={(v) => patch(["scanner", "interval_seconds"], v)} />
          <Field label="Batch size" value={scanner.scan_batch_size} type="number" onChange={(v) => patch(["scanner", "scan_batch_size"], v)} />
          <Field label="Concorrência" value={scanner.scan_concurrency} type="number" onChange={(v) => patch(["scanner", "scan_concurrency"], v)} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Screener</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          <Field label="Screener ativo" value={screener.enabled} type="boolean" onChange={(v) => patch(["scanner", "screener", "enabled"], v)} />
          <Field label="Volume 24h mín. (USD)" value={screener.min_turnover_24h_usd} type="number" onChange={(v) => patch(["scanner", "screener", "min_turnover_24h_usd"], v)} />
          <Field label="Máx. candidatos" value={screener.max_candidates} type="number" onChange={(v) => patch(["scanner", "screener", "max_candidates"], v)} />
          <Field label="Modo" value={screener.mode} onChange={(v) => patch(["scanner", "screener", "mode"], v)} />
          <Field label="Timeframes" value={screener.timeframes} type="string[]" onChange={(v) => patch(["scanner", "screener", "timeframes"], v)} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Qualidade do scanner</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          <Field label="Conf. IMBA mín." value={quality.min_imba_confidence} type="number" onChange={(v) => patch(["scanner", "quality", "min_imba_confidence"], v)} />
          <Field label="Conf. combinada mín." value={quality.min_combined_confidence} type="number" onChange={(v) => patch(["scanner", "quality", "min_combined_confidence"], v)} />
          <Field label="Confluência mín." value={quality.min_confluence_score} type="number" onChange={(v) => patch(["scanner", "quality", "min_confluence_score"], v)} />
          <Field label="Kalman alinhado" value={quality.require_kalman_align} type="boolean" onChange={(v) => patch(["scanner", "quality", "require_kalman_align"], v)} />
          <Field label="Padrão de mercado" value={quality.require_market_pattern} type="boolean" onChange={(v) => patch(["scanner", "quality", "require_market_pattern"], v)} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>IMBA</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          <Field label="Sensibilidade" value={imba.sensitivity} type="number" onChange={(v) => patch(["imba", "sensitivity"], v)} />
          <Field label="Usar Fib" value={imba.use_fib_levels} type="boolean" onChange={(v) => patch(["imba", "use_fib_levels"], v)} />
          <Field label="Fib lookback" value={imba.fib_lookback} type="number" onChange={(v) => patch(["imba", "fib_lookback"], v)} />
          <Field label="TF estrutura Fib" value={imba.fib_structure_timeframe} onChange={(v) => patch(["imba", "fib_structure_timeframe"], v)} />
          <Field label="HTF confirm mín." value={imba.min_htf_confirm} type="number" onChange={(v) => patch(["imba", "min_htf_confirm"], v)} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Aprendizado</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          <Field label="Learning ativo" value={learning.enabled} type="boolean" onChange={(v) => patch(["learning", "enabled"], v)} />
          <Field label="Log rejeições" value={learning.log_rejections} type="boolean" onChange={(v) => patch(["learning", "log_rejections"], v)} />
          <Field label="Amostras mín. padrão" value={learning.min_pattern_samples} type="number" onChange={(v) => patch(["learning", "min_pattern_samples"], v)} />
          <Field label="Win rate ruim (%)" value={learning.bad_pattern_winrate_pct} type="number" onChange={(v) => patch(["learning", "bad_pattern_winrate_pct"], v)} />
          <Field label="Win rate bom (%)" value={learning.good_pattern_winrate_pct} type="number" onChange={(v) => patch(["learning", "good_pattern_winrate_pct"], v)} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Timeframes</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          <Field label="Primário" value={timeframes.primary} onChange={(v) => patch(["timeframes", "primary"], v)} />
          <Field label="Tendência" value={timeframes.trend} onChange={(v) => patch(["timeframes", "trend"], v)} />
          <Field label="Execução" value={timeframes.execution} onChange={(v) => patch(["timeframes", "execution"], v)} />
          <Field label="Análise" value={timeframes.analysis} type="string[]" onChange={(v) => patch(["timeframes", "analysis"], v)} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Exibição (dashboard)</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          <Field
            label="UTC offset (horas)"
            value={display.utc_offset_hours ?? -3}
            type="number"
            onChange={(v) => patch(["display", "utc_offset_hours"], v)}
          />
          <p className="text-xs text-slate-500 md:col-span-2">
            Horários do gráfico de Análise e timestamps das rejeições. Ex: -3 (Brasília), 0 (UTC), +1 (Lisboa).
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Geral</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          <Field label="OHLCV limit" value={settings.ohlcv_limit} type="number" onChange={(v) => patch(["ohlcv_limit"], v)} />
          <Field label="Log level" value={settings.log_level} onChange={(v) => patch(["log_level"], v)} />
        </CardContent>
      </Card>
    </div>
  );
}
