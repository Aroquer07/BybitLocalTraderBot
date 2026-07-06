"""Controller cerebral — coleta multi-TF, confluência Python, consulta LLM."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from src.config.settings import Settings
from src.models.schemas import TelegramSignal, TradeDecision, TradeDirection, TradeSource
from src.services.exchange_client import ExchangeClient
from src.services.llm_client import LLMClient
from src.services.runtime_config_store import RuntimeConfigStore
from src.services.rejection_log import record_rejection
from src.services.trade_journal import TradeJournal
from src.services.trade_learning import is_pattern_blocked
from src.strategies.imba_analyzer import (
    analyze_multi_timeframe,
    config_from_runtime,
    imba_analysis_timeframes,
)
from src.strategies.execution_levels import resolve_execution_levels
from src.strategies.trade_validation import (
    apply_execution_levels,
    validate_execution_decision,
)
from src.strategies.win_probability import enrich_decision_with_win_probability
from src.strategies.technical_analysis import TechnicalAnalysisEngine
from src.utils.formatters import format_trade_decision_log
from src.utils.logger import get_logger
from src.utils.trade_filters import check_signal_allowed, infer_trade_style

logger = get_logger(__name__)

DecisionCallback = Callable[[TelegramSignal, TradeDecision], Awaitable[None]]


class BrainController:
    """
    Cérebro do agente: sinal → multi-TF CCXT → indicadores + confluência → LLM.

    A LLM atua exclusivamente como Juiz Estratégico. Indicadores e confluência
    são calculados via Python, nunca pela IA.
    """

    def __init__(
        self,
        settings: Settings,
        exchange_client: ExchangeClient,
        llm_client: LLMClient,
        ta_engine: TechnicalAnalysisEngine,
        runtime_store: RuntimeConfigStore,
    ) -> None:
        self._settings = settings
        self._exchange = exchange_client
        self._llm = llm_client
        self._ta = ta_engine
        self._runtime = runtime_store
        self._on_decision_callback: DecisionCallback | None = None

    def on_decision(self, callback: DecisionCallback) -> None:
        """Registra callback para decisões de trade (aprovadas ou recusadas)."""
        self._on_decision_callback = callback

    async def process_signal(self, signal: TelegramSignal) -> TradeDecision:
        """
        Pipeline completo de análise para um sinal.

        Erros em CCXT ou Ollama retornam decisão de recusa sem propagar exceção.
        """
        runtime = self._runtime.reload()
        symbol = signal.symbol
        if not symbol:
            logger.warning("Sinal sem símbolo identificável | msg_id=%s", signal.message_id)
            decision = self._reject("Símbolo não identificado no sinal")
            await self._dispatch(signal, decision)
            return decision

        trade_style = signal.trade_style or infer_trade_style(
            signal.raw_text,
            runtime.timeframes.primary,
        )
        allowed, reject_reason = check_signal_allowed(
            signal, trade_style, self._settings, filters=runtime.telegram
        )
        if not allowed:
            logger.info(
                "Sinal filtrado | msg_id=%s | estilo=%s | motivo=%s",
                signal.message_id,
                trade_style.value,
                reject_reason,
            )
            decision = self._reject(reject_reason, symbol=symbol, stage="filter")
            await self._dispatch(signal, decision)
            return decision

        try:
            ohlcv_by_tf, orderbook = await self._fetch_market_data(symbol, runtime)
            imba_ohlcv = await self._fetch_imba_timeframes(symbol, runtime)
            imba_config = config_from_runtime(runtime)
            imba_analysis = analyze_multi_timeframe(
                symbol,
                imba_ohlcv,
                imba_config,
                settings=runtime,
            )
            market_state = self._ta.build_market_state(
                symbol=symbol,
                ohlcv_by_timeframe=ohlcv_by_tf,
                orderbook=orderbook,
            )
            market_state = market_state.model_copy(
                update={"imba_analysis": imba_analysis},
            )
            logger.info(
                "MarketState | %s | TFs=%s | confluence=%s (L=%d S=%d) | %s",
                symbol,
                list(market_state.timeframes.keys()),
                market_state.confluence.recommendation if market_state.confluence else "N/A",
                market_state.confluence.long_score if market_state.confluence else 0,
                market_state.confluence.short_score if market_state.confluence else 0,
                imba_analysis.summary,
            )
        except Exception:
            logger.exception("Falha ao coletar dados de mercado | symbol=%s", symbol)
            decision = self._reject(
                f"Falha na coleta de dados para {symbol}",
                symbol=symbol,
                stage="filter",
            )
            await self._dispatch(signal, decision)
            return decision

        decision = await self._llm.evaluate_trade(signal, market_state)
        decision = self._enrich_with_imba(
            decision, imba_analysis, imba_ohlcv, signal, runtime
        )
        decision = validate_execution_decision(decision, runtime)
        try:
            journal = TradeJournal(self._runtime)
            closed: list = journal.list_closed()
            decision = enrich_decision_with_win_probability(
                decision,
                imba_analysis,
                market_state,
                source=TradeSource.TELEGRAM,
                confidence_threshold=runtime.confidence.telegram,
                closed_trades=closed,
                learning_config=runtime.learning,
            )
        except Exception:
            logger.exception("Falha P(win) | %s", symbol)
            closed = []

        feat = (
            decision.probability_breakdown.get("features")
            if decision.probability_breakdown
            else None
        )
        pattern_blocked = False
        if decision.approved and feat and runtime.learning.enabled:
            blocked, block_reason = is_pattern_blocked(feat, closed, runtime.learning)
            if blocked:
                record_rejection(
                    self._runtime,
                    symbol=symbol,
                    source=TradeSource.TELEGRAM,
                    stage="pattern",
                    reason=block_reason,
                    direction=decision.direction,
                    llm_confidence=decision.llm_confidence,
                    predicted_probability=decision.confidence,
                    probability_features=feat,
                )
                pattern_blocked = True
                decision = decision.model_copy(
                    update={"approved": False, "bias": block_reason},
                )

        if not decision.passes_kill_switch and not pattern_blocked:
            stage = "pwin" if feat else "llm"
            record_rejection(
                self._runtime,
                symbol=symbol,
                source=TradeSource.TELEGRAM,
                stage=stage,
                reason=decision.bias or decision.ai_analysis or "Rejeitado",
                direction=decision.direction,
                llm_confidence=decision.llm_confidence or decision.confidence,
                predicted_probability=decision.confidence if stage == "pwin" else None,
                probability_features=feat,
            )

        self._log_decision(signal, decision)
        await self._dispatch(signal, decision)
        return decision

    async def _fetch_market_data(
        self,
        symbol: str,
        runtime,
    ) -> tuple[dict[str, list[list[float]]], dict]:
        """Busca OHLCV multi-TF e orderbook em paralelo."""
        timeframes = runtime.timeframes.analysis
        limit = runtime.ohlcv_limit

        ohlcv_tasks = {
            tf: self._exchange.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
            for tf in timeframes
        }
        orderbook_task = self._exchange.fetch_order_book(symbol)

        gathered = await asyncio.gather(
            *ohlcv_tasks.values(),
            orderbook_task,
            return_exceptions=True,
        )

        orderbook_result = gathered[-1]
        ohlcv_results = gathered[:-1]

        if isinstance(orderbook_result, Exception):
            raise orderbook_result

        ohlcv_by_tf: dict[str, list[list[float]]] = {}
        for tf, result in zip(ohlcv_tasks.keys(), ohlcv_results, strict=True):
            if isinstance(result, Exception):
                logger.warning("Falha OHLCV %s @ %s: %s", symbol, tf, result)
                continue
            ohlcv_by_tf[tf] = result

        if not ohlcv_by_tf:
            raise ValueError(f"Nenhum OHLCV obtido para {symbol}")

        return ohlcv_by_tf, orderbook_result

    async def _fetch_imba_timeframes(
        self,
        symbol: str,
        runtime,
    ) -> dict[str, list[list[float]]]:
        """Busca OHLCV nos timeframes IMBA presentes na config."""
        imba_tfs = imba_analysis_timeframes(runtime)
        limit = runtime.ohlcv_limit
        tasks = {
            tf: self._exchange.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
            for tf in imba_tfs
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        out: dict[str, list[list[float]]] = {}
        for tf, result in zip(tasks.keys(), results, strict=True):
            if isinstance(result, Exception):
                logger.warning("Falha IMBA OHLCV %s @ %s", symbol, tf)
                continue
            out[tf] = result
        return out

    def _enrich_with_imba(
        self,
        decision: TradeDecision,
        imba_analysis,
        imba_ohlcv: dict[str, list[list[float]]],
        signal: TelegramSignal,
        runtime,
    ) -> TradeDecision:
        """Completa níveis ausentes com referência IMBA/Telegram — não sobrescreve a IA."""
        if not decision.approved or decision.direction is None:
            return decision

        imba_dir = imba_analysis.fresh_signal_direction or imba_analysis.aligned_direction
        if imba_dir and imba_dir != decision.direction:
            return decision.model_copy(
                update={
                    "approved": False,
                    "confidence": min(decision.confidence, 0.5),
                    "bias": f"IMBA diverge: indicador={imba_dir.value} vs sinal={decision.direction.value}",
                }
            )

        config = config_from_runtime(runtime)
        imba_signal, _, smc_reject = resolve_execution_levels(
            imba_analysis,
            config,
            imba_ohlcv,
            runtime,
        )
        if imba_signal is None:
            if smc_reject:
                return decision.model_copy(
                    update={
                        "approved": False,
                        "bias": smc_reject,
                        "ai_analysis": smc_reject,
                    }
                )
            return decision

        imba_direction = (
            TradeDirection.LONG if imba_signal.side == "LONG" else TradeDirection.SHORT
        )
        return apply_execution_levels(
            decision,
            symbol=signal.symbol or "",
            direction=imba_direction,
            entry_price=imba_signal.entry_price,
            stop_loss=imba_signal.stop_loss,
            take_profit_prices=list(imba_signal.take_profits),
            execution_timeframe=runtime.timeframes.execution,
        )

    def _log_decision(self, signal: TelegramSignal, decision: TradeDecision) -> None:
        """Loga decisão com destaque para kill switch."""
        log_msg = format_trade_decision_log(decision)

        if decision.passes_kill_switch:
            logger.info("TRADE APROVADO | %s", log_msg)
            if decision.formatted_output:
                logger.info("\n%s", decision.formatted_output)
        else:
            reason = decision.bias or decision.ai_analysis
            logger.info(
                "TRADE RECUSADO | conf=%.0f%% | %s | msg_id=%s",
                decision.confidence * 100,
                reason,
                signal.message_id,
            )

    async def _dispatch(
        self,
        signal: TelegramSignal,
        decision: TradeDecision,
    ) -> None:
        """Despacha decisão ao ExecutionController se registrado."""
        if self._on_decision_callback is not None:
            try:
                await self._on_decision_callback(signal, decision)
            except Exception:
                logger.exception(
                    "Erro no callback de decisão | msg_id=%s",
                    signal.message_id,
                )

    def _reject(
        self,
        reason: str,
        *,
        symbol: str | None = None,
        stage: str = "filter",
    ) -> TradeDecision:
        if symbol:
            record_rejection(
                self._runtime,
                symbol=symbol,
                source=TradeSource.TELEGRAM,
                stage=stage,
                reason=reason,
            )
        return TradeDecision(
            approved=False,
            confidence=0.0,
            ai_analysis=reason,
        )
