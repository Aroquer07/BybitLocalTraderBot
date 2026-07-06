"""Cliente CCXT assíncrono isolado para Bybit V5 (testnet, demo ou live)."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import ccxt.async_support as ccxt_async
from ccxt.base.errors import AuthenticationError, BadRequest, ExchangeError, OrderNotFound

from src.config.settings import Settings
from src.models.schemas import TradeDirection
from src.services.ohlcv_cache import OhlcvCache
from src.services.runtime_config_store import RuntimeConfigStore
from src.utils.logger import get_logger

logger = get_logger(__name__)

ABSOLUTE_MAX_LEVERAGE = 30

_RISK_TIER_LEVERAGE_RE = re.compile(
    r"adjust your leverage to (\d+) or below",
    re.IGNORECASE,
)
_MAX_LEVERAGE_ERROR_RE = re.compile(r"maxLeverage \[(\d+)\]", re.IGNORECASE)


def _parse_risk_tier_max_leverage(message: str) -> int | None:
    """Extrai alavancagem máxima sugerida pela Bybit no erro 110090."""
    match = _RISK_TIER_LEVERAGE_RE.search(message)
    if not match:
        return None
    return int(match.group(1))


def _parse_max_leverage_from_error(message: str) -> int | None:
    """Extrai alavancagem máxima do par no erro 110013 (valor em centésimos)."""
    match = _MAX_LEVERAGE_ERROR_RE.search(message)
    if not match:
        return None
    return int(match.group(1)) // 100


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clamp_leverage_hard(
    leverage: int,
    *,
    config_max: int | None = None,
    market_max: int | None = None,
) -> int:
    """Hard cap absoluto (30x) antes de qualquer chamada à API."""
    capped = min(int(leverage), ABSOLUTE_MAX_LEVERAGE)
    if config_max is not None:
        capped = min(capped, int(config_max))
    if market_max is not None:
        capped = min(capped, int(market_max))
    return max(1, capped)


class ExchangeClient:
    """
    Wrapper CCXT para Bybit V5 (testnet, demo paper ou live conforme settings).

    Todas as operações são assíncronas e isoladas — falhas não propagam
    para outros módulos do sistema.
    """

    def __init__(
        self,
        settings: Settings,
        runtime_store: RuntimeConfigStore | None = None,
    ) -> None:
        self._settings = settings
        self._runtime = runtime_store
        self._exchange: ccxt_async.bybit | None = None
        self._ohlcv_cache = OhlcvCache(ttl_seconds=90.0, max_entries=800)

    @property
    def is_connected(self) -> bool:
        """Indica se a exchange está inicializada."""
        return self._exchange is not None

    async def connect(self) -> None:
        """Inicializa conexão com Bybit V5 (testnet, demo ou live)."""
        if self._exchange is not None:
            return

        self._exchange = ccxt_async.bybit(
            {
                "apiKey": self._settings.active_bybit_api_key.get_secret_value(),
                "secret": self._settings.active_bybit_api_secret.get_secret_value(),
                "enableRateLimit": True,
                "options": {
                    "defaultType": "swap",
                    "defaultSubType": "linear",
                    "adjustForTimeDifference": True,
                    "recvWindow": 20000,
                },
            }
        )

        mode = self._settings.bybit_mode
        if mode == "testnet":
            self._exchange.set_sandbox_mode(True)
        elif mode == "demo":
            self._exchange.enable_demo_trading(True)

        try:
            await self._exchange.load_time_difference()
            await self._exchange.load_markets()
        except AuthenticationError as exc:
            logger.warning(
                "Autenticação falhou no load_markets (%s) — carregando mercados públicos",
                exc,
            )
            markets = await self._exchange.fetch_markets()
            self._exchange.set_markets(markets)
        except Exception:
            await self._exchange.close()
            self._exchange = None
            raise

        hostname = getattr(self._exchange, "hostname", None)
        if not hostname:
            api_urls = self._exchange.urls.get("api", {})
            hostname = api_urls.get("private") or api_urls.get("public") or "unknown"

        logger.info(
            "Bybit conectado | mode=%s | endpoint=%s | markets=%d",
            mode,
            hostname,
            len(self._exchange.markets),
        )

    async def disconnect(self) -> None:
        """Fecha conexão CCXT."""
        if self._exchange is not None:
            await self._exchange.close()
            self._exchange = None
        logger.info("Bybit desconectado")

    def _ensure_connected(self) -> ccxt_async.bybit:
        if self._exchange is None:
            raise RuntimeError("ExchangeClient não conectado. Chame connect() primeiro.")
        return self._exchange

    def _is_linear_swap_market(self, market: dict[str, Any]) -> bool:
        """Verifica se o mercado é perpetual linear (futures swap)."""
        if self._settings.bybit_market_type != "linear_swap":
            return True
        return (
            market.get("swap") is True
            and market.get("linear") is True
            and market.get("type") == "swap"
        )

    def _find_linear_swap(self, exchange: ccxt_async.bybit, base: str) -> str | None:
        """Busca símbolo de perpetual linear para um base asset."""
        for market_symbol, market in exchange.markets.items():
            if (
                market.get("base") == base
                and self._is_linear_swap_market(market)
            ):
                return market_symbol
        return None

    def resolve_symbol(self, symbol: str) -> str:
        """
        Resolve símbolo para perpetual linear swap (ex: BTC/USDT:USDT).

        Rejeita mercados spot e não-linear.
        """
        exchange = self._ensure_connected()
        normalized = symbol.upper().strip()

        if normalized in exchange.markets:
            market = exchange.markets[normalized]
            if self._is_linear_swap_market(market):
                return normalized

        swap_variant = f"{normalized}:USDT" if ":" not in normalized else normalized
        if swap_variant in exchange.markets:
            market = exchange.markets[swap_variant]
            if not self._is_linear_swap_market(market):
                raise ValueError(
                    f"Mercado não permitido (apenas linear swap): {swap_variant}"
                )
            return swap_variant

        base = normalized.split("/")[0].split(":")[0]
        found = self._find_linear_swap(exchange, base)
        if found is not None:
            return found

        raise ValueError(
            f"Símbolo não encontrado como perpetual linear: {symbol}"
        )

    def count_markets_by_type(self) -> dict[str, int]:
        """Conta mercados carregados por categoria (para diagnóstico)."""
        exchange = self._ensure_connected()
        counts: dict[str, int] = {
            "linear_swap": 0,
            "spot": 0,
            "inverse": 0,
            "other": 0,
        }
        for market in exchange.markets.values():
            if self._is_linear_swap_market(market):
                counts["linear_swap"] += 1
            elif market.get("type") == "spot":
                counts["spot"] += 1
            elif market.get("linear") is False and market.get("swap"):
                counts["inverse"] += 1
            else:
                counts["other"] += 1
        return counts

    async def fetch_balance(self) -> dict[str, Any]:
        """Busca saldo da conta (USDT e totais)."""
        exchange = self._ensure_connected()
        try:
            return await exchange.fetch_balance()
        except AuthenticationError:
            logger.warning("Saldo indisponível — credenciais Bybit inválidas ou sem permissão")
            raise
        except Exception:
            logger.exception("Erro ao buscar saldo")
            raise

    async def fetch_usdt_balance(self) -> float:
        """Retorna saldo USDT livre para cálculo de risco."""
        balance = await self.fetch_balance()
        usdt = balance.get("USDT", {})
        free = usdt.get("free") or usdt.get("total") or 0.0
        return float(free)

    def get_market_limits(self, symbol: str) -> dict[str, Any]:
        """Retorna limites e precisão do mercado."""
        exchange = self._ensure_connected()
        resolved = self.resolve_symbol(symbol)
        market = exchange.markets[resolved]
        limits = market.get("limits", {})
        amount_limits = limits.get("amount", {})
        precision = market.get("precision", {})
        max_amount = amount_limits.get("max")
        lot_filter = (market.get("info") or {}).get("lotSizeFilter") or {}
        max_mkt_qty = lot_filter.get("maxMktOrderQty")
        if max_mkt_qty is not None:
            max_mkt = float(max_mkt_qty)
            if max_amount is not None:
                max_amount = min(float(max_amount), max_mkt)
            else:
                max_amount = max_mkt
        leverage_limits = limits.get("leverage", {})
        return {
            "min_amount": float(amount_limits.get("min") or 0.001),
            "max_amount": max_amount,
            "min_cost": limits.get("cost", {}).get("min"),
            "amount_precision": precision.get("amount"),
            "price_precision": precision.get("price"),
            "contract_size": market.get("contractSize", 1.0),
            "max_leverage": leverage_limits.get("max"),
            "min_leverage": leverage_limits.get("min"),
        }

    def amount_to_precision(self, symbol: str, amount: float) -> float:
        """Arredonda quantidade à precisão da exchange."""
        exchange = self._ensure_connected()
        resolved = self.resolve_symbol(symbol)
        return float(exchange.amount_to_precision(resolved, amount))

    def price_to_precision(self, symbol: str, price: float) -> float:
        """Arredonda preço à precisão da exchange."""
        exchange = self._ensure_connected()
        resolved = self.resolve_symbol(symbol)
        return float(exchange.price_to_precision(resolved, price))

    async def fetch_positions(
        self,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        """Busca posições abertas."""
        exchange = self._ensure_connected()
        try:
            symbols = None
            if symbol:
                symbols = [self.resolve_symbol(symbol)]
            return await exchange.fetch_positions(symbols)
        except Exception:
            logger.exception("Erro ao buscar posições | symbol=%s", symbol)
            raise

    async def fetch_position_size(self, symbol: str, side: str) -> float:
        """Retorna tamanho da posição aberta para o lado informado."""
        positions = await self.fetch_positions(symbol)
        resolved = self.resolve_symbol(symbol)
        want_long = side == "buy"
        for pos in positions:
            if pos.get("symbol") != resolved:
                continue
            contracts = abs(float(pos.get("contracts") or pos.get("contractSize") or 0))
            if contracts <= 0:
                continue
            pos_side = (pos.get("side") or "").lower()
            if want_long and pos_side in ("long", "buy"):
                return contracts
            if not want_long and pos_side in ("short", "sell"):
                return contracts
        return 0.0

    async def resolve_liquidation_price(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        leverage: int,
    ) -> float:
        """
        Preço de liquidação: posição aberta (exchange) ou estimativa pré-trade.
        """
        from src.strategies.liquidation_safety import (
            estimate_liquidation_price,
            parse_liquidation_from_position,
        )

        positions = await self.fetch_positions(symbol)
        resolved = self.resolve_symbol(symbol)
        want_long = side.lower() in ("buy", "long")
        for pos in positions:
            if pos.get("symbol") != resolved:
                continue
            contracts = abs(float(pos.get("contracts") or pos.get("contractSize") or 0))
            if contracts <= 0:
                continue
            pos_side = (pos.get("side") or "").lower()
            if want_long and pos_side not in ("long", "buy"):
                continue
            if not want_long and pos_side not in ("short", "sell"):
                continue
            liq = parse_liquidation_from_position(pos)
            if liq is not None:
                return liq
            entry_px = float(pos.get("entryPrice") or entry_price)
            lev = int(float(pos.get("leverage") or leverage))
            return estimate_liquidation_price(entry_px, lev, side)

        return estimate_liquidation_price(entry_price, leverage, side)

    async def count_open_positions(self) -> int:
        """Conta posições abertas em todos os símbolos."""
        positions = await self.fetch_positions()
        count = 0
        for pos in positions:
            contracts = abs(float(pos.get("contracts") or pos.get("contractSize") or 0))
            if contracts > 0:
                count += 1
        return count

    async def fetch_open_position_report_rows(self) -> list[dict[str, Any]]:
        """Posições abertas com PnL real da Bybit (não estimado do journal)."""
        from src.services.pnl_reporter import position_row_from_exchange

        rows: list[dict[str, Any]] = []
        for pos in await self.fetch_positions():
            row = position_row_from_exchange(pos)
            if row is not None:
                rows.append(row)
        return rows

    async def fetch_closed_pnl_records(
        self,
        start_ms: int,
        end_ms: int,
    ) -> list[dict[str, Any]]:
        """Busca histórico closed-pnl da Bybit (janelas de até 7 dias + paginação)."""
        from src.services.pnl_reporter import MAX_BYBIT_WINDOW_MS

        exchange = self._ensure_connected()
        records: list[dict[str, Any]] = []
        window_start = start_ms

        while window_start < end_ms:
            window_end = min(window_start + MAX_BYBIT_WINDOW_MS, end_ms)
            cursor: str | None = None
            while True:
                request: dict[str, Any] = {
                    "category": "linear",
                    "startTime": window_start,
                    "endTime": window_end,
                    "limit": 100,
                }
                if cursor:
                    request["cursor"] = cursor
                response = await exchange.privateGetV5PositionClosedPnl(request)
                result = response.get("result") or {}
                batch = result.get("list") or []
                records.extend(batch)
                cursor = result.get("nextPageCursor")
                if not cursor or not batch:
                    break
            window_start = window_end + 1

        return records

    async def fetch_closed_pnl_stats(
        self,
        start_ms: int,
        end_ms: int,
    ) -> dict[str, Any]:
        """W/L e PnL realizado agregados da Bybit no período."""
        from src.services.pnl_reporter import aggregate_closed_pnl_records

        records = await self.fetch_closed_pnl_records(start_ms, end_ms)
        return aggregate_closed_pnl_records(records)

    async def fetch_linear_executions(
        self,
        start_ms: int,
        end_ms: int,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        """Busca histórico de execuções linear (fills) com paginação."""
        from src.services.pnl_reporter import MAX_BYBIT_WINDOW_MS

        exchange = self._ensure_connected()
        records: list[dict[str, Any]] = []
        window_start = start_ms

        while window_start < end_ms:
            window_end = min(window_start + MAX_BYBIT_WINDOW_MS, end_ms)
            cursor: str | None = None
            while True:
                request: dict[str, Any] = {
                    "category": "linear",
                    "startTime": window_start,
                    "endTime": window_end,
                    "limit": 100,
                }
                if symbol:
                    resolved = self.resolve_symbol(symbol)
                    market = exchange.market(resolved)
                    request["symbol"] = market["id"]
                if cursor:
                    request["cursor"] = cursor
                response = await exchange.privateGetV5ExecutionList(request)
                result = response.get("result") or {}
                batch = result.get("list") or []
                records.extend(batch)
                cursor = result.get("nextPageCursor")
                if not cursor or not batch:
                    break
            window_start = window_end + 1

        return records

    async def scan_recent_slippage(
        self,
        start_ms: int,
        end_ms: int,
        *,
        symbol: str | None = None,
    ) -> list[Any]:
        """Detecta slippage >1% em execuções recentes."""
        from src.services.slippage_guard import scan_execution_rows

        rows = await self.fetch_linear_executions(start_ms, end_ms, symbol=symbol)
        return scan_execution_rows(rows)

    async def fetch_order(self, order_id: str, symbol: str) -> dict[str, Any]:
        """Busca status de uma ordem."""
        from ccxt.base.errors import ArgumentsRequired, BadRequest, OrderNotFound

        exchange = self._ensure_connected()
        resolved = self.resolve_symbol(symbol)
        try:
            return await exchange.fetch_order(
                order_id,
                resolved,
                params={"acknowledged": True},
            )
        except (OrderNotFound, ArgumentsRequired, BadRequest) as exc:
            logger.warning(
                "Ordem não consultável | id=%s symbol=%s | %s",
                order_id,
                symbol,
                exc,
            )
            raise
        except Exception:
            logger.exception("Erro ao buscar ordem | id=%s symbol=%s", order_id, symbol)
            raise

    async def fetch_open_orders(self, symbol: str) -> list[dict[str, Any]]:
        """Lista ordens abertas do símbolo."""
        exchange = self._ensure_connected()
        resolved = self.resolve_symbol(symbol)
        try:
            return await exchange.fetch_open_orders(resolved)
        except Exception:
            logger.exception("Erro ao buscar ordens abertas | symbol=%s", symbol)
            raise

    async def cancel_order(self, order_id: str, symbol: str) -> dict[str, Any]:
        """Cancela ordem por ID."""
        exchange = self._ensure_connected()
        resolved = self.resolve_symbol(symbol)
        try:
            result = await exchange.cancel_order(order_id, resolved)
            logger.info("Ordem cancelada | %s id=%s", symbol, order_id)
            return result
        except OrderNotFound:
            logger.debug("Ordem já inexistente | %s id=%s", symbol, order_id)
            return {}
        except Exception:
            logger.exception("Erro ao cancelar ordem | id=%s", order_id)
            raise

    async def create_reduce_only_limit(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float,
    ) -> dict[str, Any]:
        """Cria ordem limit reduce-only (TP parcial)."""
        exchange = self._ensure_connected()
        resolved = self.resolve_symbol(symbol)
        amount = self.amount_to_precision(symbol, amount)
        price = self.price_to_precision(symbol, price)
        try:
            order = await exchange.create_order(
                resolved,
                "limit",
                side,
                amount,
                price,
                params={"reduceOnly": True, "timeInForce": "GTC"},
            )
            logger.info(
                "TP limit reduce-only | %s %s amount=%s @ %s id=%s",
                side,
                symbol,
                amount,
                price,
                order.get("id"),
            )
            return order
        except Exception:
            logger.exception("Erro ao criar TP limit | %s @ %s", symbol, price)
            raise

    @staticmethod
    def _is_stop_loss_order(order: dict[str, Any], close_side: str) -> bool:
        """Identifica ordem de stop loss (condicional ou trading-stop)."""
        if (order.get("side") or "").lower() != close_side.lower():
            return False
        info = order.get("info") or {}
        order_type = (order.get("type") or "").lower()
        if order_type in ("stop", "stopmarket", "stop_market"):
            return True
        for key in ("triggerPrice", "stopLossPrice", "stopPrice"):
            val = _parse_float(order.get(key)) or _parse_float(info.get(key))
            if val and val > 0:
                return True
        return str(info.get("stopOrderType") or "").lower() in ("stop", "stoploss")

    @staticmethod
    def _is_take_profit_order(order: dict[str, Any], close_side: str) -> bool:
        """Identifica TP (trading-stop parcial ou limit reduce-only)."""
        if (order.get("side") or "").lower() != close_side.lower():
            return False
        if ExchangeClient._is_stop_loss_order(order, close_side):
            return False
        if ExchangeClient._is_reduce_only_limit_tp(order, close_side):
            return True
        info = order.get("info") or {}
        for key in ("takeProfitPrice", "takeProfit", "tpTriggerPrice"):
            val = _parse_float(order.get(key)) or _parse_float(info.get(key))
            if val and val > 0:
                return True
        return str(info.get("stopOrderType") or "").lower() in (
            "takeprofit",
            "partialtakeprofit",
            "tpsl",
        )

    @staticmethod
    def _order_tp_price(order: dict[str, Any]) -> float:
        info = order.get("info") or {}
        for key in (
            "takeProfitPrice",
            "takeProfit",
            "tpTriggerPrice",
            "price",
            "triggerPrice",
        ):
            val = _parse_float(order.get(key)) or _parse_float(info.get(key))
            if val and val > 0:
                return float(val)
        return 0.0

    @staticmethod
    def _order_sl_price(order: dict[str, Any]) -> float:
        info = order.get("info") or {}
        for key in ("stopLossPrice", "stopPrice", "triggerPrice", "price"):
            val = _parse_float(order.get(key)) or _parse_float(info.get(key))
            if val and val > 0:
                return float(val)
        return 0.0

    @staticmethod
    def is_stop_at_entry(
        entry_price: float,
        sl_price: float,
        *,
        tolerance_pct: float = 0.15,
    ) -> bool:
        """True quando SL já está na entrada (breakeven aplicado)."""
        if entry_price <= 0 or sl_price <= 0:
            return False
        return abs(sl_price - entry_price) / entry_price * 100.0 <= tolerance_pct

    async def fetch_open_stop_loss_price(
        self,
        symbol: str,
        entry_side: str,
    ) -> float | None:
        """Preço do SL aberto na exchange, se existir."""
        close_side = "sell" if entry_side.lower() in ("buy", "long") else "buy"
        for order in await self.fetch_open_orders(symbol):
            if not self._is_stop_loss_order(order, close_side):
                continue
            price = self._order_sl_price(order)
            if price > 0:
                return price
        return None

    @staticmethod
    def _order_open_amount(order: dict[str, Any]) -> float:
        remaining = _parse_float(order.get("remaining"))
        if remaining and remaining > 0:
            return float(remaining)
        amount = _parse_float(order.get("amount"))
        return float(amount) if amount and amount > 0 else 0.0

    async def _collect_open_tp_snapshots(
        self,
        symbol: str,
        entry_side: str,
    ) -> list[dict[str, Any]]:
        """Snapshot de TPs abertos (preço + qty) antes de alterar SL."""
        entry_norm = "buy" if entry_side.lower() in ("buy", "long") else "sell"
        close_side = "sell" if entry_norm == "buy" else "buy"
        snapshots: list[dict[str, Any]] = []
        for order in await self.fetch_open_orders(symbol):
            if not self._is_take_profit_order(order, close_side):
                continue
            price = self._order_tp_price(order)
            amount = self._order_open_amount(order)
            if price <= 0 or amount <= 0:
                continue
            snapshots.append({
                "order_id": order.get("id"),
                "price": price,
                "amount": amount,
            })
        return snapshots

    async def _restore_take_profit_snapshots(
        self,
        symbol: str,
        entry_side: str,
        snapshots: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Recria TPs que sumiram após tradingStop alterar o SL (Bybit apaga TPs)."""
        if not snapshots:
            return []

        entry_norm = "buy" if entry_side.lower() in ("buy", "long") else "sell"
        close_side = "sell" if entry_norm == "buy" else "buy"
        current = await self._collect_open_tp_snapshots(symbol, entry_norm)
        current_prices = {round(s["price"], 10) for s in current}
        restored: list[dict[str, Any]] = []
        remaining = await self.fetch_position_size(symbol, entry_norm)

        for snap in snapshots:
            price = float(snap["price"])
            amount = float(snap["amount"])
            if price <= 0 or amount <= 0 or remaining <= 0:
                continue
            amount = min(amount, remaining)
            amount = float(self.amount_to_precision(symbol, amount))
            if amount <= 0:
                continue
            if round(price, 10) in current_prices:
                remaining = max(0.0, remaining - amount)
                continue
            try:
                tp_order = await self.create_partial_take_profit(
                    symbol,
                    close_side,
                    amount,
                    price,
                )
                restored.append({
                    **snap,
                    "order_id": tp_order.get("id"),
                    "amount": amount,
                })
                current_prices.add(round(price, 10))
                remaining = max(0.0, remaining - amount)
                await asyncio.sleep(0.15)
            except Exception as exc:
                logger.warning(
                    "Falha ao restaurar TP após breakeven | %s @ %s qty=%s: %s",
                    symbol,
                    price,
                    amount,
                    exc,
                )
        return restored

    async def ensure_take_profit_for_remaining(
        self,
        symbol: str,
        entry_side: str,
        take_profit_price: float,
        *,
        amount_tolerance: float = 0.05,
    ) -> dict[str, Any] | None:
        """
        Garante TP na exchange cobrindo o restante da posição (ex.: TP3 após parciais).

        Recria o TP se sumiu após breakeven ou se a qty não cobre o que ainda está aberto.
        """
        entry_norm = "buy" if entry_side.lower() in ("buy", "long") else "sell"
        close_side = "sell" if entry_norm == "buy" else "buy"
        remaining = await self.fetch_position_size(symbol, entry_norm)
        if remaining <= 0:
            return None

        tp_price = float(self.price_to_precision(symbol, take_profit_price))
        snapshots = await self._collect_open_tp_snapshots(symbol, entry_norm)
        price_key = round(tp_price, 10)

        for snap in snapshots:
            snap_price = round(float(snap["price"]), 10)
            if snap_price != price_key:
                continue
            snap_amount = float(snap["amount"])
            min_ok = remaining * (1.0 - amount_tolerance)
            if snap_amount >= min_ok:
                return {"status": "ok", "existing": snap}
            order_id = snap.get("order_id")
            if order_id:
                try:
                    await self.cancel_order(str(order_id), symbol)
                except Exception as exc:
                    logger.warning(
                        "Falha ao cancelar TP subdimensionado | %s id=%s: %s",
                        symbol,
                        order_id,
                        exc,
                    )

        amount = float(self.amount_to_precision(symbol, remaining))
        if amount <= 0:
            return None

        tp_order = await self.create_partial_take_profit(
            symbol,
            close_side,
            amount,
            tp_price,
        )
        logger.info(
            "TP final garantido | %s @ %s qty=%s id=%s",
            symbol,
            tp_price,
            amount,
            tp_order.get("id"),
        )
        return {
            "status": "created",
            "order_id": tp_order.get("id"),
            "price": tp_price,
            "amount": amount,
            "order": tp_order,
        }

    async def cancel_stop_loss_orders(
        self,
        symbol: str,
        entry_side: str,
    ) -> int:
        """Cancela SLs abertos do símbolo antes de mover para breakeven."""
        close_side = "sell" if entry_side.lower() in ("buy", "long") else "buy"
        cancelled = 0
        for order in await self.fetch_open_orders(symbol):
            if not self._is_stop_loss_order(order, close_side):
                continue
            order_id = order.get("id")
            if not order_id:
                continue
            try:
                await self.cancel_order(str(order_id), symbol)
                cancelled += 1
            except Exception:
                logger.warning(
                    "Falha ao cancelar SL | %s id=%s",
                    symbol,
                    order_id,
                )
        return cancelled

    async def cancel_take_profit_orders(
        self,
        symbol: str,
        entry_side: str,
    ) -> int:
        """Cancela TPs abertos (limit reduce-only ou trading-stop parcial)."""
        entry_norm = "buy" if entry_side.lower() in ("buy", "long") else "sell"
        close_side = "sell" if entry_norm == "buy" else "buy"
        cancelled = 0
        for order in await self.fetch_open_orders(symbol):
            if not self._is_take_profit_order(order, close_side):
                continue
            order_id = order.get("id")
            if not order_id:
                continue
            try:
                await self.cancel_order(str(order_id), symbol)
                cancelled += 1
            except Exception:
                logger.warning(
                    "Falha ao cancelar TP | %s id=%s",
                    symbol,
                    order_id,
                )
        return cancelled

    async def move_stop_loss_to_entry(
        self,
        symbol: str,
        entry_side: str,
        entry_price: float,
        amount: float | None = None,
        *,
        tp_fallback: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Move SL para entrada (breakeven) e preserva TPs parciais restantes."""
        entry_norm = "buy" if entry_side.lower() in ("buy", "long") else "sell"
        close_side = "sell" if entry_norm == "buy" else "buy"
        if amount is None:
            amount = await self.fetch_position_size(symbol, entry_norm)
        amount = self.amount_to_precision(symbol, amount)
        entry_price = self.price_to_precision(symbol, entry_price)

        tp_snapshots = await self._collect_open_tp_snapshots(symbol, entry_norm)
        if not tp_snapshots and tp_fallback:
            tp_snapshots = [
                {
                    "price": float(s["price"]),
                    "amount": float(s["amount"]),
                    "level": s.get("level"),
                    "order_id": s.get("order_id"),
                }
                for s in tp_fallback
                if float(s.get("price") or 0) > 0 and float(s.get("amount") or 0) > 0
            ]

        current_sl = await self.fetch_open_stop_loss_price(symbol, entry_norm)
        if current_sl and self.is_stop_at_entry(float(entry_price), current_sl):
            logger.info(
                "SL já em breakeven | %s @ %s — TPs preservados, sem alterações",
                symbol,
                entry_price,
            )
            return {
                "id": None,
                "stopLossPrice": current_sl,
                "restored_tps": [],
                "skipped": True,
            }

        await self.cancel_stop_loss_orders(symbol, entry_norm)

        sl_order = await self.create_partial_stop_loss(
            symbol,
            close_side,
            float(amount),
            float(entry_price),
        )

        restored = await self._restore_take_profit_snapshots(
            symbol, entry_norm, tp_snapshots
        )
        if restored:
            logger.info(
                "TPs restaurados após breakeven | %s | %s",
                symbol,
                ", ".join(f"@{r['price']}" for r in restored),
            )
        sl_order["restored_tps"] = restored
        return sl_order

    async def create_partial_stop_loss(
        self,
        symbol: str,
        side: str,
        amount: float,
        stop_price: float,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Cria SL parcial via trading-stop endpoint (Bybit V5)."""
        exchange = self._ensure_connected()
        resolved = self.resolve_symbol(symbol)
        amount = self.amount_to_precision(symbol, amount)
        stop_price = self.price_to_precision(symbol, stop_price)
        order_params: dict[str, Any] = {
            "stopLossPrice": stop_price,
            "tradingStopEndpoint": True,
            "reduceOnly": True,
            **(params or {}),
        }
        try:
            order = await exchange.create_order(
                resolved,
                "market",
                side,
                amount,
                params=order_params,
            )
            logger.info(
                "SL parcial | %s @ %s amount=%s id=%s",
                symbol,
                stop_price,
                amount,
                order.get("id"),
            )
            return order
        except Exception as exc:
            logger.warning(
                "tradingStop SL falhou, tentando conditional | %s: %s",
                symbol,
                exc,
            )
            return await self._create_conditional_stop(
                symbol, side, amount, stop_price, params
            )

    async def _create_conditional_stop(
        self,
        symbol: str,
        side: str,
        amount: float,
        stop_price: float,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fallback: ordem condicional market com trigger."""
        exchange = self._ensure_connected()
        resolved = self.resolve_symbol(symbol)
        trigger_dir = "ascending" if side == "buy" else "descending"
        order_params: dict[str, Any] = {
            "triggerPrice": stop_price,
            "triggerDirection": trigger_dir,
            "reduceOnly": True,
            **(params or {}),
        }
        order = await exchange.create_order(
            resolved,
            "market",
            side,
            amount,
            params=order_params,
        )
        logger.info(
            "SL condicional (fallback) | %s @ %s id=%s",
            symbol,
            stop_price,
            order.get("id"),
        )
        return order

    async def create_partial_take_profit(
        self,
        symbol: str,
        side: str,
        amount: float,
        take_profit_price: float,
        *,
        use_limit_at_trigger: bool = True,
    ) -> dict[str, Any]:
        """Cria TP parcial via trading-stop Bybit V5 (aba Posição parcial); limit como fallback."""
        amount = self.amount_to_precision(symbol, amount)
        tp_price = self.price_to_precision(symbol, take_profit_price)
        if float(amount) <= 0:
            raise ValueError(f"TP amount inválido: {amount}")

        exchange = self._ensure_connected()
        resolved = self.resolve_symbol(symbol)
        order_params: dict[str, Any] = {
            "takeProfitPrice": tp_price,
            "tradingStopEndpoint": True,
            "reduceOnly": True,
        }
        if use_limit_at_trigger:
            order_params["takeProfitLimitPrice"] = tp_price

        try:
            order = await exchange.create_order(
                resolved,
                "market",
                side,
                float(amount),
                params=order_params,
            )
            logger.info(
                "TP parcial (tradingStop) | %s @ %s amount=%s id=%s",
                symbol,
                tp_price,
                amount,
                order.get("id"),
            )
            return order
        except Exception as exc:
            logger.warning(
                "tradingStop TP falhou, tentando limit reduce-only | %s @ %s: %s",
                symbol,
                tp_price,
                exc,
            )
        return await self.create_reduce_only_limit(symbol, side, amount, tp_price)

    @staticmethod
    def _is_reduce_only_limit_tp(order: dict[str, Any], close_side: str) -> bool:
        """Identifica ordem limit reduce-only usada como TP (não SL condicional)."""
        if (order.get("side") or "").lower() != close_side.lower():
            return False
        if (order.get("type") or "").lower() != "limit":
            return False
        info = order.get("info") or {}
        reduce_only = order.get("reduceOnly")
        if reduce_only is None:
            raw = info.get("reduceOnly")
            reduce_only = str(raw).lower() in ("true", "1", "yes")
        if not reduce_only:
            return False
        for key in ("triggerPrice", "stopLossPrice", "stopPrice"):
            val = _parse_float(order.get(key)) or _parse_float(info.get(key))
            if val and val > 0:
                return False
        return True

    async def fetch_reduce_only_limit_tp_orders(
        self,
        symbol: str,
        entry_side: str,
    ) -> list[dict[str, Any]]:
        """Lista TPs abertos como limit reduce-only (candidatos à migração)."""
        close_side = "sell" if entry_side.lower() in ("buy", "long") else "buy"
        open_orders = await self.fetch_open_orders(symbol)
        return [
            o
            for o in open_orders
            if self._is_reduce_only_limit_tp(o, close_side)
        ]

    async def migrate_limit_tps_to_trading_stop(
        self,
        symbol: str,
        entry_side: str,
    ) -> dict[str, Any]:
        """
        Cancela TPs limit reduce-only e recria via trading-stop Bybit (posição parcial).
        """
        entry_norm = "buy" if entry_side.lower() in ("buy", "long") else "sell"
        close_side = "sell" if entry_norm == "buy" else "buy"

        size = await self.fetch_position_size(symbol, entry_norm)
        if size <= 0:
            return {"symbol": symbol, "status": "skipped", "reason": "sem_posição"}

        limit_tps = await self.fetch_reduce_only_limit_tp_orders(symbol, entry_norm)
        if not limit_tps:
            return {"symbol": symbol, "status": "skipped", "reason": "sem_tp_limit"}

        reverse = entry_norm == "sell"
        limit_tps.sort(
            key=lambda o: float(o.get("price") or 0),
            reverse=reverse,
        )

        migrated: list[dict[str, Any]] = []
        errors: list[str] = []

        for order in limit_tps:
            order_id = order.get("id")
            price = float(order.get("price") or 0)
            amount = float(
                order.get("remaining")
                or order.get("amount")
                or 0
            )
            if amount <= 0 or price <= 0:
                continue
            try:
                if order_id:
                    await self.cancel_order(str(order_id), symbol)
            except Exception as exc:
                errors.append(f"cancel {order_id}: {exc}")
                continue
            try:
                tp_order = await self.create_partial_take_profit(
                    symbol,
                    close_side,
                    amount,
                    price,
                )
                migrated.append({
                    "price": price,
                    "amount": amount,
                    "order_id": tp_order.get("id"),
                })
                await asyncio.sleep(0.15)
            except Exception as exc:
                errors.append(f"tp @ {price}: {exc}")

        status = "ok" if migrated and not errors else ("partial" if migrated else "failed")
        return {
            "symbol": symbol,
            "status": status,
            "migrated": migrated,
            "errors": errors,
        }

    async def emergency_close_position(
        self,
        symbol: str,
        entry_side: str,
    ) -> dict[str, Any] | None:
        """Fecha posição a mercado em emergência."""
        size = await self.fetch_position_size(symbol, entry_side)
        if size <= 0:
            logger.warning("Emergency close: sem posição | %s", symbol)
            return None
        close_side = "sell" if entry_side == "buy" else "buy"
        size = self.amount_to_precision(symbol, size)
        logger.warning(
            "EMERGENCY CLOSE | %s %s amount=%s",
            close_side,
            symbol,
            size,
        )
        return await self.create_market_order(
            symbol,
            close_side,
            size,
            params={"reduceOnly": True},
        )

    async def execute_trade_with_partial_tps(
        self,
        symbol: str,
        side: str,
        amount: float,
        stop_loss: float,
        take_profits: list[tuple[float, float]],
        leverage: int,
        entry_price: float | None = None,
    ) -> dict[str, Any]:
        """
        Executa entrada + SL total + TPs parciais via trading-stop Bybit.

        take_profits: lista de (preço, quantidade) para cada TP.
        """
        runtime = self._runtime.reload() if self._runtime else None
        config_max = runtime.risk.max_leverage if runtime else ABSOLUTE_MAX_LEVERAGE
        leverage = clamp_leverage_hard(leverage, config_max=config_max)
        leverage = await self.set_leverage(symbol, leverage)

        amount = self.amount_to_precision(symbol, amount)
        stop_loss = self.price_to_precision(symbol, stop_loss)
        close_side = "sell" if side == "buy" else "buy"

        entry_order, leverage = await self._create_market_order_with_risk_retry(
            symbol, side, amount, leverage
        )

        actual_entry = entry_price
        if actual_entry is None:
            fill_price = entry_order.get("average") or entry_order.get("price")
            if fill_price:
                actual_entry = float(fill_price)

        from src.services.slippage_guard import detect_slippage, log_slippage

        entry_slippage = None
        if entry_price and actual_entry:
            entry_slippage = detect_slippage(
                symbol=symbol,
                order_price=float(entry_price),
                exec_price=float(actual_entry),
                context="entry",
                side=side,
                order_type="Market",
            )
            if entry_slippage is not None:
                log_slippage(entry_slippage)

        from src.strategies.trade_validation import shift_execution_levels

        planned_entry = entry_price or actual_entry or 0.0
        if actual_entry and planned_entry:
            tp_prices = [tp[0] for tp in take_profits]
            stop_loss, shifted_tps = shift_execution_levels(
                planned_entry,
                float(actual_entry),
                float(stop_loss),
                tp_prices,
            )
            stop_loss = self.price_to_precision(symbol, stop_loss)
            take_profits = [
                (self.price_to_precision(symbol, shifted_tps[i]), take_profits[i][1])
                for i in range(len(take_profits))
            ]
            if abs(float(actual_entry) - planned_entry) / planned_entry > 0.0001:
                logger.info(
                    "Níveis ajustados ao fill | %s | planned=%s actual=%s sl=%s tp1=%s",
                    symbol,
                    planned_entry,
                    actual_entry,
                    stop_loss,
                    take_profits[0][0] if take_profits else None,
                )

        # #region agent log
        from src.utils.debug_session import debug_log

        fill_delta = (
            (actual_entry - entry_price) if actual_entry and entry_price else 0.0
        )
        sl_dist = abs((entry_price or actual_entry or 0) - stop_loss)
        tp1_planned = take_profits[0][0] if take_profits else 0.0
        tp1_dist = abs(tp1_planned - (entry_price or actual_entry or 0))
        debug_log(
            location="exchange_client.py:execute_trade_with_partial_tps",
            message="entry_fill_vs_planned",
            hypothesis_id="H1",
            data={
                "symbol": symbol,
                "side": side,
                "planned_entry": entry_price,
                "actual_entry": actual_entry,
                "fill_delta": fill_delta,
                "fill_delta_pct": round(
                    fill_delta / entry_price * 100, 4
                )
                if entry_price
                else None,
                "stop_loss": stop_loss,
                "sl_dist_pct": round(
                    sl_dist / (actual_entry or entry_price or 1) * 100, 4
                ),
                "tp1_planned": tp1_planned,
                "tp1_dist_pct": round(
                    tp1_dist / (actual_entry or entry_price or 1) * 100, 4
                ),
                "tp1_rr": round(tp1_dist / sl_dist, 4) if sl_dist > 0 else None,
                "tp_orders": [
                    {"level": i + 1, "price": p, "amount": a}
                    for i, (p, a) in enumerate(take_profits)
                    if a > 0
                ],
                "leverage": leverage,
            },
        )
        # #endregion

        from src.strategies.liquidation_safety import estimate_liquidation_price
        from src.strategies.trade_validation import apply_liquidation_safe_stop_loss

        runtime = self._runtime.reload() if self._runtime else None
        buffer_pct = runtime.risk.liquidation_sl_buffer_pct if runtime else 0.4
        ref_entry = float(actual_entry or planned_entry or entry_price or 0)
        if ref_entry > 0:
            try:
                liq_price = await self.resolve_liquidation_price(
                    symbol, side, ref_entry, leverage
                )
            except Exception:
                liq_price = estimate_liquidation_price(
                    ref_entry, leverage, "LONG" if side == "buy" else "SHORT"
                )
            direction = TradeDirection.LONG if side == "buy" else TradeDirection.SHORT
            safe_sl, sl_err = apply_liquidation_safe_stop_loss(
                direction,
                ref_entry,
                float(stop_loss),
                liq_price,
                buffer_pct,
            )
            if sl_err or safe_sl is None:
                logger.error(
                    "SL inseguro vs liquidação | %s | sl=%s liq=%s | %s — emergency close",
                    symbol,
                    stop_loss,
                    liq_price,
                    sl_err,
                )
                await self.emergency_close_position(symbol, side)
                return {
                    "entry": entry_order,
                    "entry_price": actual_entry,
                    "emergency_closed": True,
                    "symbol": symbol,
                    "side": side,
                    "amount": amount,
                    "stop_loss": stop_loss,
                    "leverage": leverage,
                    "error": sl_err or "SL inseguro",
                }
            if safe_sl != float(stop_loss):
                logger.warning(
                    "SL clamped pós-fill | %s | %.6g -> %.6g | liq=%.6g",
                    symbol,
                    stop_loss,
                    safe_sl,
                    liq_price,
                )
                stop_loss = self.price_to_precision(symbol, safe_sl)

        sl_order_id: str | None = None
        tp_orders: list[dict[str, Any]] = []
        protection_errors: list[Exception] = []

        try:
            sl_order = await self.create_partial_stop_loss(
                symbol, close_side, amount, stop_loss
            )
            sl_order_id = sl_order.get("id")
        except Exception as exc:
            protection_errors.append(exc)
            logger.error("Falha ao criar SL | %s", symbol)

        for level, (tp_price, tp_amount) in enumerate(take_profits, start=1):
            if tp_amount <= 0:
                continue
            try:
                tp_order = await self.create_partial_take_profit(
                    symbol,
                    close_side,
                    tp_amount,
                    tp_price,
                )
                tp_orders.append({
                    "level": level,
                    "order_id": tp_order.get("id"),
                    "price": tp_price,
                    "amount": tp_amount,
                    "order": tp_order,
                })
            except Exception as exc:
                protection_errors.append(exc)
                logger.error(
                    "Falha ao criar TP%d | %s @ %s",
                    level,
                    symbol,
                    tp_price,
                )

        emergency_closed = False
        if protection_errors and len(tp_orders) == 0 and sl_order_id is None:
            logger.error(
                "Todas proteções falharam — emergency close | %s",
                symbol,
            )
            await self.emergency_close_position(symbol, side)
            emergency_closed = True
        else:
            await self._sync_protection_order_ids(symbol, close_side, tp_orders)
            if sl_order_id is None:
                sl_order_id = await self._find_sl_order_id(
                    symbol, close_side, stop_loss
                )

        return {
            "entry": entry_order,
            "entry_price": actual_entry,
            "sl_order_id": sl_order_id,
            "tp_orders": tp_orders,
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "stop_loss": stop_loss,
            "take_profit_prices": [tp[0] for tp in take_profits],
            "protection_errors": [str(e) for e in protection_errors],
            "emergency_closed": emergency_closed,
            "leverage": leverage,
            "entry_slippage": (
                {
                    "slippage_pct": entry_slippage.slippage_pct,
                    "order_price": entry_slippage.order_price,
                    "exec_price": entry_slippage.exec_price,
                }
                if entry_slippage is not None
                else None
            ),
        }

    async def _sync_protection_order_ids(
        self,
        symbol: str,
        close_side: str,
        tp_orders: list[dict[str, Any]],
    ) -> None:
        """Atribui IDs de ordens abertas quando tradingStop não retorna id."""
        try:
            open_orders = await self.fetch_open_orders(symbol)
        except Exception:
            logger.warning("Não foi possível sincronizar IDs | %s", symbol)
            return

        for tp in tp_orders:
            if tp.get("order_id"):
                continue
            price = float(tp.get("price") or 0)
            amount = float(tp.get("amount") or 0)
            for order in open_orders:
                if (order.get("side") or "").lower() != close_side:
                    continue
                order_price = float(order.get("price") or order.get("triggerPrice") or 0)
                order_amount = float(order.get("amount") or 0)
                if (
                    abs(order_price - price) < 0.05
                    and abs(order_amount - amount) < 0.01
                ):
                    tp["order_id"] = order.get("id")
                    break

    async def _find_sl_order_id(
        self,
        symbol: str,
        close_side: str,
        stop_loss: float,
    ) -> str | None:
        """Localiza ordem SL aberta pelo preço trigger."""
        try:
            open_orders = await self.fetch_open_orders(symbol)
        except Exception:
            return None

        for order in open_orders:
            if (order.get("side") or "").lower() != close_side:
                continue
            trigger = float(
                order.get("triggerPrice")
                or order.get("stopLossPrice")
                or order.get("price")
                or 0
            )
            if abs(trigger - stop_loss) < 0.05:
                return order.get("id")
        return None

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str | None = None,
        limit: int | None = None,
    ) -> list[list[float]]:
        """
        Busca candles OHLCV de forma assíncrona.

        Returns:
            Lista de [timestamp, open, high, low, close, volume].
        """
        exchange = self._ensure_connected()
        runtime = self._runtime.reload() if self._runtime else None
        tf = timeframe or (runtime.timeframes.primary if runtime else "15m")
        lim = limit or (runtime.ohlcv_limit if runtime else 200)

        try:
            resolved = self.resolve_symbol(symbol)
            cache_key = (resolved, tf, lim)
            cached = self._ohlcv_cache.get(cache_key)
            if cached is not None:
                return cached
            data = await exchange.fetch_ohlcv(resolved, tf, limit=lim)
            self._ohlcv_cache.set(cache_key, data)
            return data
        except Exception:
            logger.exception("Erro ao buscar OHLCV | symbol=%s tf=%s", symbol, tf)
            raise

    async def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        """Busca ticker atual do par."""
        exchange = self._ensure_connected()
        try:
            resolved = self.resolve_symbol(symbol)
            return await exchange.fetch_ticker(resolved)
        except Exception:
            logger.exception("Erro ao buscar ticker | symbol=%s", symbol)
            raise

    def list_linear_usdt_symbols(self) -> list[str]:
        """Lista perpetuals linear USDT ativos (formato CCXT)."""
        exchange = self._ensure_connected()
        symbols: list[str] = []
        for market in exchange.markets.values():
            if not self._is_linear_swap_market(market):
                continue
            if market.get("quote") != "USDT":
                continue
            if market.get("active") is False:
                continue
            sym = market.get("symbol")
            if sym:
                symbols.append(sym)
        return sorted(symbols)

    async def fetch_linear_market_snapshot(self) -> dict[str, dict[str, Any]]:
        """
        Snapshot de todos os perpétuos linear: volume, funding, variação 24h.

        Uma única chamada à API (fetch_funding_rates sem símbolos).
        """
        exchange = self._ensure_connected()
        try:
            rates = await exchange.fetch_funding_rates(params={"subType": "linear"})
        except Exception:
            logger.exception("Erro ao buscar snapshot linear")
            raise

        snapshot: dict[str, dict[str, Any]] = {}
        for symbol, data in rates.items():
            market = exchange.markets.get(symbol)
            if market is None or not self._is_linear_swap_market(market):
                continue
            if market.get("quote") != "USDT":
                continue

            turnover = (
                data.get("quoteVolume")
                or data.get("turnover")
                or (data.get("info") or {}).get("turnover24h")
            )
            pct = data.get("percentage") or (data.get("info") or {}).get("price24hPcnt")
            funding = data.get("fundingRate")
            if funding is None:
                funding = (data.get("info") or {}).get("fundingRate")

            try:
                turnover_f = float(turnover) if turnover is not None else 0.0
            except (TypeError, ValueError):
                turnover_f = 0.0
            try:
                pct_f = float(pct) * 100 if pct is not None and abs(float(pct)) < 1 else float(pct or 0)
            except (TypeError, ValueError):
                pct_f = 0.0
            try:
                funding_f = float(funding) if funding is not None else None
            except (TypeError, ValueError):
                funding_f = None

            snapshot[symbol] = {
                "turnover_24h": turnover_f,
                "price_change_24h_pct": pct_f,
                "funding_rate": funding_f,
                "last_price": data.get("last"),
                "open_interest": _parse_float(
                    data.get("openInterest")
                    or (data.get("info") or {}).get("openInterest")
                    or (data.get("info") or {}).get("openInterestValue"),
                ),
            }
        return snapshot

    async def fetch_account_ratio_delta(
        self,
        symbol: str,
        period: str = "1h",
    ) -> dict[str, float | None]:
        """Último buy/sell ratio e delta vs leitura anterior (shorts/long entering)."""
        exchange = self._ensure_connected()
        resolved = self.resolve_symbol(symbol)
        try:
            history = await exchange.fetch_long_short_ratio_history(
                resolved,
                timeframe=period,
                limit=2,
            )
        except Exception:
            logger.debug("Account ratio indisponível | %s", symbol, exc_info=True)
            return {"buy_ratio": None, "sell_ratio": None, "sell_ratio_delta": None, "buy_ratio_delta": None}

        if not history:
            return {"buy_ratio": None, "sell_ratio": None, "sell_ratio_delta": None, "buy_ratio_delta": None}

        latest = history[-1]
        info = latest.get("info") or {}
        buy = _parse_float(info.get("buyRatio"))
        sell = _parse_float(info.get("sellRatio"))

        buy_delta: float | None = None
        sell_delta: float | None = None
        if len(history) >= 2:
            prev_info = history[-2].get("info") or {}
            prev_buy = _parse_float(prev_info.get("buyRatio"))
            prev_sell = _parse_float(prev_info.get("sellRatio"))
            if buy is not None and prev_buy is not None:
                buy_delta = buy - prev_buy
            if sell is not None and prev_sell is not None:
                sell_delta = sell - prev_sell

        return {
            "buy_ratio": buy,
            "sell_ratio": sell,
            "sell_ratio_delta": sell_delta,
            "buy_ratio_delta": buy_delta,
        }

    async def fetch_order_book(
        self,
        symbol: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Busca snapshot do orderbook."""
        exchange = self._ensure_connected()
        try:
            resolved = self.resolve_symbol(symbol)
            return await exchange.fetch_order_book(resolved, limit=limit)
        except Exception:
            logger.exception("Erro ao buscar orderbook | symbol=%s", symbol)
            raise

    async def set_leverage(self, symbol: str, leverage: int) -> int:
        """Define alavancagem respeitando hard cap 30x, limites configurados e do mercado."""
        if leverage > ABSOLUTE_MAX_LEVERAGE:
            logger.error(
                "Alavancagem %dx bloqueada — hard limit %dx | %s",
                leverage,
                ABSOLUTE_MAX_LEVERAGE,
                symbol,
            )
        runtime = self._runtime.reload() if self._runtime else None
        config_max = runtime.risk.max_leverage if runtime else ABSOLUTE_MAX_LEVERAGE
        market_limits = self.get_market_limits(symbol)
        market_max = market_limits.get("max_leverage")
        market_max_int = int(market_max) if market_max is not None else None
        capped = clamp_leverage_hard(
            leverage,
            config_max=config_max,
            market_max=market_max_int,
        )
        exchange = self._ensure_connected()
        resolved = self.resolve_symbol(symbol)
        try:
            await exchange.set_leverage(capped, resolved)
            logger.info("Alavancagem definida | %s = %dx", symbol, capped)
            return capped
        except BadRequest as exc:
            msg = str(exc)
            lowered = msg.lower()
            if "110043" in msg or "leverage not modified" in lowered:
                logger.info("Alavancagem já em %dx | %s", capped, symbol)
                return capped
            if "110013" in msg:
                suggested = _parse_max_leverage_from_error(msg)
                if suggested and suggested < capped:
                    suggested = clamp_leverage_hard(
                        suggested,
                        config_max=config_max,
                        market_max=market_max_int,
                    )
                    logger.warning(
                        "Alavancagem acima do máximo do par | %s | %dx -> %dx",
                        symbol,
                        capped,
                        suggested,
                    )
                    await exchange.set_leverage(suggested, resolved)
                    logger.info("Alavancagem definida | %s = %dx", symbol, suggested)
                    return suggested
            logger.exception("Erro ao definir alavancagem | symbol=%s", symbol)
            raise
        except Exception:
            logger.exception("Erro ao definir alavancagem | symbol=%s", symbol)
            raise

    async def _submit_market_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        runtime = self._runtime.reload() if self._runtime else None
        if runtime is not None:
            lev_hint = params.get("leverage") if params else None
            if lev_hint is not None and int(lev_hint) > ABSOLUTE_MAX_LEVERAGE:
                logger.error(
                    "Ordem bloqueada: leverage %dx > hard limit %dx | %s",
                    int(lev_hint),
                    ABSOLUTE_MAX_LEVERAGE,
                    symbol,
                )
                raise ValueError(
                    f"Leverage {int(lev_hint)}x excede hard limit de {ABSOLUTE_MAX_LEVERAGE}x"
                )
        exchange = self._ensure_connected()
        resolved = self.resolve_symbol(symbol)
        return await exchange.create_order(
            resolved, "market", side, amount, params=params or {}
        )

    async def _create_market_order_with_risk_retry(
        self,
        symbol: str,
        side: str,
        amount: float,
        leverage: int,
        *,
        max_retries: int = 3,
    ) -> tuple[dict[str, Any], int]:
        """Cria ordem market; em 110090 reduz alavancagem conforme exchange."""
        runtime = self._runtime.reload() if self._runtime else None
        config_max = runtime.risk.max_leverage if runtime else ABSOLUTE_MAX_LEVERAGE
        current_lev = clamp_leverage_hard(leverage, config_max=config_max)
        if current_lev != leverage:
            logger.warning(
                "Alavancagem clampada antes da ordem | %s | %dx -> %dx",
                symbol,
                leverage,
                current_lev,
            )
        last_exc: ExchangeError | None = None

        for _ in range(max_retries):
            try:
                order = await self._submit_market_order(symbol, side, amount)
                logger.info(
                    "Ordem market criada | %s %s amount=%s id=%s",
                    side,
                    symbol,
                    amount,
                    order.get("id"),
                )
                return order, current_lev
            except ExchangeError as exc:
                msg = str(exc)
                if "110090" not in msg:
                    logger.exception("Erro ao criar ordem market | %s %s", side, symbol)
                    raise
                suggested = _parse_risk_tier_max_leverage(msg)
                if suggested is None or suggested >= current_lev:
                    logger.warning(
                        "Risk tier limit | %s | lev=%dx | %s",
                        symbol,
                        current_lev,
                        msg,
                    )
                    raise
                suggested = clamp_leverage_hard(suggested, config_max=config_max)
                logger.warning(
                    "Risk tier limit | %s | reduzindo alavancagem %dx -> %dx",
                    symbol,
                    current_lev,
                    suggested,
                )
                current_lev = suggested
                leverage = await self.set_leverage(symbol, current_lev)
                current_lev = leverage
                last_exc = exc

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Falha inesperada ao criar ordem market")

    async def create_market_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Cria ordem a mercado."""
        try:
            order = await self._submit_market_order(symbol, side, amount, params)
            logger.info(
                "Ordem market criada | %s %s amount=%s id=%s",
                side,
                symbol,
                amount,
                order.get("id"),
            )
            return order
        except Exception:
            logger.exception("Erro ao criar ordem market | %s %s", side, symbol)
            raise

    async def create_stop_loss_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        stop_price: float,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Cria ordem de stop loss."""
        exchange = self._ensure_connected()
        resolved = self.resolve_symbol(symbol)
        order_params: dict[str, Any] = {
            "stopLossPrice": stop_price,
            "triggerPrice": stop_price,
            **(params or {}),
        }
        try:
            order = await exchange.create_order(
                resolved,
                "market",
                side,
                amount,
                params=order_params,
            )
            logger.info("SL criado | %s @ %s", symbol, stop_price)
            return order
        except Exception:
            logger.exception("Erro ao criar SL | %s @ %s", symbol, stop_price)
            raise

    async def create_take_profit_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        take_profit_price: float,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Cria ordem de take profit."""
        exchange = self._ensure_connected()
        resolved = self.resolve_symbol(symbol)
        order_params: dict[str, Any] = {
            "takeProfitPrice": take_profit_price,
            "triggerPrice": take_profit_price,
            **(params or {}),
        }
        try:
            order = await exchange.create_order(
                resolved,
                "limit",
                side,
                amount,
                take_profit_price,
                params=order_params,
            )
            logger.info("TP criado | %s @ %s", symbol, take_profit_price)
            return order
        except Exception:
            logger.exception("Erro ao criar TP | %s @ %s", symbol, take_profit_price)
            raise

    async def execute_trade_with_protection(
        self,
        symbol: str,
        side: str,
        amount: float,
        stop_loss: float,
        take_profits: list[float],
        leverage: int,
    ) -> dict[str, Any]:
        """
        Executa trade com SL e TPs simultâneos.

        Zero DCA — ordem única de entrada com proteções despachadas em paralelo.
        """
        runtime = self._runtime.reload() if self._runtime else None
        config_max = runtime.risk.max_leverage if runtime else ABSOLUTE_MAX_LEVERAGE
        leverage = clamp_leverage_hard(leverage, config_max=config_max)
        leverage = await self.set_leverage(symbol, leverage)

        entry_order, leverage = await self._create_market_order_with_risk_retry(
            symbol, side, amount, leverage
        )

        close_side = "sell" if side == "buy" else "buy"
        tp_amount = amount / max(len(take_profits), 1)

        protection_tasks = [
            self.create_stop_loss_order(symbol, close_side, amount, stop_loss),
            *[
                self.create_take_profit_order(symbol, close_side, tp_amount, tp)
                for tp in take_profits
            ],
        ]

        protection_results = await asyncio.gather(
            *protection_tasks,
            return_exceptions=True,
        )

        errors = [r for r in protection_results if isinstance(r, Exception)]
        if errors:
            logger.error(
                "Falha parcial em proteções | symbol=%s | errors=%d",
                symbol,
                len(errors),
            )

        return {
            "entry": entry_order,
            "protections": protection_results,
            "symbol": symbol,
            "side": side,
            "amount": amount,
        }
