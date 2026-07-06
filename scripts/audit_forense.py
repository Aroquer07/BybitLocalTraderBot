"""Extração forense de dados Bybit + análise de PnL (script temporário)."""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config.settings import get_settings
from src.models.schemas import StoredTrade, TradeStatus
from src.services.exchange_client import ExchangeClient
from src.services.pnl_reporter import MAX_BYBIT_WINDOW_MS, MS_DAY, period_range_ms
from src.services.runtime_config_store import RuntimeConfigStore
from src.utils.logger import setup_logging

AUDIT_DIR = ROOT / "data" / "audit"
REPORT_PATH = ROOT / "relatorio_auditoria_bot.md"


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _ms_to_iso(ms: int | str | None) -> str:
    if ms is None:
        return ""
    ts = int(ms) / 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


async def _paginate_execution_list(
    exchange,
    start_ms: int,
    end_ms: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    window_start = start_ms
    while window_start < end_ms:
        window_end = min(window_start + MAX_BYBIT_WINDOW_MS, end_ms)
        cursor: str | None = None
        while True:
            req: dict[str, Any] = {
                "category": "linear",
                "startTime": window_start,
                "endTime": window_end,
                "limit": 100,
            }
            if cursor:
                req["cursor"] = cursor
            resp = await exchange.privateGetV5ExecutionList(req)
            result = resp.get("result") or {}
            batch = result.get("list") or []
            records.extend(batch)
            cursor = result.get("nextPageCursor")
            if not cursor or not batch:
                break
        window_start = window_end + 1
    return records


async def _paginate_transaction_log(
    exchange,
    start_ms: int,
    end_ms: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    window_start = start_ms
    while window_start < end_ms:
        window_end = min(window_start + MAX_BYBIT_WINDOW_MS, end_ms)
        cursor: str | None = None
        while True:
            req: dict[str, Any] = {
                "accountType": "UNIFIED",
                "category": "linear",
                "startTime": window_start,
                "endTime": window_end,
                "limit": 50,
            }
            if cursor:
                req["cursor"] = cursor
            try:
                resp = await exchange.privateGetV5AccountTransactionLog(req)
            except Exception:
                req.pop("accountType", None)
                resp = await exchange.privateGetV5AccountTransactionLog(req)
            result = resp.get("result") or {}
            batch = result.get("list") or []
            records.extend(batch)
            cursor = result.get("nextPageCursor")
            if not cursor or not batch:
                break
        window_start = window_end + 1
    return records


def load_journal_trades() -> list[StoredTrade]:
    path = ROOT / "data" / "trades.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [StoredTrade.model_validate(t) for t in raw.get("trades", [])]


def analyze_closed_pnl(records: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [_f(r.get("closedPnl")) for r in records]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    breakeven = [p for p in pnls if p == 0]

    avg_win = statistics.mean(wins) if wins else 0.0
    avg_loss = statistics.mean(losses) if losses else 0.0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float("inf")

    # Drawdown on cumulative closed PnL (sorted by time)
    sorted_recs = sorted(records, key=lambda r: int(r.get("updatedTime") or r.get("createdTime") or 0))
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    equity_curve: list[tuple[int, float]] = []
    for r in sorted_recs:
        cum += _f(r.get("closedPnl"))
        peak = max(peak, cum)
        dd = peak - cum
        max_dd = max(max_dd, dd)
        ts = int(r.get("updatedTime") or r.get("createdTime") or 0)
        equity_curve.append((ts, cum))

    leverages = [_f(r.get("leverage"), 1) for r in records if r.get("leverage")]
    avg_lev = statistics.mean(leverages) if leverages else 0.0

    # R:R realized per trade
    rr_ratios: list[float] = []
    for r in records:
        entry = _f(r.get("avgEntryPrice"))
        exit_p = _f(r.get("avgExitPrice"))
        pnl = _f(r.get("closedPnl"))
        if entry <= 0:
            continue
        move_pct = abs(exit_p - entry) / entry * 100
        if pnl != 0:
            rr_ratios.append(move_pct)

    return {
        "total_records": len(records),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(breakeven),
        "winrate_pct": len(wins) / (len(wins) + len(losses)) * 100 if (wins or losses) else 0,
        "total_pnl": sum(pnls),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "avg_win_loss_ratio": abs(avg_win / avg_loss) if avg_loss else 0,
        "profit_factor": profit_factor,
        "gross_win": gross_win,
        "gross_loss": gross_loss,
        "max_drawdown": max_dd,
        "avg_leverage": avg_lev,
        "median_win": statistics.median(wins) if wins else 0,
        "median_loss": statistics.median(losses) if losses else 0,
        "largest_win": max(wins) if wins else 0,
        "largest_loss": min(losses) if losses else 0,
        "equity_curve": equity_curve,
    }


def analyze_fees(
    executions: list[dict[str, Any]],
    tx_log: list[dict[str, Any]],
) -> dict[str, Any]:
    trading_fees_exec = sum(abs(_f(e.get("execFee"))) for e in executions)
    funding_fees = 0.0
    trading_fees_ledger = 0.0
    realized_pnl_ledger = 0.0
    liquidation_events: list[dict[str, Any]] = []
    adl_events: list[dict[str, Any]] = []

    for row in tx_log:
        t = str(row.get("type") or row.get("transactionType") or "").upper()
        change = _f(row.get("change") or row.get("cashFlow") or row.get("amount"))
        fee = abs(_f(row.get("fee")))
        if "FUNDING" in t:
            funding_fees += abs(change) if change < 0 else fee
        elif "TRADE" in t or "FEE" in t or "COMMISSION" in t:
            if change < 0:
                trading_fees_ledger += abs(change)
        elif "REALISED" in t or "REALIZED" in t:
            realized_pnl_ledger += change
        elif "LIQUIDATION" in t or "BUST" in t:
            liquidation_events.append(row)
        elif "ADL" in t or "AUTO_DELEVERAGING" in t:
            adl_events.append(row)

    total_trading_fees = max(trading_fees_exec, trading_fees_ledger)

    return {
        "trading_fees_executions": trading_fees_exec,
        "trading_fees_ledger": trading_fees_ledger,
        "funding_fees": funding_fees,
        "total_fees": total_trading_fees + funding_fees,
        "realized_pnl_ledger": realized_pnl_ledger,
        "liquidation_events": liquidation_events,
        "adl_events": adl_events,
        "tx_types": dict(
            sorted(
                defaultdict(int, {str(r.get("type") or "?"): 0 for r in tx_log}).items()
            )
        ),
    }


def _count_tx_types(tx_log: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in tx_log:
        t = str(row.get("type") or row.get("transactionType") or "UNKNOWN")
        counts[t] += 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


def analyze_executions(executions: list[dict[str, Any]]) -> dict[str, Any]:
    slippage_samples: list[dict[str, Any]] = []
    stop_executions: list[dict[str, Any]] = []
    tp_executions: list[dict[str, Any]] = []
    entry_executions: list[dict[str, Any]] = []

    for e in executions:
        order_price = _f(e.get("orderPrice"))
        exec_price = _f(e.get("execPrice"))
        mark_price = _f(e.get("markPrice"))
        stop_type = str(e.get("stopOrderType") or "")
        order_type = str(e.get("orderType") or "")
        side = str(e.get("side") or "")
        symbol = str(e.get("symbol") or "")
        exec_time = int(e.get("execTime") or 0)
        fee = abs(_f(e.get("execFee")))
        qty = _f(e.get("execQty"))

        slippage_pct = 0.0
        if order_price > 0 and exec_price > 0:
            slippage_pct = abs(exec_price - order_price) / order_price * 100

        sample = {
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "stop_type": stop_type,
            "order_price": order_price,
            "exec_price": exec_price,
            "mark_price": mark_price,
            "slippage_pct": slippage_pct,
            "exec_time": exec_time,
            "fee": fee,
            "qty": qty,
            "is_maker": e.get("isMaker"),
        }

        if slippage_pct > 0.01:
            slippage_samples.append(sample)

        st_upper = stop_type.upper()
        if "STOP" in st_upper or "SL" in st_upper or stop_type not in ("", "UNKNOWN"):
            if "TAKE" in st_upper or "TP" in st_upper:
                tp_executions.append(sample)
            elif "STOP" in st_upper or "SL" in st_upper or "TRAILING" in st_upper:
                stop_executions.append(sample)
        elif order_type.upper() == "MARKET" and qty > 0:
            entry_executions.append(sample)

    stop_slippages = [s["slippage_pct"] for s in stop_executions if s["slippage_pct"] > 0]
    all_slippages = [
        abs(_f(e.get("execPrice")) - _f(e.get("orderPrice"))) / _f(e.get("orderPrice")) * 100
        for e in executions
        if _f(e.get("orderPrice")) > 0 and _f(e.get("execPrice")) > 0
    ]

    return {
        "total_executions": len(executions),
        "stop_executions": len(stop_executions),
        "tp_executions": len(tp_executions),
        "entry_executions": len(entry_executions),
        "avg_slippage_pct": statistics.mean(all_slippages) if all_slippages else 0,
        "max_slippage_pct": max(all_slippages) if all_slippages else 0,
        "avg_stop_slippage_pct": statistics.mean(stop_slippages) if stop_slippages else 0,
        "worst_slippage": sorted(slippage_samples, key=lambda x: -x["slippage_pct"])[:15],
        "worst_stops": sorted(stop_executions, key=lambda x: -x["slippage_pct"])[:15],
        "total_exec_fees": sum(abs(_f(e.get("execFee"))) for e in executions),
    }


def analyze_journal_vs_api(
    journal_closed: list[StoredTrade],
    closed_pnl: list[dict[str, Any]],
    executions: list[dict[str, Any]],
) -> dict[str, Any]:
    journal_pnl = 0.0
    journal_wins = journal_losses = 0
    rr_planned: list[float] = []
    sl_dist_pcts: list[float] = []
    tp1_rr_planned: list[float] = []

    for t in journal_closed:
        if t.pnl_pct and t.pnl_pct > 0:
            journal_wins += 1
        else:
            journal_losses += 1
        if t.amount and t.exit_price:
            if t.direction.value == "LONG":
                pnl = (t.exit_price - t.entry_price) * t.amount
            else:
                pnl = (t.entry_price - t.exit_price) * t.amount
            journal_pnl += pnl

        sl_dist = abs(t.entry_price - t.stop_loss)
        if sl_dist > 0 and t.take_profits:
            tp1_dist = abs(t.take_profits[0] - t.entry_price)
            rr = tp1_dist / sl_dist
            tp1_rr_planned.append(rr)
            sl_dist_pcts.append(sl_dist / t.entry_price * 100)
            if t.exit_price:
                actual_move = abs(t.exit_price - t.entry_price)
                rr_planned.append(actual_move / sl_dist)

    # Group closed PnL by symbol for rough matching
    api_by_symbol: dict[str, list[dict]] = defaultdict(list)
    for r in closed_pnl:
        sym = str(r.get("symbol") or "").replace("USDT", "/USDT")
        if not sym.endswith("/USDT"):
            sym = sym + "/USDT" if sym else "?"
        api_by_symbol[sym].append(r)

    divergences: list[dict[str, Any]] = []
    for t in journal_closed:
        sym_key = t.symbol.upper()
        api_sym = sym_key.replace("/", "")
        matches = [r for r in closed_pnl if api_sym in str(r.get("symbol", ""))]
        if not matches:
            continue
        # Find closest by entry price
        best = min(matches, key=lambda r: abs(_f(r.get("avgEntryPrice")) - t.entry_price))
        api_pnl = _f(best.get("closedPnl"))
        api_exit = _f(best.get("avgExitPrice"))
        api_entry = _f(best.get("avgEntryPrice"))
        if t.exit_price and api_exit > 0:
            exit_diff_pct = abs(t.exit_price - api_exit) / api_exit * 100
            if exit_diff_pct > 0.5:
                divergences.append({
                    "symbol": t.symbol,
                    "journal_exit": t.exit_price,
                    "api_exit": api_exit,
                    "diff_pct": exit_diff_pct,
                    "journal_sl": t.stop_loss,
                    "close_reason": t.close_reason,
                })

    return {
        "journal_closed": len(journal_closed),
        "journal_wins": journal_wins,
        "journal_losses": journal_losses,
        "journal_estimated_pnl": journal_pnl,
        "avg_planned_tp1_rr": statistics.mean(tp1_rr_planned) if tp1_rr_planned else 0,
        "avg_sl_distance_pct": statistics.mean(sl_dist_pcts) if sl_dist_pcts else 0,
        "median_planned_tp1_rr": statistics.median(tp1_rr_planned) if tp1_rr_planned else 0,
        "divergences": divergences[:20],
        "avg_leverage_journal": statistics.mean([t.leverage for t in journal_closed]) if journal_closed else 0,
    }


def analyze_asymmetry_deep(closed_pnl: list[dict[str, Any]]) -> dict[str, Any]:
    """Analisa se wins são parciais (TP) e losses são full stop."""
    partial_wins = 0
    full_losses = 0
    win_sizes: list[float] = []
    loss_sizes: list[float] = []
    win_qtys: list[float] = []
    loss_qtys: list[float] = []

    for r in closed_pnl:
        pnl = _f(r.get("closedPnl"))
        qty = _f(r.get("closedSize") or r.get("qty"))
        entry = _f(r.get("avgEntryPrice"))
        exit_p = _f(r.get("avgExitPrice"))
        if pnl > 0:
            win_sizes.append(pnl)
            win_qtys.append(qty)
            # Partial close heuristic: small move relative to leverage
            if entry > 0:
                move_pct = abs(exit_p - entry) / entry * 100
                if move_pct < 0.5:
                    partial_wins += 1
        elif pnl < 0:
            loss_sizes.append(pnl)
            loss_qtys.append(qty)
            if entry > 0:
                move_pct = abs(exit_p - entry) / entry * 100
                if move_pct > 0.3:
                    full_losses += 1

    return {
        "partial_wins_heuristic": partial_wins,
        "full_losses_heuristic": full_losses,
        "avg_win_qty": statistics.mean(win_qtys) if win_qtys else 0,
        "avg_loss_qty": statistics.mean(loss_qtys) if loss_qtys else 0,
        "win_qty_loss_qty_ratio": (
            statistics.mean(win_qtys) / statistics.mean(loss_qtys)
            if win_qtys and loss_qtys and statistics.mean(loss_qtys) > 0
            else 0
        ),
    }


def build_report(
    *,
    settings_mode: str,
    start_ms: int,
    end_ms: int,
    pnl_stats: dict[str, Any],
    fee_stats: dict[str, Any],
    exec_stats: dict[str, Any],
    journal_stats: dict[str, Any],
    asym_stats: dict[str, Any],
    tx_type_counts: dict[str, int],
) -> str:
    total_pnl = pnl_stats["total_pnl"]
    total_fees = fee_stats["total_fees"]
    fee_pct = abs(total_fees / total_pnl * 100) if total_pnl != 0 else 0

    # Diagnosis logic
    avg_wl_ratio = pnl_stats["avg_win_loss_ratio"]
    pf = pnl_stats["profit_factor"]
    lethal = []

    if avg_wl_ratio < 1.0 and pnl_stats["winrate_pct"] > 50:
        lethal.append(
            f"**Assimetria R:R invertida**: win rate {pnl_stats['winrate_pct']:.1f}% mas "
            f"Average Win (${pnl_stats['avg_win']:.2f}) < |Average Loss| (${abs(pnl_stats['avg_loss']):.2f}) "
            f"— ratio {avg_wl_ratio:.2f}:1. O bot ganha mais vezes, mas perde mais por trade."
        )
    if pf < 1.0:
        lethal.append(f"**Profit Factor {pf:.2f}** — abaixo de 1.0, estrutura matematicamente perdedora.")
    if fee_pct > 15:
        lethal.append(
            f"**Hemorragia de custos**: taxas (${total_fees:.2f}) representam {fee_pct:.1f}% do PnL negativo."
        )
    if asym_stats["win_qty_loss_qty_ratio"] < 0.8:
        lethal.append(
            "**Fatiamento assimétrico**: quantidade média fechada em wins menor que em losses — "
            "TPs parciais capturam pouco, stops fecham posição inteira."
        )
    if exec_stats["avg_stop_slippage_pct"] > 0.05:
        lethal.append(
            f"**Slippage em stops**: média {exec_stats['avg_stop_slippage_pct']:.3f}% além do preço ordenado."
        )
    if fee_stats["liquidation_events"]:
        lethal.append(
            f"**Eventos de liquidação detectados**: {len(fee_stats['liquidation_events'])} no período."
        )

    if not lethal:
        lethal.append("Combinação de assimetria R:R, custos e execução degradando edge positivo do win rate.")

    primary = lethal[0]

    lines = [
        "# 🚨 Auditoria Forense de Algoritmo - Bybit Bot",
        "",
        "## 1. Resumo Executivo e Diagnóstico Principal",
        "",
        f"**Período analisado:** {_ms_to_iso(start_ms)} → {_ms_to_iso(end_ms)} | **Modo:** {settings_mode.upper()}",
        "",
        f"### Diagnóstico Letal",
        primary,
        "",
        "Fatores contribuintes identificados:",
    ]
    for item in lethal:
        lines.append(f"- {item}")

    lines.extend([
        "",
        "## 2. Métricas Quantitativas Extraídas da API",
        "",
        "| Métrica | Valor |",
        "|---------|-------|",
        f"| Fechamentos (closed PnL records) | {pnl_stats['total_records']} |",
        f"| Wins / Losses | {pnl_stats['wins']}W / {pnl_stats['losses']}L |",
        f"| Win Rate | {pnl_stats['winrate_pct']:.1f}% |",
        f"| PnL Realizado Total | ${pnl_stats['total_pnl']:,.2f} |",
        f"| Average Win | ${pnl_stats['avg_win']:,.2f} |",
        f"| Average Loss | ${pnl_stats['avg_loss']:,.2f} |",
        f"| Win/Loss Size Ratio | {pnl_stats['avg_win_loss_ratio']:.2f}:1 |",
        f"| Median Win / Median Loss | ${pnl_stats['median_win']:,.2f} / ${pnl_stats['median_loss']:,.2f} |",
        f"| Maior Win / Maior Loss | ${pnl_stats['largest_win']:,.2f} / ${pnl_stats['largest_loss']:,.2f} |",
        f"| Profit Factor | {pnl_stats['profit_factor']:.2f} |",
        f"| Gross Win / Gross Loss | ${pnl_stats['gross_win']:,.2f} / ${pnl_stats['gross_loss']:,.2f} |",
        f"| Max Drawdown (cumulativo) | ${pnl_stats['max_drawdown']:,.2f} |",
        f"| Alavancagem Média (API) | {pnl_stats['avg_leverage']:.1f}x |",
        f"| Taxas Trading (execuções) | ${fee_stats['trading_fees_executions']:,.2f} |",
        f"| Taxas Funding | ${fee_stats['funding_fees']:,.2f} |",
        f"| **Total Custos Operacionais** | **${total_fees:,.2f}** |",
        f"| Custos como % do Prejuízo | {fee_pct:.1f}% |",
        f"| PnL Bruto (antes de taxas, estimado) | ${total_pnl + total_fees:,.2f} |",
        f"| Execuções totais | {exec_stats['total_executions']} |",
        f"| Slippage médio (ordem vs exec) | {exec_stats['avg_slippage_pct']:.4f}% |",
        f"| Slippage máximo | {exec_stats['max_slippage_pct']:.4f}% |",
        f"| Slippage médio em Stops | {exec_stats['avg_stop_slippage_pct']:.4f}% |",
        f"| TP1 R:R planejado (journal) | {journal_stats['avg_planned_tp1_rr']:.2f}:1 |",
        f"| Distância SL média (journal) | {journal_stats['avg_sl_distance_pct']:.3f}% |",
        f"| Qty média Win vs Loss | {asym_stats['avg_win_qty']:.2f} vs {asym_stats['avg_loss_qty']:.2f} |",
        "",
        "## 3. Análise de Execução e Divergências",
        "",
    ])

  # Worst stops
    if exec_stats["worst_stops"]:
        lines.append("### Stops com Maior Slippage (ordem vs execução)")
        lines.append("")
        lines.append("| Símbolo | Side | Order Price | Exec Price | Slippage % | Fee |")
        lines.append("|---------|------|-------------|------------|------------|-----|")
        for s in exec_stats["worst_stops"][:10]:
            if s["slippage_pct"] > 0:
                lines.append(
                    f"| {s['symbol']} | {s['side']} | {s['order_price']:.6g} | "
                    f"{s['exec_price']:.6g} | {s['slippage_pct']:.3f}% | ${s['fee']:.4f} |"
                )
        lines.append("")

    if exec_stats["worst_slippage"]:
        lines.append("### Top Slippage Geral")
        lines.append("")
        for s in exec_stats["worst_slippage"][:5]:
            lines.append(
                f"- **{s['symbol']}** {s['side']} {s['order_type']}: "
                f"ordem={s['order_price']:.6g} exec={s['exec_price']:.6g} "
                f"slippage={s['slippage_pct']:.3f}% ({_ms_to_iso(s['exec_time'])})"
            )
        lines.append("")

    lines.append("### Divergências Journal vs API")
    lines.append("")
    if journal_stats["divergences"]:
        for d in journal_stats["divergences"][:8]:
            lines.append(
                f"- **{d['symbol']}**: journal exit={d['journal_exit']:.6g} vs API={d['api_exit']:.6g} "
                f"(diff {d['diff_pct']:.2f}%) | SL planejado={d['journal_sl']:.6g} | reason={d['close_reason']}"
            )
    else:
        lines.append("- Divergências de preço de saída >0.5%: nenhuma significativa detectada no match por símbolo.")
    lines.append("")

    lines.append("### Comportamento Assimétrico Win/Loss")
    lines.append("")
    lines.append(
        f"- Wins com movimento pequeno (<0.5%): **{asym_stats['partial_wins_heuristic']}** "
        f"(TPs parciais capturando fatias)"
    )
    lines.append(
        f"- Losses com movimento amplo (>0.3%): **{asym_stats['full_losses_heuristic']}** "
        f"(stops fechando posição completa ou quase)"
    )
    lines.append(
        f"- Ratio qty win/loss: **{asym_stats['win_qty_loss_qty_ratio']:.2f}** "
        f"(<1.0 = wins menores que losses em tamanho)"
    )
    lines.append("")

    if fee_stats["liquidation_events"]:
        lines.append("### Eventos de Liquidação")
        for ev in fee_stats["liquidation_events"][:5]:
            lines.append(f"- {_ms_to_iso(ev.get('transactionTime'))}: {ev.get('type')} change={ev.get('change')}")
        lines.append("")

    if tx_type_counts:
        lines.append("### Tipos de Transação (Ledger)")
        lines.append("")
        for t, c in list(tx_type_counts.items())[:12]:
            lines.append(f"- `{t}`: {c}")
        lines.append("")

    lines.extend([
        "## 4. Mapeamento de Vulnerabilidades Críticas",
        "",
        "### 4.1 Assimetria R:R Estrutural",
        f"- TP1 R:R planejado médio: **{journal_stats['avg_planned_tp1_rr']:.2f}:1** com fechamento parcial 50/30/20%",
        "- Com win rate ~55%, é necessário R:R efetivo >0.82:1; o R:R *realizado* está invertido "
        f"(avg win ${pnl_stats['avg_win']:.2f} vs avg loss ${abs(pnl_stats['avg_loss']):.2f})",
        "- TPs parciais (50% no TP1) reduzem exposição ao lucro; SL fecha 100% restante em perda",
        "",
        "### 4.2 Hemorragia de Custos com 20x",
        f"- Taxas de execução: **${fee_stats['trading_fees_executions']:,.2f}** em {exec_stats['total_executions']} fills",
        f"- Funding fees: **${fee_stats['funding_fees']:,.2f}**",
        f"- Custos totais: **${total_fees:,.2f}** ({fee_pct:.1f}% do prejuízo de ${abs(total_pnl):,.2f})",
        "- Com alavancagem ~20x, notional elevado amplifica taxas taker em cada fill parcial",
        "",
        "### 4.3 Execução de Stop Loss",
        f"- {exec_stats['stop_executions']} execuções classificadas como stop/trigger",
        f"- Slippage médio em stops: {exec_stats['avg_stop_slippage_pct']:.4f}%",
        "- Em mercados voláteis, stop-market pode executar além do trigger, especialmente em alts",
        "",
        "### 4.4 Comportamento de Margem",
        f"- Eventos liquidação: {len(fee_stats['liquidation_events'])}",
        f"- Eventos ADL: {len(fee_stats['adl_events'])}",
        f"- Alavancagem média registrada: {pnl_stats['avg_leverage']:.1f}x (config max 30x, min 10x)",
        "- Múltiplas posições concorrentes (max 3) concentram risco de margem",
        "",
        "### 4.5 Divergência Lógica vs Execução",
        f"- Journal: {journal_stats['journal_closed']} trades fechados vs API: {pnl_stats['total_records']} records",
        "- Cada TP parcial gera um closed-PnL record separado na Bybit — win rate da API conta *fechamentos*, não *trades*",
        "- `close_reason=position_closed_on_exchange` indica sync passivo sem distinção TP vs SL",
        "",
        "## 5. Próximos Passos (Isolamento de Risco)",
        "",
        "Antes de qualquer alteração na estratégia, investigar:",
        "",
        "1. **Reconciliar closed-PnL records com trades lógicos** — agrupar fills por `orderId`/posição "
        "para calcular win rate por *trade* e não por *fechamento parcial*",
        "2. **Auditar R:R efetivo pós-parciais** — simular PnL se TP1=50% com SL no restante vs resultado real",
        "3. **Isolar custo por trade** — fee/notional por símbolo e impacto do funding em holds >4h",
        "4. **Mapear stops que excederam SL planejado** — cruzar `sl_order_id` com execution list",
        "5. **Pausar ou reduzir alavancagem** até Profit Factor >1.0 em paper/backtest reconciliado",
        "6. **Validar sizing** — confirmar se `max_position_pct=5%` com 3 slots não excede `max_portfolio_risk_pct=3%`",
        "",
        f"*Relatório gerado em {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}*",
        f"*Dados brutos em `data/audit/`*",
    ])

    return "\n".join(lines)


async def main() -> int:
    setup_logging("WARNING", "text")
    settings = get_settings()
    runtime = RuntimeConfigStore(settings.settings_path)
    client = ExchangeClient(settings, runtime)

    start_ms, end_ms = period_range_ms("week")
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        await client.connect()
        exchange = client._ensure_connected()

        closed_pnl = await client.fetch_closed_pnl_records(start_ms, end_ms)
        executions = await _paginate_execution_list(exchange, start_ms, end_ms)
        tx_log = await _paginate_transaction_log(exchange, start_ms, end_ms)

        # Persist raw data
        (AUDIT_DIR / "closed_pnl.json").write_text(
            json.dumps(closed_pnl, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (AUDIT_DIR / "executions.json").write_text(
            json.dumps(executions, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (AUDIT_DIR / "transaction_log.json").write_text(
            json.dumps(tx_log, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        journal = load_journal_trades()
        week_start = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
        journal_closed = [
            t for t in journal
            if t.status == TradeStatus.CLOSED
            and t.closed_at
            and t.closed_at.replace(tzinfo=timezone.utc) >= week_start
        ]

        pnl_stats = analyze_closed_pnl(closed_pnl)
        fee_stats = analyze_fees(executions, tx_log)
        fee_stats["tx_types"] = _count_tx_types(tx_log)
        exec_stats = analyze_executions(executions)
        journal_stats = analyze_journal_vs_api(journal_closed, closed_pnl, executions)
        asym_stats = analyze_asymmetry_deep(closed_pnl)

        summary = {
            "period": {"start_ms": start_ms, "end_ms": end_ms},
            "pnl": pnl_stats,
            "fees": {k: v for k, v in fee_stats.items() if k not in ("liquidation_events", "adl_events")},
            "executions": {k: v for k, v in exec_stats.items() if k not in ("worst_slippage", "worst_stops")},
            "journal": {k: v for k, v in journal_stats.items() if k != "divergences"},
            "asymmetry": asym_stats,
        }
        # Remove equity_curve from summary (too large)
        summary["pnl"] = {k: v for k, v in summary["pnl"].items() if k != "equity_curve"}
        (AUDIT_DIR / "analysis_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        report = build_report(
            settings_mode=settings.bybit_mode,
            start_ms=start_ms,
            end_ms=end_ms,
            pnl_stats=pnl_stats,
            fee_stats=fee_stats,
            exec_stats=exec_stats,
            journal_stats=journal_stats,
            asym_stats=asym_stats,
            tx_type_counts=fee_stats["tx_types"],
        )
        REPORT_PATH.write_text(report, encoding="utf-8")

        # Minimal stdout
        print(f"OK | closed_pnl={len(closed_pnl)} executions={len(executions)} tx={len(tx_log)}")
        print(f"PnL=${pnl_stats['total_pnl']:,.2f} WR={pnl_stats['winrate_pct']:.1f}% PF={pnl_stats['profit_factor']:.2f}")
        print(f"Report: {REPORT_PATH}")
        return 0
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise
    finally:
        await client.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
