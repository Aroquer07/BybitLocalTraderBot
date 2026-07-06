"""Análise profunda dos dados já extraídos."""
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
closed = json.loads((ROOT / "data/audit/closed_pnl.json").read_text())
tx = json.loads((ROOT / "data/audit/transaction_log.json").read_text())
execs = json.loads((ROOT / "data/audit/executions.json").read_text())

open_fees = sum(float(r.get("openFee") or 0) for r in closed)
close_fees = sum(float(r.get("closeFee") or 0) for r in closed)
pnl_fees = open_fees + close_fees
trade_fees = sum(float(r.get("fee") or 0) for r in tx if r.get("type") == "TRADE")
settlement = [r for r in tx if r.get("type") == "SETTLEMENT"]
fund_net = sum(float(r.get("change") or 0) for r in settlement)
exec_fees = sum(abs(float(e.get("execFee") or 0)) for e in execs)
total_pnl = sum(float(r.get("closedPnl") or 0) for r in closed)

losses = sorted(
    [
        (
            float(r["closedPnl"]),
            r["symbol"],
            r.get("avgEntryPrice"),
            r.get("avgExitPrice"),
            r.get("leverage"),
            r.get("closedSize"),
            float(r.get("openFee") or 0) + float(r.get("closeFee") or 0),
        )
        for r in closed
        if float(r.get("closedPnl") or 0) < 0
    ]
)

# Group by symbol + createdTime window (same position)
by_order = defaultdict(list)
for r in closed:
    by_order[r.get("orderId")].append(r)

# Better grouping: symbol + side + avgEntryPrice (rounded)
groups = defaultdict(list)
for r in closed:
    key = (r["symbol"], r.get("side"), round(float(r.get("avgEntryPrice") or 0), 8))
    groups[key].append(r)

trade_pnls = [sum(float(x["closedPnl"]) for x in recs) for recs in groups.values()]
tw = sum(1 for p in trade_pnls if p > 0)
tl = sum(1 for p in trade_pnls if p < 0)
avg_w = sum(p for p in trade_pnls if p > 0) / tw if tw else 0
avg_l = sum(p for p in trade_pnls if p < 0) / tl if tl else 0
gw = sum(p for p in trade_pnls if p > 0)
gl = abs(sum(p for p in trade_pnls if p < 0))
pf = gw / gl if gl else 0

# Slippage only on stop orders (stopOrderType != UNKNOWN)
stops = [
    e for e in execs
    if str(e.get("stopOrderType") or "").upper() not in ("", "UNKNOWN")
]
stop_slip = []
for e in stops:
    op, ep = float(e.get("orderPrice") or 0), float(e.get("execPrice") or 0)
    if op > 0 and ep > 0:
        stop_slip.append(abs(ep - op) / op * 100)

liq = [r for r in tx if r.get("type") == "LIQUIDATION"]

out = {
    "fees_closed_pnl": pnl_fees,
    "fees_tx_trade": trade_fees,
    "fees_exec": exec_fees,
    "funding_net": fund_net,
    "funding_abs": sum(abs(float(r.get("change") or 0)) for r in settlement),
    "total_pnl": total_pnl,
    "pnl_before_fees_est": total_pnl + pnl_fees,
    "fee_pct_of_loss": pnl_fees / abs(total_pnl) * 100 if total_pnl else 0,
    "logical_trades": len(trade_pnls),
    "logical_wins": tw,
    "logical_losses": tl,
    "logical_wr": tw / (tw + tl) * 100 if tw + tl else 0,
    "logical_avg_win": avg_w,
    "logical_avg_loss": avg_l,
    "logical_pf": pf,
    "logical_total_pnl": sum(trade_pnls),
    "stop_slippage_avg": statistics.mean(stop_slip) if stop_slip else 0,
    "stop_slippage_median": statistics.median(stop_slip) if stop_slip else 0,
    "stop_count": len(stops),
    "top_losses": [
        {"pnl": l[0], "symbol": l[1], "entry": l[2], "exit": l[3], "lev": l[4], "fees": l[6]}
        for l in losses[:10]
    ],
    "liquidation": liq,
}
print(json.dumps(out, indent=2))
