import { useCallback, useEffect, useState } from "react";
import { Wallet } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { api, type AccountInfo } from "@/api/client";
import { accountModeLabel } from "@/lib/strategyPattern";
import { formatNumber } from "@/lib/utils";

function formatBalance(value: number) {
  return `$${formatNumber(value)}`;
}

function modeBadge(mode: string): "loss" | "warn" | "brand" {
  if (mode === "live") return "loss";
  if (mode === "demo") return "warn";
  return "brand";
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

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2">
          <Wallet className="h-4 w-4 text-brand" />
          Conta Bybit
        </CardTitle>
        <Badge variant={account ? modeBadge(account.mode) : "neutral"}>
          {account ? accountModeLabel(account.mode) : "—"}
        </Badge>
      </CardHeader>
      <CardContent>
        <div className="grid gap-6 sm:grid-cols-3">
          <div>
            <div className="data-label">Disponível</div>
            <div className="data-value mt-2">
              {account?.balance_usdt != null ? formatBalance(account.balance_usdt) : "—"}
            </div>
          </div>
          <div>
            <div className="data-label">Total USDT</div>
            <div className="mt-2 font-mono text-lg font-semibold tabular-nums text-slate-200">
              {account?.total_usdt != null ? formatBalance(account.total_usdt) : "—"}
            </div>
          </div>
          <div>
            <div className="data-label">Em uso</div>
            <div className="mt-2 font-mono text-lg font-semibold tabular-nums text-slate-200">
              {account?.used_usdt != null ? formatBalance(account.used_usdt) : "—"}
            </div>
          </div>
        </div>
        {account?.error && (
          <p className="mt-4 text-xs text-warn">Não foi possível buscar saldo: {account.error}</p>
        )}
      </CardContent>
    </Card>
  );
}
