"""Analisa um sinal Telegram manualmente (sem esperar mensagem ao vivo)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config.settings import get_settings
from src.controllers.brain_controller import BrainController
from src.models.schemas import TelegramSignal, TradeDirection, TradeSource
from src.services.exchange_client import ExchangeClient
from src.services.llm_client import LLMClient
from src.services.telegram_client import TelegramClient
from src.strategies.technical_analysis import TechnicalAnalysisEngine
from src.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)

SEI_MESSAGE = """🚨 SEI — SHORT 📉

Alavancagem: Ajuste de acordo com seu gerenciamento de risco

📥 Entrada: 0.04970

🎯 Take Profit 1 (TP1): 0.04866
🎯 Take Profit 2 (TP2): 0.04740

💢 Stop Loss: 0.05089

⚠️ Gerenciamento de risco:

Arrisque apenas 1% da sua banca nesta operação.
Ao atingir o TP1, considere realizar lucro parcial e mover o stop para o preço de entrada (break-even).

Não é recomendação financeira. Faça sua própria análise antes de operar."""


def build_signal_from_text(text: str, channel_id: int) -> TelegramSignal:
    from src.utils.telegram_parse import parse_signal_fields

    fields = parse_signal_fields(text)
    return TelegramSignal(
        message_id=0,
        channel_id=channel_id,
        raw_text=text,
        symbol=fields["symbol"],
        direction=fields["direction"],
        entry_price=fields["entry_price"],
        stop_loss=fields["stop_loss"],
        take_profits=fields["take_profits"],
        leverage=fields["leverage"],
    )


async def main() -> int:
    settings = get_settings()
    setup_logging()

    signal = build_signal_from_text(SEI_MESSAGE, settings.telegram_channel_id)
    print("=" * 60)
    print("SINAL PARSEADO")
    print("=" * 60)
    print(f"  Symbol:    {signal.symbol}")
    print(f"  Direction: {signal.direction}")
    print(f"  Entry:     {signal.entry_price}")
    print(f"  SL:        {signal.stop_loss}")
    print(f"  TPs:       {signal.take_profits}")
    print()

    if not signal.symbol or not signal.direction:
        print("FALHA: não conseguiu parsear símbolo ou direção")
        return 1

    exchange = ExchangeClient(settings)
    llm = LLMClient(settings)
    ta = TechnicalAnalysisEngine(settings)
    brain = BrainController(settings, exchange, llm, ta)

    try:
        await exchange.connect()
        print("Bybit conectado")
        ollama_ok = await llm.warmup()
        print(f"Ollama warmup: {'ok' if ollama_ok else 'falhou'}")
        print()
        print("Analisando (IMBA 3m/5m/15m + LLM)...")
        decision = await brain.process_signal(signal)

        print()
        print("=" * 60)
        print("RESULTADO DA ANÁLISE")
        print("=" * 60)
        print(f"  Aprovado:    {decision.approved}")
        print(f"  Confiança:   {decision.confidence * 100:.0f}%")
        print(f"  Threshold:   {decision.confidence_threshold * 100:.0f}%")
        print(f"  Executaria:  {decision.passes_kill_switch}")
        print(f"  Direção:     {decision.direction}")
        print(f"  Entry:       {decision.entry_price}")
        print(f"  SL:          {decision.stop_loss}")
        if decision.take_profits:
            print(f"  TPs:         {[tp.price for tp in decision.take_profits]}")
        print(f"  Viés:        {decision.bias or decision.ai_analysis}")
        if decision.formatted_output:
            print()
            print(decision.formatted_output)
        return 0
    except Exception as exc:
        logger.exception("Erro na análise")
        print(f"ERRO: {exc}")
        return 1
    finally:
        await exchange.disconnect()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
