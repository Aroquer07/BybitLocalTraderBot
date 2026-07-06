import { useCallback, useEffect, useState } from "react";
import { Wallet } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { api, type AccountInfo } from "@/api/client";
import { accountModeLabel } from "@/lib/strategyPattern";
import { formatNumber } from "@/lib/utils";

function formatBalance(value: number) {
  return `$${formatNumber(value)}`;
}

export function AccountBalance() {
  const [account, setAccount] = useState<AccountInfo | null>(null);

  const load = useCallback(() => {
    api.account().then(setAccount).catch(() => setAccount(null));
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, [load]);

  const modeClass =
    account?.mode === "live"
      ? "text-rose-300"
      : account?.mode === "demo"
        ? "text-amber-300"
        : "text-cyan-300";

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2">
          <Wallet className="h-4 w-4 text-accent" />
          Conta Bybit
        </CardTitle>
        <span className={`rounded-full bg-black/30 px-2.5 py-1 text-xs font-semibold ${modeClass}`}>
          {account ? accountModeLabel(account.mode) : "—"}
        </span>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-3">
        <div>
          <div className="text-xs text-slate-500">Saldo disponível</div>
          <div className="text-2xl font-semibold text-white">
            {account?.balance_usdt != null ? formatBalance(account.balance_usdt) : "—"}
          </div>
        </div>
        <div>
          <div className="text-xs text-slate-500">Total USDT</div>
          <div className="text-lg text-slate-200">
            {account?.total_usdt != null ? formatBalance(account.total_usdt) : "—"}
          </div>
        </div>
        <div>
          <div className="text-xs text-slate-500">Em uso</div>
          <div className="text-lg text-slate-200">
            {account?.used_usdt != null ? formatBalance(account.used_usdt) : "—"}
          </div>
        </div>
        {account?.error && (
          <p className="sm:col-span-3 text-xs text-amber-400/90">
            Não foi possível buscar saldo: {account.error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
