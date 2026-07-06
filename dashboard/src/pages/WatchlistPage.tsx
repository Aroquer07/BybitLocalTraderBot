import { useCallback, useEffect, useState } from "react";
import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
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
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Watchlist</h1>
        <p className="mt-1 text-sm text-slate-400">
          Moedas monitoradas pelo scanner ({symbols.length})
        </p>
      </div>

      {message && (
        <div className="rounded-lg border border-surface-border bg-surface-raised px-4 py-3 text-sm">
          {message}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Adicionar símbolo</CardTitle>
        </CardHeader>
        <CardContent className="flex gap-2">
          <input
            value={newSymbol}
            onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === "Enter" && add()}
            placeholder="Ex: BTC, ETH, SOL"
            className="flex-1 rounded-lg border border-surface-border bg-black/30 px-3 py-2 text-sm text-white"
          />
          <Button onClick={add}>
            <Plus className="h-4 w-4" />
            Adicionar
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2">
          <CardTitle>Breakout Probability ({breakout?.timeframe ?? "5m"})</CardTitle>
          <Button variant="outline" size="sm" onClick={loadBreakout} disabled={loadingBreakout}>
            <RefreshCw className={`h-4 w-4 ${loadingBreakout ? "animate-spin" : ""}`} />
            Atualizar
          </Button>
        </CardHeader>
        <CardContent>
          {breakout?.error && (
            <p className="mb-3 text-sm text-rose-400">{breakout.error}</p>
          )}
          {!breakout?.outlooks?.length ? (
            <p className="text-sm text-slate-500">
              {loadingBreakout ? "Calculando probabilidades..." : "Sem dados de breakout"}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-sm">
                <thead>
                  <tr className="border-b border-surface-border text-xs uppercase text-slate-500">
                    <th className="py-2 pr-3">Símbolo</th>
                    <th className="py-2 pr-3">Bias</th>
                    <th className="py-2 pr-3">Prob</th>
                    <th className="py-2 pr-3">High</th>
                    <th className="py-2 pr-3">Low</th>
                    <th className="py-2 pr-3">Prev</th>
                  </tr>
                </thead>
                <tbody>
                  {breakout.outlooks.map((row) => (
                    <tr key={row.symbol} className="border-b border-surface-border/50">
                      <td className="py-2 pr-3 font-medium text-white">{row.symbol}</td>
                      {row.error ? (
                        <td colSpan={5} className="py-2 text-rose-400">
                          {row.error}
                        </td>
                      ) : (
                        <>
                          <td
                            className={`py-2 pr-3 ${
                              row.bias === "BULLISH" ? "text-emerald-400" : "text-rose-400"
                            }`}
                          >
                            {row.bias}
                          </td>
                          <td
                            className={`py-2 pr-3 ${
                              row.meets_threshold ? "text-violet-300" : "text-slate-400"
                            }`}
                          >
                            {row.probability_pct?.toFixed(1)}%
                          </td>
                          <td className="py-2 pr-3 text-slate-400">
                            {row.prob_high_pct?.toFixed(1)}%
                          </td>
                          <td className="py-2 pr-3 text-slate-400">
                            {row.prob_low_pct?.toFixed(1)}%
                          </td>
                          <td className="py-2 pr-3 text-slate-400">{row.prev_candle}</td>
                        </>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {breakout?.updated_at && (
            <p className="mt-3 text-xs text-slate-600">
              Atualizado {new Date(breakout.updated_at).toLocaleString()} · mín{" "}
              {breakout.min_probability_pct}%
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Símbolos ativos</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2">
            {symbols.map((sym) => (
              <span
                key={sym}
                className="inline-flex items-center gap-2 rounded-lg border border-surface-border bg-black/25 px-3 py-1.5 text-sm text-slate-200"
              >
                {sym}
                <button
                  type="button"
                  onClick={() => remove(sym)}
                  className="text-slate-500 hover:text-rose-400"
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
  );
}
