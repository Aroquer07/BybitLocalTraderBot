"""Gestão de posição: sizing por risco, TPs parciais e breakeven no TP1/TP2."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from src.config.settings import Settings
from src.services.runtime_config_store import RuntimeConfigStore
from src.services.exchange_client import ExchangeClient, clamp_leverage_hard
from src.strategies.trade_validation import REQUIRED_TP_COUNT
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class PositionSizeResult:
    """Resultado do cálculo de tamanho de posição."""

    amount: float
    notional_usdt: float
    margin_usdt: float
    risk_usdt: float
    sl_distance: float


@dataclass(frozen=True)
class PartialTPAmounts:
    """Quantidades por nível de take profit (3 níveis)."""

    tp1: float
    tp2: float
    tp3: float
    total: float


@dataclass
class ActiveTradeState:
    """Estado de um trade ativo para monitoramento."""

    symbol: str
    side: str
    entry_price: float
    original_amount: float
    stop_loss: float
    sl_order_id: str | None = None
    tp_orders: list[dict[str, Any]] = field(default_factory=list)
    tp_close_pcts: tuple[float, float, float] = (50.0, 30.0, 20.0)
    breakeven_trigger_tp: int = 0
    breakeven_applied: bool = False
    monitor_task: asyncio.Task[None] | None = None
    final_tp_task: asyncio.Task[None] | None = None


def calculate_position_size(
    balance_usdt: float,
    entry_price: float,
    stop_loss: float,
    risk_per_trade_pct: float,
    max_position_pct: float,
    leverage: int,
    min_amount: float,
    amount_precision: int | None = None,
) -> PositionSizeResult:
    """
    Calcula tamanho da posição com base no risco máximo por trade.

    risk_usdt = balance * (risk_pct / 100)
    size = risk_usdt / |entry - sl|
    Cap por max_position_pct do saldo em margem.
    """
    if balance_usdt <= 0 or entry_price <= 0:
        raise ValueError("Saldo ou preço de entrada inválido")

    sl_distance = abs(entry_price - stop_loss)
    if sl_distance <= 0:
        raise ValueError("Stop loss deve ser diferente do preço de entrada")

    risk_usdt = balance_usdt * (risk_per_trade_pct / 100.0)
    amount = risk_usdt / sl_distance

    max_margin = balance_usdt * (max_position_pct / 100.0)
    max_notional = max_margin * leverage
    max_amount = max_notional / entry_price
    amount = min(amount, max_amount)

    if amount_precision is not None:
        factor = 10**amount_precision
        amount = int(amount * factor) / factor

    if amount < min_amount:
        amount = min_amount

    notional = amount * entry_price
    margin = notional / leverage

    return PositionSizeResult(
        amount=amount,
        notional_usdt=notional,
        margin_usdt=margin,
        risk_usdt=risk_usdt,
        sl_distance=sl_distance,
    )


def split_tp_amounts(
    total_amount: float,
    tp1_pct: float,
    tp2_pct: float,
    tp3_pct: float,
    *,
    require_full_allocation: bool = True,
) -> PartialTPAmounts:
    """Divide quantidade total em 3 TPs (ex.: 50/30/20%)."""
    total_pct = tp1_pct + tp2_pct + tp3_pct
    if require_full_allocation and abs(total_pct - 100.0) > 0.01:
        raise ValueError(f"TPs devem somar 100%, recebido {total_pct}%")
    if total_pct <= 0:
        raise ValueError(f"TPs devem somar > 0%, recebido {total_pct}%")

    tp1 = total_amount * (tp1_pct / 100.0)
    tp2 = total_amount * (tp2_pct / 100.0)
    tp3 = total_amount * (tp3_pct / 100.0)

    return PartialTPAmounts(tp1=tp1, tp2=tp2, tp3=tp3, total=total_amount)


def normalize_tp_amounts_for_exchange(
    symbol: str,
    total_amount: float,
    amounts: PartialTPAmounts,
    *,
    amount_to_precision,
    min_amount: float,
) -> PartialTPAmounts:
    """Arredonda TPs e garante soma ≤ posição (evita ordens extras na exchange)."""
    raw = [amounts.tp1, amounts.tp2, amounts.tp3]
    precised = [float(amount_to_precision(symbol, a)) for a in raw]
    excess = sum(precised) - total_amount
    if excess > 0:
        for i in range(2, -1, -1):
            if excess <= 0:
                break
            reducible = max(0.0, precised[i] - min_amount)
            cut = min(excess, reducible)
            if cut > 0:
                precised[i] = float(amount_to_precision(symbol, precised[i] - cut))
                excess -= cut
    return PartialTPAmounts(
        tp1=precised[0],
        tp2=precised[1],
        tp3=precised[2],
        total=total_amount,
    )


class PositionManager:
    """Orquestra sizing, execução parcial e monitoramento de breakeven."""

    def __init__(
        self,
        settings: Settings,
        exchange: ExchangeClient,
        runtime_store: RuntimeConfigStore,
    ) -> None:
        self._settings = settings
        self._exchange = exchange
        self._runtime = runtime_store
        self._active_trades: dict[str, ActiveTradeState] = {}

    async def compute_size_for_trade(
        self,
        symbol: str,
        entry_price: float,
        stop_loss: float,
        leverage: int,
    ) -> PositionSizeResult:
        """Calcula tamanho dinâmico respeitando limites do mercado."""
        balance = await self._exchange.fetch_usdt_balance()
        limits = self._exchange.get_market_limits(symbol)

        runtime = self._runtime.reload()
        capped_leverage = clamp_leverage_hard(
            leverage, config_max=runtime.risk.max_leverage
        )
        raw = calculate_position_size(
            balance_usdt=balance,
            entry_price=entry_price,
            stop_loss=stop_loss,
            risk_per_trade_pct=runtime.risk.risk_per_trade_pct,
            max_position_pct=runtime.risk.max_position_pct,
            leverage=capped_leverage,
            min_amount=limits["min_amount"],
            amount_precision=limits.get("amount_precision"),
        )

        amount = self._exchange.amount_to_precision(symbol, raw.amount)
        limits = self._exchange.get_market_limits(symbol)
        max_amt = limits.get("max_amount")
        if max_amt:
            amount = min(amount, float(max_amt))
            amount = self._exchange.amount_to_precision(symbol, amount)

        notional = amount * entry_price
        margin = notional / capped_leverage

        return PositionSizeResult(
            amount=amount,
            notional_usdt=notional,
            margin_usdt=margin,
            risk_usdt=raw.risk_usdt,
            sl_distance=raw.sl_distance,
        )

    async def execute_with_partial_tps(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        stop_loss: float,
        take_profit_prices: list[float],
        leverage: int,
        amount: float | None = None,
        tp_close_pcts: tuple[float, float, float] | None = None,
        breakeven_after_tp: int | None = None,
    ) -> dict[str, Any]:
        """
        Executa entrada + SL + 3 TPs parciais e inicia monitor de breakeven opcional.

        breakeven_after_tp: 0=off, 1=após TP1, 2=após TP2 (default: settings).
        """
        if len(take_profit_prices) < REQUIRED_TP_COUNT:
            raise ValueError(f"São necessários {REQUIRED_TP_COUNT} níveis de take profit")
        take_profit_prices = take_profit_prices[:REQUIRED_TP_COUNT]

        runtime = self._runtime.reload()
        capped_leverage = clamp_leverage_hard(
            leverage, config_max=runtime.risk.max_leverage
        )

        if amount is None:
            sizing = await self.compute_size_for_trade(
                symbol, entry_price, stop_loss, capped_leverage
            )
            amount = sizing.amount
        else:
            amount = self._exchange.amount_to_precision(symbol, amount)

        close_pcts = tp_close_pcts or runtime.imba.tp_close_tuple()
        tp_amounts = split_tp_amounts(
            amount,
            close_pcts[0],
            close_pcts[1],
            close_pcts[2],
            require_full_allocation=tp_close_pcts is None,
        )
        limits = self._exchange.get_market_limits(symbol)
        tp_amounts = normalize_tp_amounts_for_exchange(
            symbol,
            amount,
            tp_amounts,
            amount_to_precision=self._exchange.amount_to_precision,
            min_amount=float(limits["min_amount"]),
        )

        # #region agent log
        from src.utils.debug_session import debug_log

        debug_log(
            location="position_manager.py:execute_with_partial_tps",
            message="tp_amount_split",
            hypothesis_id="H4",
            data={
                "symbol": symbol,
                "total_amount": amount,
                "tp_close_pcts": list(close_pcts),
                "tp1_amt": tp_amounts.tp1,
                "tp2_amt": tp_amounts.tp2,
                "tp3_amt": tp_amounts.tp3,
                "tp_prices": take_profit_prices[:REQUIRED_TP_COUNT],
            },
        )
        # #endregion

        result = await self._exchange.execute_trade_with_partial_tps(
            symbol=symbol,
            side=side,
            amount=amount,
            stop_loss=stop_loss,
            take_profits=[
                (take_profit_prices[0], tp_amounts.tp1),
                (take_profit_prices[1], tp_amounts.tp2),
                (take_profit_prices[2], tp_amounts.tp3),
            ],
            leverage=capped_leverage,
            entry_price=entry_price,
        )

        if result.get("emergency_closed"):
            logger.error("Trade encerrado em emergência | symbol=%s", symbol)
            return result

        state = ActiveTradeState(
            symbol=symbol,
            side=side,
            entry_price=float(result.get("entry_price") or entry_price),
            original_amount=amount,
            stop_loss=float(result.get("stop_loss") or stop_loss),
            sl_order_id=result.get("sl_order_id"),
            tp_orders=result.get("tp_orders", []),
            tp_close_pcts=close_pcts,
            breakeven_trigger_tp=breakeven_after_tp
            if breakeven_after_tp is not None
            else runtime.breakeven.level,
        )
        self._active_trades[symbol] = state

        if state.breakeven_trigger_tp > 0:
            state.monitor_task = asyncio.create_task(
                self._monitor_breakeven(state),
                name=f"breakeven-{symbol}",
            )

        state.final_tp_task = asyncio.create_task(
            self._monitor_final_tp(state),
            name=f"final-tp-{symbol}",
        )

        result["sizing"] = {
            "amount": amount,
            "tp_amounts": {
                "tp1": tp_amounts.tp1,
                "tp2": tp_amounts.tp2,
                "tp3": tp_amounts.tp3,
            },
        }
        return result

    @staticmethod
    def _remaining_pct_after_tp(
        tp_close_pcts: tuple[float, float, float],
        trigger_level: int,
    ) -> float:
        """% da posição que deve restar após o TP gatilho do breakeven."""
        idx = max(0, min(trigger_level, REQUIRED_TP_COUNT)) - 1
        return sum(tp_close_pcts[idx + 1 :])

    def _tp_fill_threshold(
        self,
        state: ActiveTradeState,
        trigger_level: int,
    ) -> float:
        """Tamanho máximo da posição após o TP gatilho (com 2% de tolerância)."""
        remaining_pct = self._remaining_pct_after_tp(
            state.tp_close_pcts, trigger_level
        )
        return state.original_amount * (remaining_pct / 100.0) * 1.02

    def _final_tp_order(self, state: ActiveTradeState) -> dict[str, Any] | None:
        return next(
            (tp for tp in state.tp_orders if int(tp.get("level") or 0) == REQUIRED_TP_COUNT),
            None,
        )

    def _final_tp_size_threshold(self, state: ActiveTradeState) -> float:
        """Tamanho máximo esperado quando só resta o TP final (20% + tolerância)."""
        pct = state.tp_close_pcts[REQUIRED_TP_COUNT - 1]
        return state.original_amount * (pct / 100.0) * 1.05

    async def _monitor_final_tp(self, state: ActiveTradeState) -> None:
        """
        Garante TP3 ativo com qty correta e fecha o restante se o preço cruzar sem fill.
        """
        tp_final = self._final_tp_order(state)
        if not tp_final:
            return

        tp_price = float(tp_final.get("price") or 0)
        if tp_price <= 0:
            return

        symbol = state.symbol
        is_long = state.side.lower() in ("buy", "long")
        size_threshold = self._final_tp_size_threshold(state)
        poll_interval = 5.0
        max_wait = 604_800.0
        elapsed = 0.0

        logger.info(
            "Monitor TP%d | %s | price=%.6g | size_threshold=%.4f",
            REQUIRED_TP_COUNT,
            symbol,
            tp_price,
            size_threshold,
        )

        try:
            # Garante um estado "limpo" no início: evita acumular TPs duplicadas no
            # mesmo preço (Bybit limita TP+SL e pode começar a falhar/duplicar).
            ensured = await self._exchange.ensure_take_profit_for_remaining(
                symbol,
                state.side,
                tp_price,
            )
            if ensured and ensured.get("order_id"):
                tp_final["order_id"] = ensured["order_id"]
                if ensured.get("amount"):
                    tp_final["amount"] = ensured["amount"]

            while elapsed < max_wait:
                remaining = await self._exchange.fetch_position_size(
                    symbol, state.side
                )
                if remaining <= 0:
                    logger.info("TP%d completo | %s | posição zerada", REQUIRED_TP_COUNT, symbol)
                    break

                if remaining <= size_threshold:
                    ensured = await self._exchange.ensure_take_profit_for_remaining(
                        symbol,
                        state.side,
                        tp_price,
                    )
                    if ensured and ensured.get("order_id"):
                        tp_final["order_id"] = ensured["order_id"]
                        if ensured.get("amount"):
                            tp_final["amount"] = ensured["amount"]

                    ticker = await self._exchange.fetch_ticker(symbol)
                    mark = float(
                        ticker.get("last")
                        or ticker.get("close")
                        or ticker.get("bid")
                        or 0
                    )
                    crossed = mark >= tp_price if is_long else mark <= tp_price

                    if crossed:
                        remaining = await self._exchange.fetch_position_size(
                            symbol, state.side
                        )
                        if remaining <= 0:
                            break

                        order_id = tp_final.get("order_id")
                        filled = False
                        if order_id:
                            try:
                                order = await self._exchange.fetch_order(
                                    str(order_id), symbol
                                )
                                status = (order.get("status") or "").lower()
                                filled_amt = float(order.get("filled") or 0)
                                order_amt = float(
                                    order.get("amount") or tp_final.get("amount") or 0
                                )
                                if status in ("closed", "filled") or (
                                    order_amt > 0 and filled_amt >= order_amt * 0.99
                                ):
                                    filled = True
                            except Exception as exc:
                                logger.warning(
                                    "Poll TP%d indisponível | %s | %s",
                                    REQUIRED_TP_COUNT,
                                    order_id,
                                    exc,
                                )

                        if not filled and remaining > 0:
                            logger.warning(
                                "TP%d cruzado sem fill — fechando restante a mercado | %s | mark=%.6g qty=%.4f",
                                REQUIRED_TP_COUNT,
                                symbol,
                                mark,
                                remaining,
                            )
                            await self._exchange.emergency_close_position(
                                symbol, state.side
                            )
                        break

                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

            if elapsed >= max_wait:
                logger.info(
                    "Monitor TP%d timeout | %s | elapsed=%.0fs",
                    REQUIRED_TP_COUNT,
                    symbol,
                    elapsed,
                )
        except asyncio.CancelledError:
            logger.info("Monitor TP%d cancelado | %s", REQUIRED_TP_COUNT, symbol)
            raise

    async def _monitor_breakeven(self, state: ActiveTradeState) -> None:
        """Monitora TP1 ou TP2 e move SL para entrada quando preenchido."""
        trigger_level = state.breakeven_trigger_tp
        if trigger_level not in (1, 2):
            return

        tp_order = next(
            (tp for tp in state.tp_orders if tp.get("level") == trigger_level),
            None,
        )
        size_threshold = self._tp_fill_threshold(state, trigger_level)

        order_id = str(tp_order["order_id"]) if tp_order and tp_order.get("order_id") else None
        symbol = state.symbol
        poll_interval = 5.0
        max_wait = 604_800.0  # 7 dias
        elapsed = 0.0

        logger.info(
            "Monitor breakeven | %s | após TP%d | order=%s | size_threshold=%.4f",
            symbol,
            trigger_level,
            order_id or "position-poll",
            size_threshold,
        )

        try:
            current_sl = await self._exchange.fetch_open_stop_loss_price(
                symbol, state.side
            )
            if current_sl and self._exchange.is_stop_at_entry(
                state.entry_price, current_sl
            ):
                state.breakeven_applied = True
                state.stop_loss = state.entry_price
                logger.info(
                    "Breakeven já em vigor | %s | SL@%.6g ≈ entrada — monitor encerrado",
                    symbol,
                    current_sl,
                )
                return

            while elapsed < max_wait and not state.breakeven_applied:
                tp_filled = False

                if order_id:
                    try:
                        order = await self._exchange.fetch_order(order_id, symbol)
                        status = (order.get("status") or "").lower()
                        filled = float(order.get("filled") or 0)
                        amount = float(order.get("amount") or tp_order.get("amount") or 0)
                        if status in ("closed", "filled") or (
                            amount > 0 and filled >= amount * 0.99
                        ):
                            tp_filled = True
                    except Exception as exc:
                        logger.warning(
                            "Poll TP%d indisponível | %s | %s — usando tamanho da posição",
                            trigger_level,
                            order_id,
                            exc,
                        )

                if not tp_filled:
                    remaining = await self._exchange.fetch_position_size(
                        symbol, state.side
                    )
                    if remaining <= 0:
                        state.breakeven_applied = True
                        break
                    if 0 < remaining <= size_threshold:
                        tp_filled = True
                        logger.info(
                            "TP%d inferido por tamanho | %s | remaining=%.4f",
                            trigger_level,
                            symbol,
                            remaining,
                        )

                if tp_filled:
                    # #region agent log
                    from src.utils.debug_session import debug_log

                    debug_log(
                        location="position_manager.py:_monitor_breakeven",
                        message="tp_trigger_breakeven",
                        hypothesis_id="H3",
                        data={
                            "symbol": symbol,
                            "trigger_level": trigger_level,
                            "order_id": order_id,
                            "remaining": await self._exchange.fetch_position_size(
                                symbol, state.side
                            ),
                            "original_amount": state.original_amount,
                            "size_threshold": size_threshold,
                            "entry_price": state.entry_price,
                            "stop_loss": state.stop_loss,
                        },
                    )
                    # #endregion
                    await self._apply_breakeven(state)
                    break

                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

            if not state.breakeven_applied and elapsed >= max_wait:
                logger.info(
                    "Monitor breakeven timeout | %s | TP%d | elapsed=%.0fs",
                    symbol,
                    trigger_level,
                    elapsed,
                )
        except asyncio.CancelledError:
            logger.info("Monitor breakeven cancelado | %s", symbol)
            raise

    async def _apply_breakeven(self, state: ActiveTradeState) -> None:
        """Move SL para preço de entrada na posição restante."""
        if state.breakeven_applied:
            return

        remaining = await self._exchange.fetch_position_size(
            state.symbol, state.side
        )
        if remaining <= 0:
            logger.info(
                "Sem posição restante para breakeven | %s",
                state.symbol,
            )
            state.breakeven_applied = True
            return

        pending_tps = []
        for tp in state.tp_orders:
            if int(tp.get("level") or 0) > state.breakeven_trigger_tp:
                pending_tps.append(dict(tp))
        if pending_tps:
            tp_final = max(pending_tps, key=lambda t: int(t.get("level") or 0))
            if int(tp_final.get("level") or 0) == REQUIRED_TP_COUNT:
                tp_final["amount"] = remaining

        current_sl = await self._exchange.fetch_open_stop_loss_price(
            state.symbol, state.side
        )
        if current_sl and self._exchange.is_stop_at_entry(
            state.entry_price, current_sl
        ):
            state.breakeven_applied = True
            state.stop_loss = state.entry_price
            logger.info(
                "Breakeven já aplicado | %s | SL@entrada — TPs mantidos",
                state.symbol,
            )
            return

        try:
            new_sl = await self._exchange.move_stop_loss_to_entry(
                symbol=state.symbol,
                entry_side=state.side,
                entry_price=state.entry_price,
                amount=remaining,
                tp_fallback=pending_tps,
            )
            state.sl_order_id = new_sl.get("id")
            state.stop_loss = state.entry_price
            state.breakeven_applied = True

            for restored in new_sl.get("restored_tps") or []:
                price = float(restored.get("price") or 0)
                for tp in state.tp_orders:
                    if abs(float(tp.get("price") or 0) - price) < 1e-8:
                        tp["order_id"] = restored.get("order_id")
                        if restored.get("amount"):
                            tp["amount"] = restored["amount"]
                        break

            tp_final = self._final_tp_order(state)
            if tp_final:
                ensured = await self._exchange.ensure_take_profit_for_remaining(
                    state.symbol,
                    state.side,
                    float(tp_final.get("price") or 0),
                )
                if ensured and ensured.get("order_id"):
                    tp_final["order_id"] = ensured["order_id"]
                    if ensured.get("amount"):
                        tp_final["amount"] = ensured["amount"]

            logger.info(
                "Breakeven aplicado | %s | SL->entrada @ %s | qty=%s | order=%s | tps_restored=%d",
                state.symbol,
                state.entry_price,
                remaining,
                state.sl_order_id,
                len(new_sl.get("restored_tps") or []),
            )
        except Exception:
            logger.exception(
                "Falha ao aplicar breakeven | %s — tentando emergency close",
                state.symbol,
            )
            await self._exchange.emergency_close_position(state.symbol, state.side)

    def stop_monitoring(self, symbol: str) -> None:
        """Cancela tasks de monitoramento para um símbolo."""
        state = self._active_trades.get(symbol)
        if not state:
            return
        for task in (state.monitor_task, state.final_tp_task):
            if task and not task.done():
                task.cancel()
