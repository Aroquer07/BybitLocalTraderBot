"""Formatadores de saída para logs e mensagens."""

from src.models.schemas import TradeDecision, TradeDirection, TradeStyle


def format_price(price: float, decimals: int = 4) -> str:
    """Formata preço com casas decimais dinâmicas."""
    if price >= 1000:
        return f"{price:,.2f}"
    if price >= 1:
        return f"{price:,.{decimals}f}"
    return f"{price:.{decimals + 2}f}"


def format_usd(value: float) -> str:
    """Formata valor em USD com sinal."""
    if abs(value) < 0.005:
        return "$0.00"
    if value > 0:
        return f"+${value:,.2f}"
    return f"-${abs(value):,.2f}"


def format_percentage(value: float, decimals: int = 2) -> str:
    """Formata percentual com sinal."""
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{decimals}f}"


def format_rr_br(risk_reward: float) -> str:
    """Formata R:R no padrão brasileiro (vírgula decimal)."""
    formatted = f"{risk_reward:.1f}".replace(".", ",")
    return f"1:{formatted}"


def resolve_trade_style_label(
    trade_style: TradeStyle | str | None,
    trade_style_label: str | None = None,
) -> str:
    """Resolve label SCALP ou DAYTRADE para o output formatado."""
    if trade_style_label:
        return trade_style_label.upper()
    if trade_style is None:
        return "DAYTRADE"
    style_value = trade_style.value if isinstance(trade_style, TradeStyle) else trade_style
    return "SCALP" if style_value.lower() == "scalp" else "DAYTRADE"


def format_trade_decision_log(decision: TradeDecision) -> str:
    """Formata decisão de trade para log estruturado."""
    status = "APROVADO" if decision.passes_kill_switch else "RECUSADO"
    analysis_text = decision.bias or decision.ai_analysis
    analysis = (
        f"{analysis_text[:80]}..."
        if len(analysis_text) > 80
        else analysis_text
    )
    return (
        f"[{status}] conf={decision.confidence:.0%} | "
        f"{decision.direction or 'N/A'} {decision.symbol or 'N/A'} | "
        f"{analysis}"
    )


def build_formatted_trade_output(
    direction: TradeDirection,
    symbol: str,
    entry_zone_min: float,
    entry_zone_max: float,
    stop_loss: float,
    take_profits: list[tuple[float, float, float]],
    bias: str,
    entry_condition: str,
    confidence: float,
    trade_style: TradeStyle | str | None = None,
    trade_style_label: str | None = None,
) -> str:
    """Monta o layout obrigatório de output da LLM para trades aprovados."""
    direction_emoji = "🟢" if direction == TradeDirection.LONG else "🔴"
    pair = symbol.replace("/", "")
    style_label = resolve_trade_style_label(trade_style, trade_style_label)
    probability = int(round(confidence * 100))

    lines = [
        f"🚨 {style_label} TÉCNICO - {pair} 🚨",
        f"📊 Direção: {direction.value} {direction_emoji}",
        f"📈 Viés: {bias}",
        f"📌 Probabilidade: {probability}%",
        "",
        f"🔻 Entrada: {format_price(entry_zone_min)} — {format_price(entry_zone_max)}",
        f"✅ Condição: {entry_condition}",
        f"🛑 Stop: {format_price(stop_loss)}",
        "",
    ]

    for i, (price, _pct, rr) in enumerate(take_profits[:3]):
        lines.append(f"🎯 TP{i + 1}: {format_price(price)} | R:R {format_rr_br(rr)}")

    return "\n".join(lines)


def clean_bias_for_display(bias: str | None) -> str:
    """Remove metadados internos (P(win), etc.) do viés exibido no Telegram."""
    if not bias:
        return "Setup técnico confirmado"
    text = bias.strip()
    for sep in (" | P(win)=", " | P(win)"):
        if sep in text:
            text = text.split(sep)[0].strip()
    if len(text) > 120:
        return text[:117] + "..."
    return text


def entry_zone_from_decision(
    entry: float,
    stop_loss: float | None,
    direction: TradeDirection,
) -> tuple[float, float]:
    """Zona de entrada min—max para o layout do Telegram."""
    if not entry or entry <= 0:
        return 0.0, 0.0
    if stop_loss and stop_loss > 0:
        pad = abs(entry - stop_loss) * 0.12
        if direction == TradeDirection.LONG:
            return entry - pad * 0.25, entry + pad
        return entry - pad, entry + pad * 0.25
    return entry, entry


def entry_condition_from_decision(decision: TradeDecision) -> str:
    """Linha ✅ Condição do layout padrão."""
    tf = decision.execution_timeframe or "5m"
    direction = decision.direction.value if decision.direction else "N/A"
    return f"Sinal {direction} confirmado em {tf}"


def build_formatted_output_from_decision(decision: TradeDecision) -> str:
    """Monta layout completo do trade a partir da TradeDecision."""
    if not decision.direction or not decision.symbol:
        return ""

    entry = decision.entry_price or 0.0
    sl = decision.stop_loss or 0.0
    zone_min, zone_max = entry_zone_from_decision(entry, sl, decision.direction)

    tp_tuples: list[tuple[float, float, float]] = []
    for tp in decision.take_profits[:3]:
        tp_tuples.append((tp.price, tp.percentage, tp.risk_reward))

    while len(tp_tuples) < 4 and entry > 0 and sl > 0:
        risk = abs(entry - sl)
        n = len(tp_tuples) + 1
        if decision.direction == TradeDirection.LONG:
            price = entry + risk * n
        else:
            price = entry - risk * n
        pct = abs(price - entry) / entry * 100.0 if entry else 0.0
        rr = risk and abs(price - entry) / risk or float(n)
        tp_tuples.append((price, pct, rr))

    bias = clean_bias_for_display(decision.bias or decision.ai_analysis)
    condition = entry_condition_from_decision(decision)

    return build_formatted_trade_output(
        direction=decision.direction,
        symbol=decision.symbol,
        entry_zone_min=zone_min,
        entry_zone_max=zone_max,
        stop_loss=sl,
        take_profits=tp_tuples,
        bias=bias,
        entry_condition=condition,
        confidence=decision.confidence,
        trade_style=decision.trade_style,
        trade_style_label=decision.trade_style_label,
    )


def format_trade_opened_message(
    decision: TradeDecision,
    *,
    leverage: int,
    amount: float,
    bybit_mode: str,
) -> str:
    """Resumo enviado ao bot de notificações quando uma operação abre."""
    header = (
        f"✅ TRADE ABERTO | {bybit_mode.upper()} | "
        f"{decision.source.value} | {leverage}x | qty={amount:g}\n\n"
    )

    body = decision.formatted_output.strip() if decision.formatted_output else ""
    if not body or not body.startswith("🚨"):
        body = build_formatted_output_from_decision(decision)

    if not body:
        direction_emoji = "🟢" if decision.direction == TradeDirection.LONG else "🔴"
        pair = (decision.symbol or "N/A").replace("/", "")
        body = (
            f"🚨 {resolve_trade_style_label(decision.trade_style, decision.trade_style_label)} "
            f"TÉCNICO - {pair} 🚨\n"
            f"📊 Direção: {decision.direction.value if decision.direction else 'N/A'} "
            f"{direction_emoji}"
        )

    return header + body
