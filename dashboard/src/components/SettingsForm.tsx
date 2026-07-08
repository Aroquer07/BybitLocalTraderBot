import { useCallback, useEffect, useState } from "react";
import { Save } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/Card";
import { Alert } from "@/components/ui/Alert";
import { Input } from "@/components/ui/Input";
import { Switch } from "@/components/ui/Switch";
import { Tabs } from "@/components/ui/Tabs";
import { api } from "@/api/client";
import { accountModeLabel } from "@/lib/strategyPattern";

type FieldProps = {
  label: string;
  value: unknown;
  onChange: (value: unknown) => void;
  type?: "number" | "text" | "boolean" | "string[]";
  hint?: string;
};

function Field({ label, value, onChange, type = "text", hint }: FieldProps) {
  if (type === "boolean") {
    return (
      <Switch label={label} description={hint} checked={Boolean(value)} onChange={(v) => onChange(v)} />
    );
  }
  if (type === "number") {
    return (
      <Input
        label={label}
        hint={hint}
        type="number"
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(e) => onChange(e.target.value === "" ? 0 : Number(e.target.value))}
      />
    );
  }
  if (type === "string[]") {
    const arr = Array.isArray(value) ? (value as string[]) : [];
    return (
      <Input
        label={label}
        hint={hint ?? "Separar por vírgula"}
        value={arr.join(", ")}
        onChange={(e) =>
          onChange(
            e.target.value
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean),
          )
        }
      />
    );
  }
  return (
    <Input
      label={label}
      hint={hint}
      value={value === undefined || value === null ? "" : String(value)}
      onChange={(e) => onChange(e.target.value)}
    />
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

type SettingsTab = "account" | "risk" | "scanner" | "imba" | "learning" | "display";

export function SettingsForm() {
  const [settings, setSettings] = useState<Record<string, unknown> | null>(null);
  const [accountMode, setAccountMode] = useState("demo");
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<SettingsTab>("account");

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
    return (
      <div className="flex min-h-[30vh] items-center justify-center text-slate-500">
        Carregando configurações...
      </div>
    );
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
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <Tabs
          tabs={[
            { id: "account", label: "Conta" },
            { id: "risk", label: "Risco" },
            { id: "scanner", label: "Scanner" },
            { id: "imba", label: "IMBA" },
            { id: "learning", label: "Learning" },
            { id: "display", label: "Display" },
          ]}
          active={tab}
          onChange={(id) => setTab(id as SettingsTab)}
          className="flex-1"
        />
        <Button onClick={save}>
          <Save className="h-4 w-4" />
          Salvar
        </Button>
      </div>

      {message && <Alert variant="success">{message}</Alert>}

      {tab === "account" && (
        <Card>
          <CardHeader>
            <CardTitle>Modo da conta</CardTitle>
            <CardDescription>Requer restart do bot após alteração</CardDescription>
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
      )}

      {tab === "risk" && (
        <Card>
          <CardHeader>
            <CardTitle>Risco</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            <Field label="Risco por trade (%)" value={risk.risk_per_trade_pct} type="number" onChange={(v) => patch(["risk", "risk_per_trade_pct"], v)} />
            <Field label="Posição máxima (%)" value={risk.max_position_pct} type="number" onChange={(v) => patch(["risk", "max_position_pct"], v)} />
            <Field label="Trades simultâneos" value={risk.max_concurrent_trades} type="number" onChange={(v) => patch(["risk", "max_concurrent_trades"], v)} />
            <Field label="Risco portfolio (%)" value={risk.max_portfolio_risk_pct} type="number" onChange={(v) => patch(["risk", "max_portfolio_risk_pct"], v)} />
            <Field label="Alavancagem mín." value={risk.min_leverage} type="number" onChange={(v) => patch(["risk", "min_leverage"], v)} />
            <Field label="Alavancagem máx." value={risk.max_leverage} type="number" onChange={(v) => patch(["risk", "max_leverage"], v)} />
          </CardContent>
        </Card>
      )}

      {tab === "scanner" && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Scanner</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4">
              <Field label="Scanner ativo" value={scanner.enabled} type="boolean" onChange={(v) => patch(["scanner", "enabled"], v)} />
              <Field label="Intervalo (s)" value={scanner.interval_seconds} type="number" onChange={(v) => patch(["scanner", "interval_seconds"], v)} />
              <Field label="Batch size" value={scanner.scan_batch_size} type="number" onChange={(v) => patch(["scanner", "scan_batch_size"], v)} />
              <Field label="Concorrência" value={scanner.scan_concurrency} type="number" onChange={(v) => patch(["scanner", "scan_concurrency"], v)} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Screener & qualidade</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4">
              <Field label="Screener ativo" value={screener.enabled} type="boolean" onChange={(v) => patch(["scanner", "screener", "enabled"], v)} />
              <Field label="Volume 24h mín. (USD)" value={screener.min_turnover_24h_usd} type="number" onChange={(v) => patch(["scanner", "screener", "min_turnover_24h_usd"], v)} />
              <Field label="Máx. candidatos" value={screener.max_candidates} type="number" onChange={(v) => patch(["scanner", "screener", "max_candidates"], v)} />
              <Field label="Modo screener" value={screener.mode} onChange={(v) => patch(["scanner", "screener", "mode"], v)} />
              <Field label="Timeframes screener" value={screener.timeframes} type="string[]" onChange={(v) => patch(["scanner", "screener", "timeframes"], v)} />
              <Field label="Conf. IMBA mín." value={quality.min_imba_confidence} type="number" onChange={(v) => patch(["scanner", "quality", "min_imba_confidence"], v)} />
              <Field label="Conf. combinada mín." value={quality.min_combined_confidence} type="number" onChange={(v) => patch(["scanner", "quality", "min_combined_confidence"], v)} />
              <Field label="Confluência mín." value={quality.min_confluence_score} type="number" onChange={(v) => patch(["scanner", "quality", "min_confluence_score"], v)} />
              <Field label="Kalman alinhado" value={quality.require_kalman_align} type="boolean" onChange={(v) => patch(["scanner", "quality", "require_kalman_align"], v)} />
              <Field label="Padrão de mercado" value={quality.require_market_pattern} type="boolean" onChange={(v) => patch(["scanner", "quality", "require_market_pattern"], v)} />
            </CardContent>
          </Card>
        </div>
      )}

      {tab === "imba" && (
        <Card>
          <CardHeader>
            <CardTitle>IMBA & timeframes</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            <Field label="Sensibilidade" value={imba.sensitivity} type="number" onChange={(v) => patch(["imba", "sensitivity"], v)} />
            <Field label="Usar Fib" value={imba.use_fib_levels} type="boolean" onChange={(v) => patch(["imba", "use_fib_levels"], v)} />
            <Field label="Fib lookback" value={imba.fib_lookback} type="number" onChange={(v) => patch(["imba", "fib_lookback"], v)} />
            <Field label="TF estrutura Fib" value={imba.fib_structure_timeframe} onChange={(v) => patch(["imba", "fib_structure_timeframe"], v)} />
            <Field label="HTF confirm mín." value={imba.min_htf_confirm} type="number" onChange={(v) => patch(["imba", "min_htf_confirm"], v)} />
            <Field label="TF primário" value={timeframes.primary} onChange={(v) => patch(["timeframes", "primary"], v)} />
            <Field label="TF tendência" value={timeframes.trend} onChange={(v) => patch(["timeframes", "trend"], v)} />
            <Field label="TF execução" value={timeframes.execution} onChange={(v) => patch(["timeframes", "execution"], v)} />
            <Field label="TF análise" value={timeframes.analysis} type="string[]" onChange={(v) => patch(["timeframes", "analysis"], v)} />
          </CardContent>
        </Card>
      )}

      {tab === "learning" && (
        <Card>
          <CardHeader>
            <CardTitle>Aprendizado</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            <Field label="Learning ativo" value={learning.enabled} type="boolean" onChange={(v) => patch(["learning", "enabled"], v)} />
            <Field label="Log rejeições" value={learning.log_rejections} type="boolean" onChange={(v) => patch(["learning", "log_rejections"], v)} />
            <Field label="Amostras mín. padrão" value={learning.min_pattern_samples} type="number" onChange={(v) => patch(["learning", "min_pattern_samples"], v)} />
            <Field label="Win rate ruim (%)" value={learning.bad_pattern_winrate_pct} type="number" onChange={(v) => patch(["learning", "bad_pattern_winrate_pct"], v)} />
            <Field label="Win rate bom (%)" value={learning.good_pattern_winrate_pct} type="number" onChange={(v) => patch(["learning", "good_pattern_winrate_pct"], v)} />
          </CardContent>
        </Card>
      )}

      {tab === "display" && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Exibição</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4">
              <Field
                label="UTC offset (horas)"
                value={display.utc_offset_hours ?? -3}
                type="number"
                hint="Fuso dos gráficos de Análise. Ex: -3 Brasília, 0 UTC"
                onChange={(v) => patch(["display", "utc_offset_hours"], v)}
              />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Geral</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4">
              <Field label="OHLCV limit" value={settings.ohlcv_limit} type="number" onChange={(v) => patch(["ohlcv_limit"], v)} />
              <Field label="Log level" value={settings.log_level} onChange={(v) => patch(["log_level"], v)} />
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
