"""Testa conexão Bybit (testnet, demo ou live) via ExchangeClient."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config.settings import get_settings
from src.services.exchange_client import ExchangeClient
from src.services.runtime_config_store import RuntimeConfigStore
from src.utils.logger import get_logger, setup_logging

try:
    from ccxt.base.errors import AuthenticationError
except ImportError:
    from ccxt import AuthenticationError

logger = get_logger(__name__)

SAMPLE_SYMBOL = "BTC/USDT"
TIMEFRAME = "15m"

MODE_LABELS = {
    "testnet": "Testnet (sandbox - api-testnet.bybit.com)",
    "demo": "Demo Trading (paper mainnet - api-demo.bybit.com)",
    "live": "Live (conta real - api.bybit.com)",
}

MODE_CREDENTIAL_HINTS = {
    "testnet": "BYBIT_TESTNET_API_KEY / BYBIT_TESTNET_API_SECRET",
    "demo": "BYBIT_DEMO_API_KEY / BYBIT_DEMO_API_SECRET",
    "live": "BYBIT_API_KEY / BYBIT_API_SECRET",
}


def ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def fail(msg: str) -> None:
    print(f"  [FALHA] {msg}")


def info(msg: str) -> None:
    print(f"  {msg}")


async def main() -> int:
    settings = get_settings()
    runtime = RuntimeConfigStore(settings.settings_path).reload()
    setup_logging(runtime.log_level, runtime.log_format)
    mode = settings.bybit_mode

    print("=" * 60)
    print("Teste de conexão Bybit")
    print("=" * 60)

    info(f"Modo ativo: {mode.upper()} - {MODE_LABELS[mode]}")
    info(f"Tipo de mercado: {settings.bybit_market_type}")
    info(f"Estilos permitidos: {', '.join(runtime.telegram.allowed_trade_styles)}")
    info(f"Estilos rejeitados: {', '.join(runtime.telegram.reject_trade_styles)}")
    print()

    client = ExchangeClient(settings)
    errors: list[str] = []
    auth_ok = True

    try:
        print("--- Conectando ---")
        await client.connect()
        ok("Conexão estabelecida com sucesso")
    except Exception as exc:
        fail(f"Não foi possível conectar: {exc}")
        logger.exception("Erro na conexão Bybit")
        return 1

    try:
        print(f"\n--- Verificação de modo ({mode}) ---")
        ok(f"BYBIT_MODE={mode} confirmado nas settings")

        print("\n--- Mercados carregados ---")
        counts = client.count_markets_by_type()
        info(f"Linear swap (perpetual): {counts['linear_swap']}")
        info(f"Spot: {counts['spot']}")
        info(f"Inverse: {counts['inverse']}")
        info(f"Outros: {counts['other']}")

        if counts["linear_swap"] > 0:
            ok(f"Apenas mercados linear/swap serão usados ({counts['linear_swap']} disponíveis)")
        else:
            errors.append("Nenhum mercado linear swap encontrado")

        if settings.bybit_market_type == "linear_swap":
            ok("BYBIT_MARKET_TYPE=linear_swap - spot sera rejeitado no resolve_symbol")

        print("\n--- Resolução de símbolo ---")
        resolved = client.resolve_symbol(SAMPLE_SYMBOL)
        info(f"{SAMPLE_SYMBOL} -> {resolved}")
        if ":USDT" in resolved:
            ok("Símbolo resolvido para perpetual futures (formato :USDT)")
        else:
            ok(f"Símbolo resolvido: {resolved}")

        print("\n--- Saldo (requer API key válida) ---")
        try:
            balance = await client.fetch_balance()
            usdt = balance.get("USDT", {})
            total = usdt.get("total")
            free = usdt.get("free")
            info(f"USDT total: {total} | livre: {free}")
            ok("Saldo obtido com sucesso")
        except AuthenticationError:
            auth_ok = False
            creds = MODE_CREDENTIAL_HINTS[mode]
            fail(f"API key invalida - verifique {creds} no .env")
            if mode == "testnet":
                info("Dica: gere chaves em https://testnet.bybit.com (API Management)")
            elif mode == "demo":
                info("Dica: gere chaves em Bybit mainnet -> Demo Trading -> API")
        except Exception as exc:
            auth_ok = False
            errors.append(f"Saldo: {exc}")
            fail(f"Erro ao buscar saldo: {exc}")

        print(f"\n--- Ticker ({SAMPLE_SYMBOL}) ---")
        try:
            ticker = await client.fetch_ticker(SAMPLE_SYMBOL)
            last = ticker.get("last") or ticker.get("close")
            info(f"Último preço: {last}")
            ok("Ticker obtido com sucesso")
        except Exception as exc:
            errors.append(f"Ticker: {exc}")
            fail(f"Erro ao buscar ticker: {exc}")

        print(f"\n--- OHLCV ({SAMPLE_SYMBOL} {TIMEFRAME}) ---")
        try:
            ohlcv = await client.fetch_ohlcv(SAMPLE_SYMBOL, timeframe=TIMEFRAME, limit=5)
            info(f"Candles retornados: {len(ohlcv)}")
            if ohlcv:
                last_candle = ohlcv[-1]
                info(
                    f"Último candle: ts={last_candle[0]} "
                    f"O={last_candle[1]} H={last_candle[2]} "
                    f"L={last_candle[3]} C={last_candle[4]}"
                )
            ok("OHLCV obtido com sucesso")
        except Exception as exc:
            errors.append(f"OHLCV: {exc}")
            fail(f"Erro ao buscar OHLCV: {exc}")

        print("\n--- Rejeição de spot (sanidade) ---")
        try:
            client.resolve_symbol("ETH/USDT")
            ok("ETH/USDT resolve para futures linear (não spot)")
        except ValueError as exc:
            if "não permitido" in str(exc).lower() or "spot" in str(exc).lower():
                ok(f"Spot corretamente bloqueado: {exc}")
            else:
                errors.append(str(exc))
                fail(str(exc))

    finally:
        await client.disconnect()
        info("Conexão encerrada")

    print("\n" + "=" * 60)
    if errors:
        print("RESULTADO: FALHA PARCIAL")
        for err in errors:
            print(f"  - {err}")
        return 1

    if not auth_ok:
        print(f"RESULTADO: PARCIAL - mercado publico OK, credenciais {mode} invalidas")
        print(f"Corrija {MODE_CREDENTIAL_HINTS[mode]} para operações com saldo/ordens.")
        return 1

    print(f"RESULTADO: SUCESSO - Bybit {mode} operacional")
    print("Bot configurado para daytrade/scalp em futures linear apenas.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
