---
name: bybitbot
description: Agente de trading BybitBot — daytrade e scalp em futures linear com análise técnica multi-TF em Python e juiz estratégico Ollama.
---

# BybitBot — Framework de Análise Técnica

Agente quantitativo para **futures perpetual linear** na Bybit. Operações **intraday apenas**: daytrade e scalp. Sem swing, sem spot.

## Arquitetura em camadas

| Camada | Módulo | Responsabilidade |
|--------|--------|------------------|
| **Dados** | `exchange_client` | OHLCV multi-TF + orderbook via CCXT |
| **Indicadores** | `indicators.py` | TODA a matemática via pandas-ta |
| **Análise** | `technical_analysis.py` | Orquestra TFs + Fibonacci por timeframe |
| **Confluência** | `confluence.py` | Pré-score 0–100 long/short (Python) |
| **Juiz** | `llm_client.py` (Ollama qwen3) | Decisão final, SL/TPs, confidence — **sem calcular indicadores** |
| **Execução** | `position_manager` | Sizing, 4 TPs parciais, breakeven |

A LLM **NÃO calcula indicadores**. Ela lê o JSON compacto e julga confluência + sinal Telegram.

## Multi-timeframe (5m, 15m, 30m)

Configuração: `TIMEFRAMES=5m,15m,30m`

| Timeframe | Papel |
|-----------|-------|
| **5m** | Entrada fina / execução scalp |
| **15m** | Confirmação principal (TF primário) |
| **30m** | Filtro de ruído / tendência curta |

Estrutura `MarketState.timeframes`:

```json
{
  "5m": { "indicators": {}, "fibonacci": {}, "ohlcv_summary": {} },
  "15m": { "indicators": {}, "fibonacci": {}, "ohlcv_summary": {} },
  "30m": { "indicators": {}, "fibonacci": {}, "ohlcv_summary": {} }
}
```

## Indicadores (Python ONLY — pandas-ta)

### Base (obrigatório)

| Indicador | Config |
|-----------|--------|
| RSI | 6, 12, 24 |
| MACD | 12, 26, 9 |
| SMA | 7, 14, 28 |
| EMA | 7, 14, 28 |
| Volume MA | 5, 10 |
| Bollinger Bands | SMA20 ± 2 |
| Ichimoku | 9, 26, 52 (displacement 26) |
| Parabolic SAR | default |

### PRO

| Indicador | Uso |
|-----------|-----|
| Stochastic RSI | Momentum oversold/overbought |
| OBV | Confirmação de volume |
| ATR(14) | Referência de distância SL — **LLM define SL**, Python não auto-SL |
| Supertrend + ADX | Direção e força de tendência |
| VWAP | Sessão UTC intraday |
| Divergências RSI/MACD | Flags bullish/bearish |
| Fibonacci | Por timeframe (retrações + extensões + R:R) |

## Confluência (Python pre-score)

Módulo `confluence.py` calcula antes da LLM:

```json
{
  "long_score": 78,
  "short_score": 22,
  "long_checks": {
    "above_ema_ma": true,
    "above_vwap": true,
    "macd_bullish": true,
    "rsi_favorable": true,
    "bb_breakout": false,
    "ichimoku_bullish": true,
    "supertrend_adx": true
  },
  "short_checks": { "...": false },
  "recommendation": "LONG"
}
```

### Checklist LONG (espelho invertido para SHORT)

1. Preço acima EMA/MA relevantes e acima VWAP
2. MACD cruzando para cima ou histograma acelerando positivo
3. RSI saindo de oversold ou sustentando acima de 50
4. BB: breakout superior com volume OU squeeze breakout
5. Preço acima da nuvem Ichimoku, cruz Tenkan/Kijun favorável
6. Supertrend bullish + ADX ≥ 25 (força de tendência)

**Regra:** indicador isolado = **sem trade**. Python pontua; LLM julga.

## Kill switch — 90% de confiança

- `approved=true` **somente** se `confidence >= 0.90`
- Confluência Python + alinhamento Telegram são **necessários** mas não suficientes
- Abaixo de 90%: `approved=false`, trade não executa

## Gestão de risco

| Parâmetro | Default | Descrição |
|-----------|---------|-----------|
| `RISK_PER_TRADE_PCT` | 3.0 | % do saldo arriscado no SL |
| `MAX_POSITION_PCT` | 5.0 | % máximo do saldo como margem |
| `BYBIT_DEFAULT_LEVERAGE` | 15 | Alavancagem padrão |
| `BYBIT_MAX_LEVERAGE` | 30 | Alavancagem máxima |
| Zero DCA | — | Uma única entrada |

**Sizing:** Python calcula quantidade com base na distância entry → SL.

## Take profits — 4 níveis (25% cada)

| Nível | Fechamento |
|-------|------------|
| TP1 | 25% |
| TP2 | 25% |
| TP3 | 25% |
| TP4 | 25% |

**Breakeven:** ao preencher TP2, mover SL para preço de entrada na posição restante (50%).

## Fibonacci (por timeframe)

Cada TF inclui `fibonacci` com:

- `swing_high`, `swing_low`, `range`, `impulse`
- `retracements`: 0.236, 0.382, 0.5, 0.618, 0.786
- `extensions`: 1.272, 1.618, 2.0, 2.618
- `risk_reward_extensions`: R:R pré-calculado

## Papel da IA — Juiz Estratégico

1. Ler JSON multi-TF + confluência + sinal Telegram
2. **Não** recalcular indicadores
3. Validar alinhamento confluência ↔ Telegram ↔ multi-TF
4. Definir direção, zona de entrada, SL (usando ATR/Fib/SR) e 4 TPs
5. Atribuir `confidence` (0.0–1.0) — soberana sobre o pré-score Python
6. Gerar `formatted_output` no layout obrigatório

## JSON de resposta (obrigatório)

```json
{
  "approved": true,
  "confidence": 0.92,
  "trade_style": "scalp",
  "direction": "LONG",
  "symbol": "BTC/USDT",
  "entry_zone_min": 95000.0,
  "entry_zone_max": 95200.0,
  "entry_price": 95100.0,
  "stop_loss": 94500.0,
  "take_profits": [
    {"price": 95500.0, "percentage": 25.0, "risk_reward": 0.8},
    {"price": 96000.0, "percentage": 25.0, "risk_reward": 1.8},
    {"price": 96500.0, "percentage": 25.0, "risk_reward": 2.5},
    {"price": 97000.0, "percentage": 25.0, "risk_reward": 3.2}
  ],
  "bias": "Confluência long 78% com MACD bullish no 15m e tendência 30m alinhada",
  "entry_condition": "Entrada no reteste da zona 0.618 com confirmação 5m",
  "formatted_output": "..."
}
```

## Layout obrigatório — formatted_output

```
🚨 {SCALP|DAYTRADE} TÉCNICO - {PAR} 🚨
📊 Direção: {LONG|SHORT} {🟢|🔴}
📈 Viés: {texto técnico conciso}
📌 Probabilidade: {XX}%

🔻 Entrada: {preco_min} — {preco_max}
✅ Condição: {condição de ativação}
🛑 Stop: {preco_stop}

🎯 TP1: {preco} | R:R 1:{ratio}
🎯 TP2: {preco} | R:R 1:{ratio}
🎯 TP3: {preco} | R:R 1:{ratio}
🎯 TP4: {preco} | R:R 1:{ratio}
```

## Inferência Ollama

- Modelo: `qwen3:8b`
- `think=False` e sufixo `/no_think` na mensagem do usuário
- Resposta: **JSON puro**, sem markdown nem texto extra
