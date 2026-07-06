"""Testes de parsing Telegram com variantes reais do grupo."""

from __future__ import annotations

import json
from pathlib import Path

from src.models.schemas import TradeDirection
from src.utils.telegram_parse import (
    extract_entry_price,
    extract_stop_loss,
    extract_symbol,
    extract_take_profits,
    is_trade_signal,
    parse_decimal_token,
    parse_signal_fields,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "topic_signals.json"

SEI_DAYTRADE = """🚨 DAY TRADE - SEIUSDT 🚨
📊 Direção: LONG 🟢
🔻 Entrada: 0,04930 — 0,04990
🛑 Stop: 0,04790
🎯 TP1: 0,05100 | R:R 1:1,6
🎯 TP2: 0,05250 | R:R 1:2,9
🎯 TP3: 0,05400 | R:R 1:4,1
#DayTrade #SEIUSDT"""

SEI_SHORT = """🚨 SEI — SHORT 📉
📥 Entrada: 0.04970
🎯 Take Profit 1 (TP1): 0.04866
🎯 Take Profit 2 (TP2): 0.04740
💢 Stop Loss: 0.05089"""

MACK_BTC = """SHORT BTC 🔽
Entrada: 63.350 - 63.450
SL: 64.000
TP1: 62.900
TP2: 62.200
TP3: 61.000"""

HUMBAS = """LONG $BTC 📈
🎯Entrada: $63540 — $63700
🛡Stop Loss: $63470
📌 ALVOS:
1️⃣: $64780 (70%)
2️⃣: $65750 (30%)"""

HBAR = """🟢 LONG #HBARUSDT ·
📍 Entrada: 0.07148/0.071
🛑 Stop: 0.070031
TP1: 0.071873
TP2: 0.073129"""

NOISE = "BAAAAANNNNGGG!!!! SOL TP1 ATINGIDO E DERRETENDO"


class TestDecimalParse:
    def test_brazilian_comma(self) -> None:
        assert parse_decimal_token("0,04930") == 0.04930

    def test_us_dot(self) -> None:
        assert parse_decimal_token("0.04970") == 0.04970


class TestSignalVariants:
    def test_sei_daytrade_members(self) -> None:
        assert is_trade_signal(SEI_DAYTRADE)
        f = parse_signal_fields(SEI_DAYTRADE)
        assert f["symbol"] == "SEI/USDT"
        assert f["direction"] == TradeDirection.LONG
        assert f["entry_price"] == 0.0496
        assert f["stop_loss"] == 0.0479
        assert len(f["take_profits"]) == 3

    def test_sei_short(self) -> None:
        f = parse_signal_fields(SEI_SHORT)
        assert f["symbol"] == "SEI/USDT"
        assert f["direction"] == TradeDirection.SHORT
        assert f["entry_price"] == 0.04970
        assert f["stop_loss"] == 0.05089
        assert f["take_profits"] == [0.04866, 0.04740]

    def test_mack_btc_abbreviated(self) -> None:
        f = parse_signal_fields(MACK_BTC)
        assert f["symbol"] == "BTC/USDT"
        assert f["entry_price"] == 63400.0
        assert f["stop_loss"] == 64000.0
        assert f["take_profits"][0] == 62900.0

    def test_humbas_emoji_targets(self) -> None:
        f = parse_signal_fields(HUMBAS)
        assert f["symbol"] == "BTC/USDT"
        assert f["entry_price"] == 63620.0
        assert f["stop_loss"] == 63470.0
        assert 64780.0 in f["take_profits"]

    def test_hbar_hash_format(self) -> None:
        f = parse_signal_fields(HBAR)
        assert f["symbol"] == "HBAR/USDT"
        assert f["entry_price"] is not None
        assert f["stop_loss"] == 0.070031
        assert len(f["take_profits"]) >= 2

    def test_noise_not_signal(self) -> None:
        assert not is_trade_signal(NOISE)


class TestTopicSamplesCoverage:
    def test_parse_rate_on_exported_samples(self) -> None:
        if not SAMPLES.exists():
            return
        data = json.loads(SAMPLES.read_text(encoding="utf-8"))
        trade_like = [
            m["text"]
            for m in data
            if any(
                k in m["text"].upper()
                for k in ("ENTRADA", "STOP", "TP1", "LONG", "SHORT")
            )
            and "ATINGIDO" not in m["text"].upper()
            and "BANNG" not in m["text"].upper()
        ]
        parsed = [t for t in trade_like if is_trade_signal(t)]
        assert len(parsed) >= 15, f"só {len(parsed)}/{len(trade_like)} parseados"

        gaps = []
        for text in trade_like:
            if not is_trade_signal(text):
                continue
            sym = extract_symbol(text)
            entry = extract_entry_price(text, sym)
            sl = extract_stop_loss(text, sym)
            tps = extract_take_profits(text, sym)
            if not (entry and sl and tps):
                gaps.append(text[:80])
        assert len(gaps) <= 8, f"gaps ({len(gaps)}): {gaps[:3]}"
