import { useCallback, useEffect, useState } from "react";
import { Plus, RefreshCw, Trash2, Radar } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { Input } from "@/components/ui/Input";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { DataTable } from "@/components/ui/DataTable";
import { api, type BreakoutPayload } from "@/api/client";

export function WatchlistPage() {
  const [symbols, setSymbols] = useState<string[]>([]);
  const [newSymbol, setNewSymbol] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [breakout, setBreakout] = useState<BreakoutPayload | null>(null);
  const [loadingBreakout, setLoadingBreakout] = useState(false);

  const load = useCallback(() => {
    api.watchlist().then((r) => setSymbols(r.symbols)).catch(() => setSymbols([]));
  }, []);

  const loadBreakout = useCallback(() => {
    setLoadingBreakout(true);
    api
      .breakoutOutlook(30)
      .then(setBreakout)
      .catch(() => setBreakout(null))
      .finally(() => setLoadingBreakout(false));
  }, []);

  useEffect(() => {
    load();
    loadBreakout();
  }, [load, loadBreakout]);

  const save = async (next: string[]) => {
    try {
      const res = await api.saveWatchlist(next);
      setSymbols(res.symbols);
      setMessage("Watchlist atualizada.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Erro ao salvar");
    }
  };

  const add = () => {
    const sym = newSymbol.trim().toUpperCase();
    if (!sym || symbols.includes(sym)) return;
    setNewSymbol("");
    void save([...symbols, sym]);
  };

  const remove = (sym: string) => {
    void save(symbols.filter((s) => s !== sym));
  };

  return (
    <div className="space-y-8">
      <PageHeader
        title="Watchlist"
        description="Pares monitorados pelo scanner autônomo e probabilidade de breakout."
        badge={<Badge variant="brand">{symbols.length} ativos</Badge>}
        actions={
          <Button variant="outline" size="sm" onClick={loadBreakout} disabled={loadingBreakout}>
            <RefreshCw className={`h-4 w-4 ${loadingBreakout ? "animate-spin" : ""}`} />
            Atualizar outlook
          </Button>
        }
      />

      {message && <Alert variant="success">{message}</Alert>}

      <div className="grid gap-6 lg:grid-cols-12">
        <Card className="lg:col-span-4">
          <CardHeader>
            <CardTitle>Adicionar par</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input
              label="Símbolo"
              value={newSymbol}
              onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === "Enter" && add()}
              placeholder="BTC, ETH, SOL..."
            />
            <Button onClick={add} className="w-full">
              <Plus className="h-4 w-4" />
              Adicionar à watchlist
            </Button>
          </CardContent>
        </Card>

        <Card className="lg:col-span-8">
          <CardHeader>
            <CardTitle>Símbolos ativos</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {symbols.map((sym) => (
                <span
                  key={sym}
                  className="inline-flex items-center gap-2 rounded-lg border border-surface-border bg-void/50 px-3 py-2 font-mono text-sm text-slate-200"
                >
                  {sym}
                  <button
                    type="button"
                    onClick={() => remove(sym)}
                    className="text-slate-500 transition hover:text-loss"
                    aria-label={`Remover ${sym}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </span>
              ))}
              {!symbols.length && (
                <p className="text-sm text-slate-500">Nenhum símbolo na watchlist</p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Radar className="h-4 w-4 text-brand" />
            Breakout probability · {breakout?.timeframe ?? "5m"}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {breakout?.error && <Alert variant="error" className="mb-4">{breakout.error}</Alert>}
          <DataTable
            data={breakout?.outlooks ?? []}
            keyFn={(row) => row.symbol}
            emptyMessage={loadingBreakout ? "Calculando probabilidades..." : "Sem dados de breakout"}
            columns={[
              {
                key: "symbol",
                header: "Par",
                cell: (row) => <span className="font-semibold text-white">{row.symbol}</span>,
              },
              {
                key: "bias",
                header: "Bias",
                cell: (row) =>
                  row.error ? (
                    <span className="text-loss">{row.error}</span>
                  ) : (
                    <Badge variant={row.bias === "BULLISH" ? "profit" : "loss"}>{row.bias}</Badge>
                  ),
              },
              {
                key: "prob",
                header: "Prob.",
                className: "font-mono tabular-nums",
                cell: (row) => (
                  <span className={row.meets_threshold ? "font-semibold text-brand" : "text-slate-400"}>
                    {row.probability_pct?.toFixed(1)}%
                  </span>
                ),
              },
              {
                key: "high",
                header: "High",
                className: "font-mono tabular-nums text-slate-500",
                cell: (row) => `${row.prob_high_pct?.toFixed(1)}%`,
              },
              {
                key: "low",
                header: "Low",
                className: "font-mono tabular-nums text-slate-500",
                cell: (row) => `${row.prob_low_pct?.toFixed(1)}%`,
              },
              {
                key: "prev",
                header: "Prev",
                className: "text-slate-500",
                cell: (row) => row.prev_candle,
              },
            ]}
          />
          {breakout?.updated_at && (
            <p className="mt-4 font-mono text-xs tabular-nums text-slate-600">
              Atualizado {new Date(breakout.updated_at).toLocaleString()} · mín. {breakout.min_probability_pct}%
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
