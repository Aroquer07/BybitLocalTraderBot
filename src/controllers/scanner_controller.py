"""Controller de scan autônomo — watchlist IMBA multi-TF + análise técnica completa."""

from __future__ import annotations

import asyncio

from src.config.settings import Settings
from src.controllers.execution_controller import ExecutionController
from src.models.schemas import (
    ImbaAnalysis,
    TradeDecision,
    TradeDirection,
    TradeSource,
)
from src.services.exchange_client import ExchangeClient
from src.services.llm_client import LLMClient
from src.services.runtime_config_store import RuntimeConfigStore
from src.services.watchlist_loader import WatchlistStore, normalize_watchlist_symbols
from src.strategies.market_screener import MarketScreener
from src.strategies.imba_analyzer import (
    analyze_multi_timeframe,
    config_from_runtime,
    imba_analysis_timeframes,
    resolve_entry_direction,
)
from src.strategies.execution_levels import resolve_execution_levels, resolve_signal_execution_levels
from src.strategies.indicator_modules.combined import evaluate_combined_setup
from src.strategies.indicator_modules.sniper_strategy import evaluate_sniper_setup
from src.strategies.imba_algo import ImbaSignal
from src.strategies.trade_validation import (
    apply_execution_levels,
    validate_execution_decision,
)
from src.strategies.technical_analysis import TechnicalAnalysisEngine
from src.services.rejection_log import record_rejection
from src.services.approval_log import record_approval
from src.services.trade_learning import is_pattern_blocked
from src.config.strategy_config import effective_scanner_quality
from src.strategies.scanner_autonomous import (
    build_autonomous_scanner_decision,
    build_combined_scanner_decision,
    build_sniper_scanner_decision,
    synthetic_imba_analysis,
)
from src.strategies.scanner_filters import evaluate_scanner_setup
from src.strategies.win_probability import enrich_decision_with_win_probability
from src.utils.logger import get_logger

logger = get_logger(__name__)

_LEVELS_REJECTION_MARKERS = (
    "TP1 com R:R",
    "SL deve",
    "TPs LONG",
    "TPs SHORT",
    "Níveis de execução",
    "IA deve validar",
    "IA não definiu",
    "Distância entrada-SL",
)


def _scanner_rejection_stage(reason: str, *, use_llm: bool) -> str:
    if any(marker in reason for marker in _LEVELS_REJECTION_MARKERS):
        return "levels"
    return "llm" if use_llm else "decision"


class ScannerController:
    """Varre watchlist: IMBA + RSI/MACD/Fib/confluência → LLM valida coerência."""

    def __init__(
        self,
        settings: Settings,
        exchange: ExchangeClient,
        llm: LLMClient,
        execution: ExecutionController,
        runtime_store: RuntimeConfigStore,
        ta_engine: TechnicalAnalysisEngine,
    ) -> None:
        self._settings = settings
        self._exchange = exchange
        self._llm = llm
        self._execution = execution
        self._runtime = runtime_store
        self._ta = ta_engine
        self._watchlist: WatchlistStore | None = None
        self._screener = MarketScreener(exchange)
        self._screener_task: asyncio.Task[None] | None = None
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        runtime = self._runtime.reload()
        if not runtime.scanner.enabled:
            logger.info("Scanner IMBA desabilitado (scanner.enabled=false)")
            return
        if self._task and not self._task.done():
            return
        self._watchlist = WatchlistStore(runtime.scanner.watchlist_path)
        self._running = True
        self._watchlist.reload()
        if runtime.strategies.scanner.screener and runtime.scanner.screener.enabled:
            self._kickoff_screener_refresh(runtime.scanner.screener)
        self._task = asyncio.create_task(self._loop(), name="imba-scanner")
        logger.info(
            "Scanner IMBA iniciado | strategy=%s | mode=%s | interval=%ds | watchlist=%s (%s) | TFs=%s | screener=%s/%s | llm=%s",
            runtime.strategies.scanner.entry_strategy,
            runtime.strategies.scanner.mode,
            runtime.scanner.interval_seconds,
            self._watchlist.symbols,
            runtime.scanner.watchlist_path,
            runtime.timeframes.analysis,
            "on" if runtime.scanner.screener.enabled and runtime.strategies.scanner.screener else "off",
            "discovery" if runtime.scanner.screener.discovery_only else "filter",
            "on" if runtime.strategies.scanner.llm else "off",
        )

    async def stop(self) -> None:
        self._running = False
        if self._screener_task and not self._screener_task.done():
            self._screener_task.cancel()
            try:
                await self._screener_task
            except asyncio.CancelledError:
                pass
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while self._running:
            runtime = self._runtime.reload()
            try:
                await self._execution.sync_closed_positions()
                await self._scan_all(runtime)
            except Exception:
                logger.exception("Erro no ciclo do scanner IMBA")
            await asyncio.sleep(runtime.scanner.interval_seconds)

    async def _scan_all(self, runtime) -> None:
        if self._watchlist is None:
            self._watchlist = WatchlistStore(runtime.scanner.watchlist_path)

        symbols = await self._resolve_scan_symbols(runtime)
        if not symbols:
            logger.warning(
                "Nenhum símbolo para escanear | screener=%s | watchlist=%s",
                runtime.scanner.screener.enabled,
                runtime.scanner.watchlist_path,
            )
            return

        slots = await self._execution.available_trade_slots()
        if slots <= 0:
            limit = runtime.effective_max_concurrent_trades(self._settings.bybit_mode)
            open_count = await self._execution.open_position_count()
            logger.debug(
                "Scanner sem slots | %d/%d posições abertas",
                open_count,
                limit,
            )
            return

        candidates = await self._scan_symbols_batched(symbols, runtime, slots)

        if not candidates:
            return

        candidates.sort(key=lambda d: d.confidence, reverse=True)
        batch = candidates[:slots]
        logger.info(
            "Scanner batch | %d aprovado(s) | abrindo %d | slots=%d",
            len(candidates),
            len(batch),
            slots,
        )
        await self._execution.execute_decisions_batch(batch)

    async def _scan_symbols_batched(
        self,
        symbols: list[str],
        runtime,
        slots: int,
    ) -> list[TradeDecision]:
        """Avalia símbolos em lotes asyncio — até `slots` candidatos."""
        cfg = runtime.scanner
        cap = min(len(symbols), cfg.screener.max_scan_symbols)
        to_scan = symbols[:cap]

        async def _eval_symbol(symbol: str) -> TradeDecision | None:
            if not self._running:
                return None
            if self._execution.journal.has_open_position(symbol):
                return None
            try:
                return await self._evaluate_symbol(symbol, runtime)
            except Exception:
                logger.exception("Erro ao escanear %s", symbol)
                return None

        collected: list[TradeDecision] = []

        def _on_batch(start: int, end: int, _total: int) -> None:
            logger.info(
                "Scanner lote | %d-%d/%d | candidatos=%d",
                start + 1,
                end,
                len(to_scan),
                len(collected),
            )

        for start in range(0, len(to_scan), cfg.scan_batch_size):
            if not self._running or len(collected) >= slots:
                break
            chunk = to_scan[start : start + cfg.scan_batch_size]
            sem = asyncio.Semaphore(cfg.scan_concurrency)

            async def _run(sym: str) -> TradeDecision | None:
                async with sem:
                    return await _eval_symbol(sym)

            batch = await asyncio.gather(*[_run(s) for s in chunk])
            for decision in batch:
                if decision is not None:
                    collected.append(decision)
                    if len(collected) >= slots:
                        break
            _on_batch(start, min(start + len(chunk), len(to_scan)), len(collected))

        return collected[:slots]

    async def _resolve_scan_symbols(self, runtime) -> list[str]:
        """Watchlist fixa + candidatos RSI Heatmap (screener). Entrada = ALGO+Kalman."""
        screener_cfg = runtime.scanner.screener
        pipeline = runtime.strategies.scanner
        static: list[str] = []

        if screener_cfg.merge_static_watchlist or not screener_cfg.enabled or not pipeline.screener:
            static = self._watchlist.reload() if self._watchlist else []

        dynamic: list[str] = []
        if screener_cfg.enabled and pipeline.screener:
            if self._screener.needs_refresh(screener_cfg.interval_seconds):
                self._kickoff_screener_refresh(screener_cfg)
            dynamic = self._screener.symbols

        static_norm = normalize_watchlist_symbols(static)
        static_set = set(static_norm)
        screener_extras: list[str] = []
        for sym in normalize_watchlist_symbols(dynamic):
            if sym not in static_set and sym not in screener_extras:
                screener_extras.append(sym)

        max_total = screener_cfg.max_scan_symbols
        max_extras = max(max_total - len(static_norm), 0)
        merged = static_norm + screener_extras[:max_extras]

        if dynamic:
            logger.info(
                "Universo de scan | watchlist=%d | screener=%d | novos=%d | total=%d",
                len(static_norm),
                len(dynamic),
                len(screener_extras[:max_extras]),
                len(merged),
            )
        return merged

    def _kickoff_screener_refresh(self, screener_cfg) -> None:
        """Roda screener em background — não bloqueia startup nem ciclo do scanner."""
        if self._screener_task and not self._screener_task.done():
            return

        async def _run() -> None:
            try:
                await self._screener.refresh(screener_cfg)
            except Exception:
                logger.exception("Falha no screener automático — usando cache/watchlist")
            finally:
                self._screener_task = None

        self._screener_task = asyncio.create_task(_run(), name="market-screener")
        logger.info("Screener iniciado em background (watchlist segue ativa)")

    async def _fetch_ohlcv_map(
        self,
        symbol: str,
        timeframes: list[str],
        runtime,
    ) -> dict[str, list[list[float]]]:
        """Busca OHLCV em paralelo para vários TFs (com cache na exchange)."""
        limit = max(runtime.ohlcv_limit, 50)
        unique = list(dict.fromkeys(timeframes))
        if not unique:
            return {}

        tasks = {
            tf: self._exchange.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
            for tf in unique
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        out: dict[str, list[list[float]]] = {}
        for tf, result in zip(tasks.keys(), results, strict=True):
            if isinstance(result, Exception):
                logger.warning("Falha OHLCV %s @ %s", symbol, tf)
                continue
            if result:
                out[tf] = result
        return out

    @staticmethod
    def _combined_fast_timeframes(runtime) -> list[str]:
        """TFs mínimos para indicadores combinados (fase rápida)."""
        exec_tf = runtime.timeframes.execution
        tfs = {exec_tf}
        if exec_tf != "5m":
            tfs.add("5m")
        return sorted(tfs)

    def _remaining_analysis_timeframes(
        self,
        runtime,
        loaded: set[str],
    ) -> list[str]:
        return [tf for tf in runtime.timeframes.analysis if tf not in loaded]

    async def _fetch_market_data(
        self,
        symbol: str,
        runtime,
    ) -> tuple[dict[str, list[list[float]]], dict]:
        """OHLCV em todos os TFs de análise + orderbook (RSI, MACD, Fib, etc.)."""
        timeframes = runtime.timeframes.analysis
        orderbook_task = self._exchange.fetch_order_book(symbol)
        ohlcv_task = self._fetch_ohlcv_map(symbol, timeframes, runtime)
        ohlcv_by_tf, orderbook_result = await asyncio.gather(
            ohlcv_task,
            orderbook_task,
            return_exceptions=True,
        )

        if isinstance(ohlcv_by_tf, Exception):
            raise ValueError(f"Nenhum OHLCV obtido para {symbol}") from ohlcv_by_tf

        if isinstance(orderbook_result, Exception):
            orderbook: dict = {}
            logger.warning("Falha orderbook %s: %s", symbol, orderbook_result)
        else:
            orderbook = orderbook_result

        if not ohlcv_by_tf:
            raise ValueError(f"Nenhum OHLCV obtido para {symbol}")

        return ohlcv_by_tf, orderbook

    async def _evaluate_symbol(self, symbol: str, runtime) -> TradeDecision | None:
        pipeline = runtime.strategies.scanner
        if pipeline.entry_strategy == "combined":
            return await self._evaluate_combined(symbol, runtime)
        if pipeline.entry_strategy == "sniper":
            return await self._evaluate_sniper(symbol, runtime)
        return await self._evaluate_imba(symbol, runtime)

    async def _evaluate_combined(self, symbol: str, runtime) -> TradeDecision | None:
        pipeline = runtime.strategies.scanner
        screener_bias = None
        screener_cfg = runtime.scanner.screener
        if (
            pipeline.screener
            and screener_cfg.enabled
            and not screener_cfg.discovery_only
        ):
            screener_bias = self._screener.trend_bias_for(symbol)
            if screener_bias is None and self._screener.symbols and symbol in self._screener.symbols:
                logger.debug("Sem bias de tendência screener | %s — ignorado", symbol)
                return None

        try:
            ohlcv_by_tf = await self._fetch_ohlcv_map(
                symbol,
                self._combined_fast_timeframes(runtime),
                runtime,
            )
        except Exception:
            return None

        exec_tf = runtime.timeframes.execution
        exec_ohlcv = ohlcv_by_tf.get(exec_tf)
        if not exec_ohlcv:
            return None

        htf_ohlcv = ohlcv_by_tf.get("5m") if exec_tf != "5m" else None
        combined, module_results = evaluate_combined_setup(
            exec_ohlcv,
            ohlcv_htf=htf_ohlcv,
            config=pipeline.indicators,
            screener_bias=screener_bias,
        )
        if combined is None:
            for mod in module_results:
                if not mod.triggered and mod.reason not in ("desabilitado",):
                    logger.debug("Combined | %s | %s | %s", symbol, mod.name, mod.reason)
            return None

        extra_tfs = set(self._remaining_analysis_timeframes(runtime, set(ohlcv_by_tf.keys())))
        if pipeline.smc and runtime.smc.enabled:
            extra_tfs.add(runtime.smc.structure_timeframe)
        if extra_tfs:
            ohlcv_by_tf.update(
                await self._fetch_ohlcv_map(symbol, sorted(extra_tfs), runtime)
            )

        try:
            orderbook = await self._exchange.fetch_order_book(symbol)
        except Exception:
            logger.warning("Falha orderbook %s — segue sem book", symbol)
            orderbook = {}

        raw_signal = ImbaSignal(
            side=combined.direction,
            entry_price=combined.entry_price,
            stop_loss=combined.stop_loss,
            take_profits=combined.take_profits,
            levels={},
        )
        exec_signal, smc_meta, smc_reject = resolve_signal_execution_levels(
            raw_signal,
            symbol,
            ohlcv_by_tf,
            runtime,
        )
        if exec_signal is None:
            if smc_reject and pipeline.smc:
                record_rejection(
                    self._runtime,
                    symbol=symbol,
                    source=TradeSource.SCANNER,
                    stage="smc",
                    reason=smc_reject,
                    direction=TradeDirection.LONG if combined.direction == "LONG" else TradeDirection.SHORT,
                    **self._log_kwargs(
                        ohlcv_by_tf=ohlcv_by_tf,
                        pipeline=pipeline,
                        module_results=module_results,
                    ),
                )
                logger.info("Scanner SMC | %s | %s", symbol, smc_reject)
            return None

        direction = (
            TradeDirection.LONG if exec_signal.side == "LONG" else TradeDirection.SHORT
        )

        try:
            market_state = self._ta.build_market_state(
                symbol=symbol,
                ohlcv_by_timeframe=ohlcv_by_tf,
                orderbook=orderbook if orderbook else None,
            )
        except Exception:
            logger.exception("Falha market_state | %s", symbol)
            return None

        quality = effective_scanner_quality(runtime.scanner.quality, pipeline)
        if pipeline.entry_strategy == "combined":
            quality = quality.model_copy(
                update={
                    "require_imba_tf_align": False,
                    "min_imba_confidence": quality.min_combined_confidence,
                    "require_confluence_align": False,
                    "min_confluence_score": 45,
                    "min_confluence_spread": 6,
                    "min_volume_ratio": 0.05,
                    "max_sl_atr_multiple": 15.0,
                }
            )

        if pipeline.quality_filters:
            analysis_stub = synthetic_imba_analysis(symbol, combined)
            filter_verdict = evaluate_scanner_setup(
                direction=direction,
                analysis=analysis_stub,
                imba_signal=exec_signal,
                market_state=market_state,
                filters=quality,
            )
            if not filter_verdict.passed:
                record_rejection(
                    self._runtime,
                    symbol=symbol,
                    source=TradeSource.SCANNER,
                    stage="filters",
                    reason=filter_verdict.reason,
                    direction=direction,
                    **self._log_kwargs(
                        ohlcv_by_tf=ohlcv_by_tf,
                        pipeline=pipeline,
                        module_results=module_results,
                    ),
                )
                logger.info("Scanner filtrado | %s | %s", symbol, filter_verdict.reason)
                return None

        logger.info(
            "Scanner COMBINED | %s | %s %s | modules=%s",
            symbol,
            combined.regime,
            combined.direction,
            ",".join(combined.modules),
        )

        decision = build_combined_scanner_decision(
            symbol=symbol,
            signal=combined,
            runtime=runtime,
            confluence_score=(
                market_state.confluence.long_score
                if direction == TradeDirection.LONG
                else market_state.confluence.short_score
            )
            if market_state.confluence
            else 70,
        )
        decision = apply_execution_levels(
            decision,
            symbol=symbol,
            direction=direction,
            entry_price=exec_signal.entry_price,
            stop_loss=exec_signal.stop_loss,
            take_profit_prices=list(exec_signal.take_profits),
            execution_timeframe=exec_tf,
        )
        decision = validate_execution_decision(decision, runtime)
        decision = decision.model_copy(
            update={
                "source": TradeSource.SCANNER,
                "confidence_threshold": runtime.confidence.scanner,
            }
        )

        if not decision.approved:
            reason = decision.bias or decision.ai_analysis or "Níveis inválidos"
            record_rejection(
                self._runtime,
                symbol=symbol,
                source=TradeSource.SCANNER,
                stage=_scanner_rejection_stage(reason, use_llm=False),
                reason=reason,
                direction=direction,
                **self._log_kwargs(
                    ohlcv_by_tf=ohlcv_by_tf,
                    pipeline=pipeline,
                    module_results=module_results,
                    decision=decision,
                ),
            )
            logger.info("Scanner recusado | %s | %s", symbol, reason[:200])
            return None

        analysis = synthetic_imba_analysis(symbol, combined)
        return await self._finalize_scanner_decision(
            symbol,
            decision,
            analysis,
            market_state,
            runtime,
            pipeline,
            quality,
            use_llm=False,
            ohlcv_by_tf=ohlcv_by_tf,
            module_results=module_results,
        )

    async def _evaluate_sniper(self, symbol: str, runtime) -> TradeDecision | None:
        """Sniper Entry (SL/TP ATR) + confirmação Breakout Probability."""
        pipeline = runtime.strategies.scanner

        try:
            ohlcv_by_tf = await self._fetch_ohlcv_map(
                symbol,
                self._combined_fast_timeframes(runtime),
                runtime,
            )
        except Exception:
            return None

        exec_tf = runtime.timeframes.execution
        exec_ohlcv = ohlcv_by_tf.get(exec_tf)
        if not exec_ohlcv:
            return None

        htf_ohlcv = ohlcv_by_tf.get("5m") if exec_tf != "5m" else None
        sniper_signal, module_results, reject = evaluate_sniper_setup(
            exec_ohlcv,
            ohlcv_htf=htf_ohlcv,
            config=pipeline.indicators,
        )
        if sniper_signal is None:
            for mod in module_results:
                if not mod.triggered and mod.reason not in ("desabilitado",):
                    logger.debug("Sniper | %s | %s | %s", symbol, mod.name, mod.reason)
            if reject:
                logger.debug("Sniper rejeitado | %s | %s", symbol, reject)
            return None

        extra_tfs = set(self._remaining_analysis_timeframes(runtime, set(ohlcv_by_tf.keys())))
        if extra_tfs:
            ohlcv_by_tf.update(
                await self._fetch_ohlcv_map(symbol, sorted(extra_tfs), runtime)
            )

        try:
            orderbook = await self._exchange.fetch_order_book(symbol)
        except Exception:
            logger.warning("Falha orderbook %s — segue sem book", symbol)
            orderbook = {}

        exec_signal = ImbaSignal(
            side=sniper_signal.direction,
            entry_price=sniper_signal.entry_price,
            stop_loss=sniper_signal.stop_loss,
            take_profits=sniper_signal.take_profits,
            levels={},
        )

        direction = (
            TradeDirection.LONG
            if exec_signal.side == "LONG"
            else TradeDirection.SHORT
        )

        try:
            market_state = self._ta.build_market_state(
                symbol=symbol,
                ohlcv_by_timeframe=ohlcv_by_tf,
                orderbook=orderbook if orderbook else None,
            )
        except Exception:
            logger.exception("Falha market_state | %s", symbol)
            return None

        quality = effective_scanner_quality(runtime.scanner.quality, pipeline)
        quality = quality.model_copy(
            update={
                "require_imba_tf_align": False,
                "min_imba_confidence": quality.min_combined_confidence,
                "require_confluence_align": False,
                "min_confluence_score": 45,
                "min_confluence_spread": 6,
                "min_volume_ratio": 0.05,
                "max_sl_atr_multiple": 15.0,
            }
        )

        if pipeline.quality_filters:
            analysis_stub = synthetic_imba_analysis(symbol, sniper_signal)
            filter_verdict = evaluate_scanner_setup(
                direction=direction,
                analysis=analysis_stub,
                imba_signal=exec_signal,
                market_state=market_state,
                filters=quality,
            )
            if not filter_verdict.passed:
                record_rejection(
                    self._runtime,
                    symbol=symbol,
                    source=TradeSource.SCANNER,
                    stage="filters",
                    reason=filter_verdict.reason,
                    direction=direction,
                    **self._log_kwargs(
                        ohlcv_by_tf=ohlcv_by_tf,
                        pipeline=pipeline,
                        module_results=module_results,
                    ),
                )
                logger.info("Scanner filtrado | %s | %s", symbol, filter_verdict.reason)
                return None

        logger.info(
            "Scanner SNIPER | %s | %s %s | modules=%s",
            symbol,
            sniper_signal.regime,
            sniper_signal.direction,
            ",".join(sniper_signal.modules),
        )

        decision = build_sniper_scanner_decision(
            symbol=symbol,
            signal=sniper_signal,
            runtime=runtime,
            confluence_score=(
                market_state.confluence.long_score
                if direction == TradeDirection.LONG
                else market_state.confluence.short_score
            )
            if market_state.confluence
            else 70,
        )
        decision = apply_execution_levels(
            decision,
            symbol=symbol,
            direction=direction,
            entry_price=exec_signal.entry_price,
            stop_loss=exec_signal.stop_loss,
            take_profit_prices=list(exec_signal.take_profits),
            execution_timeframe=exec_tf,
        )
        decision = validate_execution_decision(
            decision,
            runtime,
            require_weighted_expectancy=False,
            sniper_levels=True,
        )
        decision = decision.model_copy(
            update={
                "source": TradeSource.SCANNER,
                "confidence_threshold": runtime.confidence.scanner,
            }
        )

        if not decision.approved:
            reason = decision.bias or decision.ai_analysis or "Níveis inválidos"
            record_rejection(
                self._runtime,
                symbol=symbol,
                source=TradeSource.SCANNER,
                stage=_scanner_rejection_stage(reason, use_llm=False),
                reason=reason,
                direction=direction,
                **self._log_kwargs(
                    ohlcv_by_tf=ohlcv_by_tf,
                    pipeline=pipeline,
                    module_results=module_results,
                    decision=decision,
                ),
            )
            logger.info("Scanner recusado | %s | %s", symbol, reason[:200])
            return None

        analysis = synthetic_imba_analysis(symbol, sniper_signal)
        return await self._finalize_scanner_decision(
            symbol,
            decision,
            analysis,
            market_state,
            runtime,
            pipeline,
            quality,
            use_llm=False,
            ohlcv_by_tf=ohlcv_by_tf,
            module_results=module_results,
        )

    @staticmethod
    def _decision_levels(decision: TradeDecision) -> dict[str, float | list[float] | None]:
        tps = [tp.price for tp in decision.take_profits] if decision.take_profits else []
        return {
            "entry": decision.entry_price,
            "stop_loss": decision.stop_loss,
            "take_profits": tps,
        }

    def _log_kwargs(
        self,
        *,
        ohlcv_by_tf: dict[str, list[list[float]]] | None,
        pipeline,
        module_results=None,
        decision: TradeDecision | None = None,
    ) -> dict:
        return {
            "ohlcv_by_tf": ohlcv_by_tf,
            "indicators_config": pipeline.indicators if pipeline else None,
            "entry_strategy": pipeline.entry_strategy if pipeline else None,
            "module_results": module_results,
            "levels": self._decision_levels(decision) if decision else None,
        }

    @staticmethod
    def _imba_higher_tf_confirms(
        analysis: ImbaAnalysis,
        direction: TradeDirection,
        *,
        min_matches: int = 1,
    ) -> bool:
        """Exige ≥N de 15m/30m/1h alinhados com a direção do sinal 5m."""
        want = "LONG" if direction == TradeDirection.LONG else "SHORT"
        matches = 0
        for tf in ("15m", "30m", "1h"):
            snap = analysis.timeframes.get(tf)
            if snap and snap.trend == want:
                matches += 1
        return matches >= min_matches

    async def _evaluate_imba(self, symbol: str, runtime) -> TradeDecision | None:
        pipeline = runtime.strategies.scanner
        if not pipeline.imba:
            return None

        try:
            ohlcv_by_tf, orderbook = await self._fetch_market_data(symbol, runtime)
        except ValueError:
            return None

        imba_tfs = imba_analysis_timeframes(runtime)
        imba_ohlcv = {tf: ohlcv_by_tf[tf] for tf in imba_tfs if tf in ohlcv_by_tf}
        if not imba_ohlcv:
            return None

        config = config_from_runtime(runtime)
        analysis = analyze_multi_timeframe(
            symbol,
            imba_ohlcv,
            config,
            settings=runtime,
        )

        exec_tf = runtime.timeframes.execution
        direction = resolve_entry_direction(
            analysis,
            exec_tf=exec_tf,
            require_fresh=runtime.imba.require_fresh_signal,
        )
        if direction is None:
            logger.debug("Sem direção IMBA | %s | %s", symbol, analysis.summary)
            return None
        if not self._imba_higher_tf_confirms(
            analysis,
            direction,
            min_matches=runtime.imba.min_htf_confirm,
        ):
            logger.debug(
                "IMBA sem confirmação HTF (%d/%d) | %s",
                runtime.imba.min_htf_confirm,
                3,
                symbol,
            )
            return None

        analysis = analysis.model_copy(update={"fresh_signal_direction": direction})

        quality = effective_scanner_quality(runtime.scanner.quality, pipeline)
        if analysis.confidence_score < quality.min_imba_confidence:
            logger.debug(
                "Score IMBA baixo | %s | %.0f%% < %.0f%%",
                symbol,
                analysis.confidence_score * 100,
                quality.min_imba_confidence * 100,
            )
            return None

        imba_signal, smc_meta, smc_reject = resolve_execution_levels(
            analysis,
            config,
            imba_ohlcv,
            runtime,
        )
        if imba_signal is None:
            stage = "smc" if smc_reject and pipeline.smc else "levels"
            if smc_reject:
                record_rejection(
                    self._runtime,
                    symbol=symbol,
                    source=TradeSource.SCANNER,
                    stage=stage,
                    reason=smc_reject,
                    direction=direction,
                    **self._log_kwargs(
                        ohlcv_by_tf=ohlcv_by_tf,
                        pipeline=pipeline,
                    ),
                )
                logger.info("Scanner níveis | %s | %s", symbol, smc_reject)
            return None

        direction = (
            TradeDirection.LONG if imba_signal.side == "LONG" else TradeDirection.SHORT
        )

        try:
            market_state = self._ta.build_market_state(
                symbol=symbol,
                ohlcv_by_timeframe=ohlcv_by_tf,
                orderbook=orderbook if orderbook else None,
            )
            market_state = market_state.model_copy(update={"imba_analysis": analysis})
        except Exception:
            logger.exception("Falha market_state | %s", symbol)
            return None

        exec_tf = runtime.timeframes.execution
        exec_snap = market_state.timeframes.get(exec_tf)
        kalman_ind = exec_snap.indicators if exec_snap else {}
        from src.strategies.kalman_entry import kalman_allows_entry

        kalman_verdict = kalman_allows_entry(
            direction,
            kalman_ind,
            require_reversal=pipeline.kalman_hard_block,
        )
        if not kalman_verdict.passed:
            record_rejection(
                self._runtime,
                symbol=symbol,
                source=TradeSource.SCANNER,
                stage="kalman",
                reason=kalman_verdict.reason,
                direction=direction,
                **self._log_kwargs(
                    ohlcv_by_tf=ohlcv_by_tf,
                    pipeline=pipeline,
                ),
            )
            logger.info("Scanner Kalman | %s | %s", symbol, kalman_verdict.reason)
            return None

        if pipeline.quality_filters:
            filter_verdict = evaluate_scanner_setup(
                direction=direction,
                analysis=analysis,
                imba_signal=imba_signal,
                market_state=market_state,
                filters=quality,
            )
            if not filter_verdict.passed:
                record_rejection(
                    self._runtime,
                    symbol=symbol,
                    source=TradeSource.SCANNER,
                    stage="filters",
                    reason=filter_verdict.reason,
                    direction=direction,
                    **self._log_kwargs(
                        ohlcv_by_tf=ohlcv_by_tf,
                        pipeline=pipeline,
                    ),
                )
                logger.info(
                    "Scanner filtrado | %s | %s",
                    symbol,
                    filter_verdict.reason,
                )
                return None

        conf = market_state.confluence
        logger.info(
            "Scanner TA | %s | TFs=%s | confluence=%s (L=%d S=%d) | %s",
            symbol,
            list(market_state.timeframes.keys()),
            conf.recommendation if conf else "N/A",
            conf.long_score if conf else 0,
            conf.short_score if conf else 0,
            analysis.summary,
        )

        use_llm = pipeline.llm
        if use_llm:
            decision = await self._llm.evaluate_scanner_opportunity(market_state, imba_signal)
            if decision.approved:
                llm_conf = (
                    decision.llm_confidence
                    if decision.llm_confidence is not None
                    else decision.confidence
                )
                if llm_conf < quality.min_llm_confidence:
                    decision = decision.model_copy(
                        update={
                            "approved": False,
                            "ai_analysis": (
                                f"LLM confiança {llm_conf:.0%} < {quality.min_llm_confidence:.0%}"
                            ),
                        }
                    )
                else:
                    decision = apply_execution_levels(
                        decision,
                        symbol=symbol,
                        direction=direction,
                        entry_price=imba_signal.entry_price,
                        stop_loss=imba_signal.stop_loss,
                        take_profit_prices=list(imba_signal.take_profits),
                        execution_timeframe=runtime.timeframes.execution,
                    )
        else:
            decision = build_autonomous_scanner_decision(
                symbol=symbol,
                direction=direction,
                analysis=analysis,
                market_state=market_state,
                imba_signal=imba_signal,
                runtime=runtime,
            )
            decision = apply_execution_levels(
                decision,
                symbol=symbol,
                direction=direction,
                entry_price=imba_signal.entry_price,
                stop_loss=imba_signal.stop_loss,
                take_profit_prices=list(imba_signal.take_profits),
                execution_timeframe=runtime.timeframes.execution,
            )

        decision = validate_execution_decision(decision, runtime)
        decision = decision.model_copy(
            update={
                "source": TradeSource.SCANNER,
                "confidence_threshold": runtime.confidence.scanner,
            }
        )

        if not decision.approved:
            reason = (
                decision.bias
                or decision.tp_sl_quality
                or decision.ai_analysis
                or ("LLM rejeitou" if use_llm else "Níveis inválidos")
            )
            stage = _scanner_rejection_stage(reason, use_llm=use_llm)
            llm_conf = (
                decision.llm_confidence
                if decision.llm_confidence is not None
                else decision.confidence
            )
            record_rejection(
                self._runtime,
                symbol=symbol,
                source=TradeSource.SCANNER,
                stage=stage,
                reason=reason,
                direction=direction,
                llm_confidence=llm_conf if use_llm else None,
                **self._log_kwargs(
                    ohlcv_by_tf=ohlcv_by_tf,
                    pipeline=pipeline,
                    decision=decision,
                ),
            )
            logger.info(
                "Scanner recusado %s | %s | %s=%.0f%% | %s",
                stage,
                symbol,
                "llm" if use_llm else "conf",
                llm_conf * 100,
                reason if stage == "levels" else reason[:200],
            )
            return None

        return await self._finalize_scanner_decision(
            symbol,
            decision,
            analysis,
            market_state,
            runtime,
            pipeline,
            quality,
            use_llm=use_llm,
            ohlcv_by_tf=ohlcv_by_tf,
        )

    async def _finalize_scanner_decision(
        self,
        symbol: str,
        decision: TradeDecision,
        analysis,
        market_state,
        runtime,
        pipeline,
        quality,
        *,
        use_llm: bool,
        ohlcv_by_tf: dict[str, list[list[float]]] | None = None,
        module_results=None,
    ) -> TradeDecision | None:
        if pipeline.pwin:
            try:
                closed = self._execution.journal.list_closed()
                decision = enrich_decision_with_win_probability(
                    decision,
                    analysis,
                    market_state,
                    source=TradeSource.SCANNER,
                    confidence_threshold=runtime.confidence.scanner,
                    closed_trades=closed,
                    learning_config=runtime.learning if pipeline.learning else None,
                    quality_config=quality,
                    entry_strategy=pipeline.entry_strategy,
                )
            except Exception:
                logger.exception("Falha P(win) | %s", symbol)
                return None
        else:
            decision = decision.model_copy(
                update={
                    "passes_kill_switch": True,
                    "confidence": max(decision.confidence, runtime.confidence.scanner),
                }
            )

        feat = (
            decision.probability_breakdown.get("features")
            if decision.probability_breakdown
            else None
        )
        if feat and runtime.learning.enabled and pipeline.learning:
            closed = self._execution.journal.list_closed()
            blocked, block_reason = is_pattern_blocked(feat, closed, runtime.learning)
            if blocked:
                record_rejection(
                    self._runtime,
                    symbol=symbol,
                    source=TradeSource.SCANNER,
                    stage="pattern",
                    reason=block_reason,
                    direction=decision.direction,
                    llm_confidence=decision.llm_confidence,
                    predicted_probability=decision.confidence,
                    probability_features=feat,
                    **self._log_kwargs(
                        ohlcv_by_tf=ohlcv_by_tf,
                        pipeline=pipeline,
                        module_results=module_results,
                        decision=decision,
                    ),
                )
                logger.info("Scanner bloqueado | %s | %s", symbol, block_reason)
                return None

        if pipeline.pwin and not decision.passes_kill_switch:
            pwin_thr = (
                decision.probability_breakdown.get("effective_threshold")
                if decision.probability_breakdown
                else runtime.confidence.scanner
            )
            record_rejection(
                self._runtime,
                symbol=symbol,
                source=TradeSource.SCANNER,
                stage="pwin",
                reason=f"P(win) {decision.confidence:.0%} < {pwin_thr:.0%}",
                direction=decision.direction,
                llm_confidence=decision.llm_confidence,
                predicted_probability=decision.confidence,
                probability_features=feat,
                **self._log_kwargs(
                    ohlcv_by_tf=ohlcv_by_tf,
                    pipeline=pipeline,
                    module_results=module_results,
                    decision=decision,
                ),
            )
            logger.info(
                "Scanner recusado P(win) | %s | prob=%.0f%% | %s",
                symbol,
                decision.confidence * 100,
                decision.bias or decision.ai_analysis,
            )
            return None

        pat = feat.get("pattern_name", "") if feat else ""
        strategy_label = pipeline.entry_strategy
        logger.info(
            "Scanner APROVADO | %s %s | strategy=%s | P(win)=%.0f%% | lev=%sx | %s",
            decision.direction.value if decision.direction else "?",
            symbol,
            strategy_label,
            decision.confidence * 100,
            decision.leverage,
            analysis.summary,
        )
        if decision.direction:
            record_approval(
                self._runtime,
                symbol=symbol,
                source=TradeSource.SCANNER,
                direction=decision.direction,
                strategy=strategy_label,
                summary=analysis.summary or "",
                confidence=decision.confidence,
                predicted_probability=decision.confidence,
                probability_features=feat,
                **self._log_kwargs(
                    ohlcv_by_tf=ohlcv_by_tf,
                    pipeline=pipeline,
                    module_results=module_results,
                    decision=decision,
                ),
            )
        return decision
