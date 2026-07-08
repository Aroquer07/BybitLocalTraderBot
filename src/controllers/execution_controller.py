"""Controller de execução — SL/TPs, limite de posições e trade journal."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from src.config.settings import Settings
from src.services.runtime_config_store import RuntimeConfigStore
from src.models.schemas import (
    OrderSide,
    TelegramSignal,
    TradeDecision,
    TradeDirection,
    TradeSource,
)
from src.services.exchange_client import ExchangeClient, clamp_leverage_hard
from src.services.position_manager import ActiveTradeState, PositionManager
from src.services.slippage_guard import SlippageEvent, format_slippage_alert, notify_slippage_events
from src.services.trade_journal import TradeJournal
from src.services.trade_notifier import TradeNotifier
from src.strategies.trade_validation import (
    REQUIRED_TP_COUNT,
    apply_liquidation_safe_stop_loss,
)
from src.utils.formatters import format_price
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ExecutionController:
    """
    Executa trades aprovados com gestão de risco.

    - Telegram: confidence >= 90% (kill switch padrão)
    - Scanner: confidence >= 65% (configurável)
    - Máximo de posições simultâneas (default 3)
    - IMBA ALGO: TPs 50/30/20, breakeven após TP1/TP2, sem fechar em reversão
    - Registra todos os trades no journal para win/loss
    """

    def __init__(
        self,
        settings: Settings,
        exchange_client: ExchangeClient,
        runtime_store: RuntimeConfigStore,
        trade_notifier: TradeNotifier | None = None,
    ) -> None:
        self._settings = settings
        self._exchange = exchange_client
        self._runtime = runtime_store
        self._position_mgr = PositionManager(settings, exchange_client, runtime_store)
        self._journal = TradeJournal(runtime_store)
        self._notifier = trade_notifier

    @property
    def journal(self) -> TradeJournal:
        return self._journal

    def _portfolio_risk_usdt(self) -> float:
        """Soma do risco em USDT das posições abertas (amount × distância SL)."""
        total = 0.0
        for trade in self._journal.list_open():
            if trade.amount and trade.entry_price and trade.stop_loss:
                total += float(trade.amount) * abs(
                    float(trade.entry_price) - float(trade.stop_loss)
                )
        return total

    async def open_position_count(self) -> int:
        """Posições abertas (exchange; fallback journal)."""
        try:
            return await self._exchange.count_open_positions()
        except Exception:
            return self._journal.count_open()

    async def available_trade_slots(self) -> int:
        """Vagas restantes até o limite do ambiente (demo=10, prod=config)."""
        runtime = self._runtime.reload()
        limit = runtime.effective_max_concurrent_trades(self._settings.bybit_mode)
        open_count = await self.open_position_count()
        return max(0, limit - open_count)

    async def can_open_new_trade(self, symbol: str) -> tuple[bool, str]:
        """Verifica limite global e posição duplicada no símbolo."""
        if self._journal.has_open_position(symbol):
            return False, f"Já existe trade aberto em {symbol} no journal"

        runtime = self._runtime.reload()
        limit = runtime.effective_max_concurrent_trades(self._settings.bybit_mode)
        open_count = await self.open_position_count()
        if open_count >= limit:
            return (
                False,
                f"Limite de {limit} posições atingido "
                f"({open_count} abertas)",
            )
        return True, ""

    async def execute_decisions_batch(
        self,
        decisions: list[TradeDecision],
    ) -> list[dict | None]:
        """Executa vários trades aprovados no mesmo ciclo, até esgotar slots."""
        results: list[dict | None] = []
        for decision in decisions:
            slots = await self.available_trade_slots()
            if slots <= 0:
                logger.info(
                    "Batch interrompido | limite de posições atingido | "
                    "executados=%d/%d",
                    len(results),
                    len(decisions),
                )
                break
            allowed, reason = await self.can_open_new_trade(decision.symbol or "")
            if not allowed:
                logger.info(
                    "Batch skip | %s | %s",
                    decision.symbol,
                    reason,
                )
                continue
            results.append(await self.execute_imba_decision(decision))
        return results

    async def sync_closed_positions(self) -> None:
        """Sincroniza journal quando posições foram fechadas na exchange."""
        for trade in self._journal.list_open():
            try:
                side = "buy" if trade.direction == TradeDirection.LONG else "sell"
                size = await self._exchange.fetch_position_size(trade.symbol, side)
                if size <= 0:
                    ticker = await self._exchange.fetch_ticker(trade.symbol)
                    last = float(ticker.get("last") or ticker.get("close") or 0)
                    if last > 0:
                        self._journal.close_by_symbol_if_flat(trade.symbol, last)
                        await self._audit_slippage_on_close(trade.symbol)
            except Exception:
                logger.exception("Erro ao sync journal | %s", trade.symbol)

    async def _audit_slippage_on_close(self, symbol: str) -> None:
        """Audita slippage de execuções recentes ao fechar posição."""
        end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_ms = end_ms - 3_600_000
        try:
            events = await self._exchange.scan_recent_slippage(
                start_ms, end_ms, symbol=symbol
            )
            close_events = [
                e for e in events if e.context in ("stop", "take_profit", "execution")
            ]
            await notify_slippage_events(close_events, self._notifier)
        except Exception:
            logger.exception("Falha ao auditar slippage | %s", symbol)

    async def handle_decision(
        self,
        signal: TelegramSignal | None,
        decision: TradeDecision,
    ) -> dict | None:
        if not decision.passes_kill_switch:
            logger.info(
                "Execução ignorada | conf=%.0f%% < %.0f%% | symbol=%s",
                decision.confidence * 100,
                decision.confidence_threshold * 100,
                decision.symbol,
            )
            return None
        return await self._execute(decision, signal)

    async def execute_imba_decision(self, decision: TradeDecision) -> dict | None:
        """Atalho para execução de trade originado pelo scanner IMBA."""
        runtime = self._runtime.reload()
        decision = decision.model_copy(
            update={
                "source": TradeSource.SCANNER,
                "confidence_threshold": runtime.confidence.scanner,
            }
        )
        return await self.handle_decision(None, decision)

    async def _execute(
        self,
        decision: TradeDecision,
        signal: TelegramSignal | None,
    ) -> dict | None:
        assert decision.symbol is not None
        assert decision.direction is not None
        assert decision.entry_price is not None
        assert decision.stop_loss is not None

        allowed, reason = await self.can_open_new_trade(decision.symbol)
        if not allowed:
            logger.info("Execução bloqueada | %s | %s", decision.symbol, reason)
            return None

        runtime = self._runtime.reload()
        feat = (
            decision.probability_breakdown.get("features")
            if decision.probability_breakdown
            else None
        )
        if feat and runtime.learning.enabled:
            from src.services.trade_learning import is_pattern_blocked

            closed = self._journal.list_closed()
            blocked, block_reason = is_pattern_blocked(feat, closed, runtime.learning)
            if blocked:
                logger.warning(
                    "Execução bloqueada por aprendizado | %s | %s",
                    decision.symbol,
                    block_reason,
                )
                return None

        side = self._resolve_side(decision.direction)
        if decision.leverage is None:
            logger.info(
                "Execução bloqueada | %s | IA não definiu alavancagem",
                decision.symbol,
            )
            return None
        leverage = min(decision.leverage, runtime.risk.max_leverage)
        leverage = clamp_leverage_hard(leverage, config_max=runtime.risk.max_leverage)
        take_profit_prices = [tp.price for tp in decision.take_profits]

        if len(take_profit_prices) < REQUIRED_TP_COUNT:
            self._fill_missing_tps(decision, take_profit_prices)

        try:
            side_str = side.value
            liq_price = await self._exchange.resolve_liquidation_price(
                decision.symbol,
                side_str,
                decision.entry_price,
                leverage,
            )
        except Exception:
            from src.strategies.liquidation_safety import estimate_liquidation_price

            liq_price = estimate_liquidation_price(
                decision.entry_price,
                leverage,
                decision.direction.value,
            )

        safe_sl, sl_err = apply_liquidation_safe_stop_loss(
            decision.direction,
            decision.entry_price,
            decision.stop_loss,
            liq_price,
            runtime.risk.liquidation_sl_buffer_pct,
        )
        if sl_err or safe_sl is None:
            logger.warning(
                "Execução bloqueada | %s | SL vs liquidação: %s (liq=%.6g)",
                decision.symbol,
                sl_err,
                liq_price,
            )
            return None
        if safe_sl != decision.stop_loss:
            logger.warning(
                "SL ajustado por liquidação | %s | %.6g -> %.6g | liq=%.6g",
                decision.symbol,
                decision.stop_loss,
                safe_sl,
                liq_price,
            )
            decision = decision.model_copy(update={"stop_loss": safe_sl})

        tp_close_pcts = runtime.imba.tp_close_tuple()
        breakeven_tp = runtime.breakeven.level

        try:
            sizing = await self._position_mgr.compute_size_for_trade(
                symbol=decision.symbol,
                entry_price=decision.entry_price,
                stop_loss=decision.stop_loss,
                leverage=leverage,
            )
        except Exception:
            logger.exception("Falha no sizing | %s", decision.symbol)
            return None

        balance = await self._exchange.fetch_usdt_balance()
        open_risk = self._portfolio_risk_usdt()
        total_risk = open_risk + sizing.risk_usdt
        max_portfolio = balance * (runtime.risk.max_portfolio_risk_pct / 100.0)
        if total_risk > max_portfolio:
            logger.warning(
                "Execução bloqueada | %s | risco carteira %.2f USDT > limite %.2f USDT "
                "(aberto=%.2f + novo=%.2f)",
                decision.symbol,
                total_risk,
                max_portfolio,
                open_risk,
                sizing.risk_usdt,
            )
            return None

        exec_tf = decision.execution_timeframe or runtime.timeframes.execution
        tp_summary = " | ".join(
            format_price(p) for p in take_profit_prices[:REQUIRED_TP_COUNT]
        )

        # #region agent log
        from src.utils.debug_session import debug_log

        sl_dist = abs(decision.entry_price - decision.stop_loss)
        tp1_dist = (
            abs(take_profit_prices[0] - decision.entry_price)
            if take_profit_prices
            else 0.0
        )
        debug_log(
            location="execution_controller.py:_execute",
            message="planned_execution_levels",
            hypothesis_id="H2",
            data={
                "symbol": decision.symbol,
                "direction": decision.direction.value,
                "planned_entry": decision.entry_price,
                "stop_loss": decision.stop_loss,
                "sl_dist_pct": round(sl_dist / decision.entry_price * 100, 4),
                "tp1": take_profit_prices[0] if take_profit_prices else None,
                "tp1_dist_pct": round(tp1_dist / decision.entry_price * 100, 4),
                "tp1_rr": round(tp1_dist / sl_dist, 4) if sl_dist > 0 else None,
                "tps": take_profit_prices[:4],
                "leverage": leverage,
                "amount": sizing.amount,
                "tp_close_pcts": list(tp_close_pcts),
            },
        )
        # #endregion

        logger.info(
            "Executando | %s %s | source=%s | exec_tf=%s | conf=%.0f%% | lev=%dx | "
            "entry=%s | sl=%s | tps=%s",
            decision.direction.value,
            decision.symbol,
            decision.source.value,
            exec_tf,
            decision.confidence * 100,
            leverage,
            decision.entry_price,
            decision.stop_loss,
            tp_summary,
        )

        try:
            result = await self._position_mgr.execute_with_partial_tps(
                symbol=decision.symbol,
                side=side.value,
                entry_price=decision.entry_price,
                stop_loss=decision.stop_loss,
                take_profit_prices=take_profit_prices[:REQUIRED_TP_COUNT],
                leverage=leverage,
                amount=sizing.amount,
                tp_close_pcts=tp_close_pcts,
                breakeven_after_tp=breakeven_tp,
            )
        except Exception:
            logger.exception("Falha na execução | %s", decision.symbol)
            return None

        if result.get("emergency_closed"):
            logger.error("Emergency close | %s", decision.symbol)
            return result

        # #region agent log
        from src.utils.debug_session import debug_log

        actual_fill = result.get("entry_price")
        planned = decision.entry_price
        fill_delta = (actual_fill - planned) if actual_fill and planned else None
        debug_log(
            location="execution_controller.py:_execute:after_fill",
            message="post_execution_fill",
            hypothesis_id="H1",
            data={
                "symbol": decision.symbol,
                "planned_entry": planned,
                "actual_entry": actual_fill,
                "fill_delta": fill_delta,
                "tp_orders_placed": len(result.get("tp_orders") or []),
                "sl_order_id": result.get("sl_order_id"),
            },
        )
        # #endregion

        journal_note = decision.bias or decision.ai_analysis or ""
        if exec_tf:
            tf_note = f"exec_tf={exec_tf}"
            journal_note = f"{tf_note} | {journal_note}" if journal_note else tf_note

        prob_features = None
        if decision.probability_breakdown and decision.probability_breakdown.get("features"):
            prob_features = dict(decision.probability_breakdown["features"])
            if decision.leverage is not None:
                prob_features["leverage"] = decision.leverage

        filled_entry = float(result.get("entry_price") or decision.entry_price)
        filled_sl = float(result.get("stop_loss") or decision.stop_loss)
        filled_tps = result.get("take_profit_prices") or take_profit_prices[:REQUIRED_TP_COUNT]
        effective_leverage = int(result.get("leverage") or leverage)

        self._journal.record_open(
            symbol=decision.symbol,
            direction=decision.direction,
            source=decision.source,
            entry_price=filled_entry,
            stop_loss=filled_sl,
            take_profits=filled_tps[:REQUIRED_TP_COUNT],
            confidence=decision.confidence,
            leverage=effective_leverage,
            amount=sizing.amount,
            entry_order_id=str(result.get("entry", {}).get("id") or ""),
            sl_order_id=str(result.get("sl_order_id") or ""),
            telegram_message_id=signal.message_id if signal else None,
            notes=journal_note,
            probability_features=prob_features,
        )

        logger.info(
            "Trade executado | %s | exec_tf=%s | entry=%s | tps=%s | journal_stats=%s",
            decision.symbol,
            exec_tf,
            result.get("entry", {}).get("id"),
            tp_summary,
            self._journal.get_stats(),
        )
        if self._notifier is not None:
            try:
                await self._notifier.notify_trade_opened(
                    decision,
                    leverage=effective_leverage,
                    amount=sizing.amount,
                )
                slip = result.get("entry_slippage")
                if slip:
                    event = SlippageEvent(
                        symbol=decision.symbol,
                        context="entry",
                        order_price=float(slip["order_price"]),
                        exec_price=float(slip["exec_price"]),
                        slippage_pct=float(slip["slippage_pct"]),
                        side=side.value,
                        order_type="Market",
                    )
                    await self._notifier.send_message(format_slippage_alert(event))
            except Exception:
                logger.exception("Falha ao notificar trade aberto | %s", decision.symbol)
        return result

    async def resume_breakeven_for_open_trades(self) -> None:
        """Reativa monitor de breakeven para trades abertos no journal (após restart)."""
        runtime = self._runtime.reload()
        level = runtime.breakeven.level
        if level <= 0:
            return

        for trade in self._journal.list_open():
            symbol = trade.symbol
            if symbol in self._position_mgr._active_trades:
                continue
            side = "buy" if trade.direction == TradeDirection.LONG else "sell"
            try:
                size = await self._exchange.fetch_position_size(symbol, side)
            except Exception:
                logger.exception("Falha ao checar posição para breakeven | %s", symbol)
                continue
            if size <= 0:
                continue

            breakeven_active = False
            try:
                current_sl = await self._exchange.fetch_open_stop_loss_price(
                    symbol, side
                )
            except Exception:
                logger.exception("Falha ao ler SL aberto | %s", symbol)
                current_sl = None

            if current_sl and self._exchange.is_stop_at_entry(
                trade.entry_price, current_sl
            ):
                breakeven_active = True
                logger.info(
                    "Breakeven já ativo | %s | SL@%.6g ≈ entrada@%.6g — monitor não reiniciado",
                    symbol,
                    current_sl,
                    trade.entry_price,
                )

            tp_close_pcts = runtime.imba.tp_close_tuple()
            tp_orders: list[dict] = []
            try:
                snapshots = await self._exchange._collect_open_tp_snapshots(
                    symbol, side
                )
                for idx, snap in enumerate(snapshots, start=1):
                    tp_orders.append(
                        {
                            "level": idx,
                            "order_id": snap.get("order_id"),
                            "price": snap["price"],
                            "amount": snap["amount"],
                        }
                    )
            except Exception:
                logger.exception("Falha ao snapshot TPs | %s", symbol)

            if not tp_orders and trade.take_profits:
                original = trade.amount or size
                for idx, price in enumerate(trade.take_profits, start=1):
                    pct_idx = idx - 1
                    pct = (
                        tp_close_pcts[pct_idx]
                        if pct_idx < len(tp_close_pcts)
                        else 0.0
                    )
                    tp_orders.append(
                        {
                            "level": idx,
                            "price": float(price),
                            "amount": original * (pct / 100.0),
                        }
                    )

            state = ActiveTradeState(
                symbol=symbol,
                side=side,
                entry_price=trade.entry_price,
                original_amount=trade.amount or size,
                stop_loss=trade.stop_loss,
                sl_order_id=trade.sl_order_id,
                tp_orders=tp_orders,
                tp_close_pcts=tp_close_pcts,
                breakeven_trigger_tp=level,
            )
            if breakeven_active:
                # Se SL já está em breakeven, não precisa reiniciar monitor de breakeven,
                # mas ainda precisamos garantir TP final (pruning/correção de duplicadas).
                state.breakeven_applied = True
                state.stop_loss = trade.entry_price
            self._position_mgr._active_trades[symbol] = state
            if not breakeven_active:
                state.monitor_task = asyncio.create_task(
                    self._position_mgr._monitor_breakeven(state),
                    name=f"breakeven-resume-{symbol}",
                )
                logger.info(
                    "Breakeven retomado | %s | após TP%d | size=%.4f | tps=%d",
                    symbol,
                    level,
                    size,
                    len(tp_orders),
                )
            else:
                state.final_tp_task = asyncio.create_task(
                    self._position_mgr._monitor_final_tp(state),
                    name=f"final-tp-resume-{symbol}",
                )
                logger.info(
                    "Breakeven já ativo — reiniciando apenas monitor TP%d | %s | size=%.4f | tps=%d",
                    REQUIRED_TP_COUNT,
                    symbol,
                    size,
                    len(tp_orders),
                )

    def _fill_missing_tps(
        self,
        decision: TradeDecision,
        take_profit_prices: list[float],
    ) -> None:
        while len(take_profit_prices) < REQUIRED_TP_COUNT:
            if take_profit_prices:
                take_profit_prices.append(take_profit_prices[-1])
            else:
                offset = 0.01 * (len(take_profit_prices) + 1)
                if decision.direction == TradeDirection.LONG:
                    take_profit_prices.append(decision.entry_price * (1 + offset))
                else:
                    take_profit_prices.append(decision.entry_price * (1 - offset))

    @staticmethod
    def _resolve_side(direction: TradeDirection) -> OrderSide:
        return OrderSide.BUY if direction == TradeDirection.LONG else OrderSide.SELL
