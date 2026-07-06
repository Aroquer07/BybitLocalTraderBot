"""Parsing robusto de sinais Telegram — variantes Mack/VIP."""

from __future__ import annotations

import re
from typing import Any

from src.models.schemas import TradeDirection

# --- Preço / decimal ---

_PRICE_TOKEN = re.compile(r"\$?\s*([\d][\d.,]*)")

_ENTRY_LINE = re.compile(
    r"(?:📍|📥|🎯)?\s*(?:entrada|entry|zona\s+de\s+entrada)"
    r"(?:\s*\([^)]*\))?"
    r"\s*:?\s*"
    r"(?P<rest>.+?)(?:\n|$)",
    re.IGNORECASE,
)

_SL_PATTERN = re.compile(
    r"(?:🛡\s*)?(?:stop\s*loss|stop|\bsl\b)"
    r"(?:\s*\([^)]*\))?"
    r"\s*[:\- ]?\s*\$?(?P<price>[\d.,]+)",
    re.IGNORECASE,
)

_TP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:take\s*profit\s*\d+\s*\(tp\d+\)|tp\d+)\s*:?\s*(?:→\s*)?\$?([\d.,]+)",
        re.IGNORECASE,
    ),
    re.compile(r"(?:^|\n)\s*\d+️⃣\s*:?\s*\$?([\d.,]+)", re.IGNORECASE),
    re.compile(r"(?:^|\n)\s*tp\s*\d+\s+\$?([\d.,]+)", re.IGNORECASE),
    re.compile(r"(?:^|\n)\s*tp\d+\s*→\s*\$?([\d.,]+)", re.IGNORECASE),
    re.compile(r"tp\s*\d+\s+\$?([\d.,]+)", re.IGNORECASE),
)

_SYMBOL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"#\s*([A-Z]{2,12})USDT\b", re.IGNORECASE),
    re.compile(r"\b([A-Z]{2,12})USDT\b", re.IGNORECASE),
    re.compile(
        r"(?:DAY\s*TRADE|SWING(?:\s*T[ÉE]CNICO)?|SINAL)\s*[-–]\s*([A-Z]{2,12})USDT",
        re.IGNORECASE,
    ),
    re.compile(r"Moeda:\s*([A-Z]{2,12})USDT", re.IGNORECASE),
    re.compile(r"🚨\s*([A-Z]{2,12})\s*[—–\-]", re.IGNORECASE),
    re.compile(
        r"(?:LONG|SHORT|Long|Short)\s+\$?([A-Z]{2,12})\s*[🔽⬆️📉📈⬇️\n]",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:LONG|SHORT|Long|Short)\s+\$?([A-Z]{2,12})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|\s)([A-Z]{2,10})\s*[—–\-]\s*(?:LONG|SHORT)\b",
        re.IGNORECASE | re.MULTILINE,
    ),
)

_DIRECTION_EXPLICIT = re.compile(
    r"dire[cç][aã]o\s*:\s*(LONG|SHORT|COMPRA|VENDA)",
    re.IGNORECASE,
)
_DIRECTION_HEADER = re.compile(
    r"^(?:LONG|SHORT|Long|Short)\b",
    re.IGNORECASE | re.MULTILINE,
)
_DIRECTION_WORD = re.compile(
    r"\b(LONG|SHORT|COMPRA|VENDA|BUY|SELL)\b",
    re.IGNORECASE,
)

_LEVERAGE_RANGE = re.compile(
    r"(\d+)\s*x\s*(?:a|~|//|/|\-)\s*(\d+)\s*x",
    re.IGNORECASE,
)
_LEVERAGE_SINGLE = re.compile(r"(\d+)\s*x", re.IGNORECASE)

_NOISE_PATTERN = re.compile(
    r"\b(atingido|banng|confirmad|derretendo|parab[eé]ns|obrigad|"
    r"trade\s+ativa\s+j[aá]\s+preenchida|ordem\s+ativa)\b",
    re.IGNORECASE,
)
_STRUCTURE_PATTERN = re.compile(
    r"(entrada|entry|stop\s*loss|\bsl\b[: ]|🛑|tp\d|take\s*profit|alvos?)",
    re.IGNORECASE,
)


def parse_decimal_token(raw: str) -> float | None:
    """Converte token numérico BR/US (vírgula decimal, ponto milhar)."""
    s = raw.strip().replace("$", "").replace(" ", "")
    if not s:
        return None

    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        left, _, right = s.partition(",")
        if right.isdigit() and len(right) <= 8:
            s = f"{left}.{right}"
        else:
            s = s.replace(",", "")

    try:
        return float(s)
    except ValueError:
        return None


def normalize_symbol_price(price: float, base: str | None) -> float:
    """BTC costuma vir abreviado (63.350 = 63350)."""
    if base and base.upper() == "BTC" and price < 1000:
        return price * 1000
    return price


def _base_from_symbol(symbol: str | None) -> str | None:
    if not symbol:
        return None
    return symbol.split("/")[0].upper()


def _extract_prices_from_chunk(chunk: str) -> list[float]:
    prices: list[float] = []
    for match in _PRICE_TOKEN.finditer(chunk):
        val = parse_decimal_token(match.group(1))
        if val is not None and val > 0:
            prices.append(val)
    return prices


def extract_symbol(text: str) -> str | None:
    for pattern in _SYMBOL_PATTERNS:
        match = pattern.search(text)
        if match:
            base = match.group(1).upper()
            if base in ("LONG", "SHORT", "DAY", "SWING", "SINAL", "TRADE"):
                continue
            return f"{base}/USDT"
    return None


def extract_direction(text: str) -> TradeDirection | None:
    match = _DIRECTION_EXPLICIT.search(text)
    if match:
        word = match.group(1).upper()
    else:
        header = _DIRECTION_HEADER.search(text)
        if header:
            word = header.group(0).upper()
        else:
            found = _DIRECTION_WORD.search(text)
            if not found:
                return None
            word = found.group(1).upper()

    if word in ("LONG", "COMPRA", "BUY"):
        return TradeDirection.LONG
    return TradeDirection.SHORT


def extract_entry_range(
    text: str,
    symbol: str | None = None,
) -> tuple[float | None, float | None]:
    """Retorna (min, max) da zona de entrada."""
    base = _base_from_symbol(symbol)
    match = _ENTRY_LINE.search(text)
    if not match:
        return None, None

    prices = _extract_prices_from_chunk(match.group("rest"))
    if not prices:
        return None, None

    prices = [normalize_symbol_price(p, base) for p in prices]
    return min(prices), max(prices)


def extract_entry_price(text: str, symbol: str | None = None) -> float | None:
    """Preço de entrada (média da zona ou valor único)."""
    lo, hi = extract_entry_range(text, symbol)
    if lo is None:
        return None
    if hi is None or hi == lo:
        return lo
    return (lo + hi) / 2


def extract_stop_loss(text: str, symbol: str | None = None) -> float | None:
    base = _base_from_symbol(symbol)
    match = _SL_PATTERN.search(text)
    if not match:
        return None
    val = parse_decimal_token(match.group("price"))
    if val is None or val <= 0:
        return None
    return normalize_symbol_price(val, base)


def extract_take_profits(text: str, symbol: str | None = None) -> list[float]:
    base = _base_from_symbol(symbol)
    seen: set[float] = set()
    out: list[float] = []

    for pattern in _TP_PATTERNS:
        for match in pattern.finditer(text):
            val = parse_decimal_token(match.group(1))
            if val is None or val <= 0:
                continue
            val = normalize_symbol_price(val, base)
            if val not in seen:
                seen.add(val)
                out.append(val)

    return out


def extract_leverage(text: str) -> int | None:
    range_match = _LEVERAGE_RANGE.search(text)
    if range_match:
        return int(range_match.group(2))
    values = [int(m.group(1)) for m in _LEVERAGE_SINGLE.finditer(text)]
    if not values:
        return None
    return max(values)


def is_trade_signal(text: str) -> bool:
    """Filtra chat/celebração — exige estrutura mínima de trade."""
    if len(text.strip()) < 20:
        return False

    symbol = extract_symbol(text)
    direction = extract_direction(text)
    if not symbol or not direction:
        return False

    if _NOISE_PATTERN.search(text) and not _STRUCTURE_PATTERN.search(text):
        return False

    entry = extract_entry_price(text, symbol)
    sl = extract_stop_loss(text, symbol)
    tps = extract_take_profits(text, symbol)

    if sl and (entry or tps):
        return True
    if entry and len(tps) >= 1 and sl:
        return True
    if len(tps) >= 2 and sl and entry:
        return True
    return False


def parse_signal_fields(text: str) -> dict[str, Any]:
    """Extrai todos os campos de um texto de sinal."""
    symbol = extract_symbol(text)
    direction = extract_direction(text)
    entry_min, entry_max = extract_entry_range(text, symbol)
    entry = extract_entry_price(text, symbol)
    return {
        "symbol": symbol,
        "direction": direction,
        "entry_price": entry,
        "entry_zone_min": entry_min,
        "entry_zone_max": entry_max,
        "stop_loss": extract_stop_loss(text, symbol),
        "take_profits": extract_take_profits(text, symbol),
        "leverage": extract_leverage(text),
        "is_trade_signal": is_trade_signal(text),
    }
