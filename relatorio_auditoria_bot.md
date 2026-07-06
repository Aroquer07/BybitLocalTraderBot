# 🚨 Auditoria Forense de Algoritmo - Bybit Bot

## 1. Resumo Executivo e Diagnóstico Principal

**Período analisado:** 2026-06-29 → 2026-07-06 (7 dias) | **Modo:** DEMO | **Fonte:** API Bybit V5 (closed PnL, executions, transaction log)

### Diagnóstico Letal

**O edge direcional da estratégia é quase neutro (~-$363 antes de taxas), mas a estrutura de execução com alavancagem ~20x e múltiplos fills parciais gera $3.161 em taxas — que convertem um resultado marginal em sangria de -$3.524.**

O bot apresenta win rate aparente de **56,7%** nos *fechamentos* da API, mas isso é enganoso: cada TP parcial conta como um "win" separado. Agrupando por posição lógica (símbolo + lado + preço de entrada), o win rate real cai para **47,6%** (49W / 54L em 103 trades), com **Profit Factor 0,69**.

A falha letal é a **combinação de três vetores**:

1. **Assimetria R:R realizada invertida** — Average Win $90,77 vs |Average Loss| $166,60 (ratio 0,54:1) nos fechamentos; em trades lógicos: +$162,79 vs -$212,98.
2. **Taxas comem ~90% do prejuízo** — $3.161 em trading fees sobre -$3.524 de PnL; sem taxas, o período seria ~-$363.
3. **Stops com slippage severo em alts** — média 3,3% entre preço da ordem e execução em 116 triggers; picos de 13% em SOON, AVA, XAN.

Fatores contribuintes adicionais:
- **1 liquidação** (VANRYUSDT, -$172,31) — evidência de margem insuficiente em posição concentrada
- **Maior loss isolado: BTWUSDT -$1.337** (8x lev) — stop executou 7% além do preço ordenado
- **Alavancagem observada até 50x** em NEAR/OP apesar de `max_leverage=30` no config — risco de tier não respeitado
- **171 closed-PnL records vs 91 trades no journal** — contagem inflada de wins por TPs parciais (50/30/20%)

---

## 2. Métricas Quantitativas Extraídas da API

| Métrica | Valor |
|---------|-------|
| **Fechamentos API (closed PnL records)** | 171 |
| **Trades lógicos (agrupados)** | 103 |
| Wins / Losses (fechamentos) | 97W / 74L |
| Wins / Losses (trades lógicos) | 49W / 54L |
| Win Rate (fechamentos) | 56,7% |
| Win Rate (trades lógicos) | **47,6%** |
| **PnL Realizado Total** | **-$3.523,90** |
| PnL estimado antes de taxas | -$363,00 |
| Average Win (fechamentos) | $90,77 |
| Average Loss (fechamentos) | -$166,60 |
| Win/Loss Size Ratio | **0,54:1** |
| Average Win / Loss (trades lógicos) | $162,79 / -$212,98 |
| Median Win / Median Loss | $74,45 / -$78,99 |
| Maior Win / Maior Loss | $523,20 / **-$1.337,13** |
| **Profit Factor** | **0,71** |
| Gross Win / Gross Loss | $8.804 / $12.328 |
| **Max Drawdown (cumulativo)** | **$4.097,48** |
| Alavancagem Média (API) | 19,7x |
| Alavancagem Média (journal) | 24,5x |
| **Taxas Trading (openFee+closeFee)** | **$3.160,89** |
| Taxas Trading (execuções) | $3.234,66 |
| Funding Fees (SETTLEMENT net) | -$3,34 |
| Funding Fees (absoluto) | $59,73 |
| **Impacto Taxas no PnL** | **89,7%** do prejuízo |
| Execuções totais | 309 |
| Fills de Stop/Trigger | 116 |
| Slippage médio (stops) | 3,30% |
| Slippage mediano (stops) | 3,97% |
| Slippage máximo observado | 12,99% |
| TP1 R:R planejado (journal) | 1,51:1 |
| Distância SL média (journal) | 0,94% |
| Qty média Win vs Loss | 116.807 vs 546.807 (ratio 0,21) |

### Top 10 Perdas que Destruíram o PnL

| Símbolo | PnL | Entry | Exit | Lev | Taxas |
|---------|-----|-------|------|-----|-------|
| BTWUSDT | -$1.337 | 0.08209 | 0.07685 | 8x | $21,94 |
| WLFIUSDT | -$1.107 | 0.0562 | 0.05685 | **25x** | $96,64 |
| NEARUSDT | -$640 | 2.0469 | 2.0349 | **50x** | $100,81 |
| ZECUSDT | -$619 | 454.99 | 459.68 | 25x | $59,98 |
| XLMUSDT | -$585 | 0.20061 | 0.2028 | 25x | $54,26 |
| DASHUSDT | -$489 | 35.73 | 36.00 | 25x | $63,12 |
| XPLUSDT | -$475 | 0.11082 | 0.10946 | 20x | $38,87 |
| OPUSDT | -$453 | 0.10728 | 0.10657 | **50x** | $63,51 |
| AVAXUSDT | -$414 | 6.819 | 6.872 | 25x | $51,28 |
| FARTCOINUSDT | -$381 | 0.16199 | 0.16334 | 20x | $44,55 |

**Os 10 maiores losses somam ~-$5.500** — mais que o prejuízo total, compensados parcialmente por wins menores e fragmentados.

---

## 3. Análise de Execução e Divergências

### 3.1 Slippage em Stop Loss

| Símbolo | Side | Order Price | Exec Price | Slippage | Fee |
|---------|------|-------------|------------|----------|-----|
| XANUSDT | Sell | 0.011487 | 0.012745 | **10,95%** | $5,09 |
| SOONUSDT | Buy | 0.19101 | 0.1724 | **9,74%** | $5,69 |
| BTWUSDT | Sell | 0.07183 | 0.07685 | **6,99%** | $10,61 |
| RAVEUSDT | Buy | 0.30339 | 0.2827 | **6,82%** | $8,40 |
| DASHUSDT | Sell | 33.87 | 36.12 | **6,64%** | $10,97 |

Em alts de baixa liquidez, stop-market executa significativamente além do trigger. O loss de BTWUSDT (-$1.337) correlaciona diretamente com slippage de 7% no stop — o SL teórico do journal não foi o preço de execução real.

### 3.2 Entradas Market com Slippage Extremo

- **AVAUSDT** Buy Market: slippage **12,99%** (ordem 0.2017 → exec 0.1755)
- **SOONUSDT** Buy Market: slippage **12,87%** em múltiplas entradas

Entradas market em pares ilíquidos já iniciam a posição em desvantagem estrutural antes do SL ser testado.

### 3.3 Comportamento Assimétrico Win/Loss

- **21 wins** com movimento de preço <0,5% — TPs parciais capturando fatias pequenas
- **46 losses** com movimento >0,3% — stops fechando volume total ou majoritário
- **Ratio qty win/loss: 0,21** — wins fecham ~5x menos contratos que losses
- Config `tp_close_pcts: [50, 30, 20]` + SL no restante = estrutura que **trunca lucros e preserva perdas inteiras**

### 3.4 Liquidação Detectada

- **2026-07-04 13:16 UTC** — VANRYUSDT LIQUIDATION: **-$172,31** (qty 1.021.103, preço 0.003178)
- Indica que em pelo menos uma posição a margem foi insuficiente — o bot não registrou isso distintamente no journal (`close_reason=position_closed_on_exchange`)

### 3.5 Divergências Journal vs API

| Observação | Journal | API |
|------------|---------|-----|
| Trades fechados | 91 | 171 records |
| Win Rate | ~42% (38W/53L) | 56,7% (fechamentos) |
| PnL estimado (journal) | -$1.128 | -$3.524 |

- Journal subestima perdas (sync passivo com `mark price` no fechamento, não PnL real da exchange)
- Divergências de exit price >0,5% em FARTCOIN (2,1%), APE (1,6%), ZEN (1,4%)
- `close_reason=position_closed_on_exchange` em 100% — sem distinção TP1/TP2/TP3/SL/liquidação

### 3.6 Alavancagem Acima do Config

Registros com leverage **50x** (NEAR, OP) e **25x** frequentes, apesar de `max_leverage=30` e `min_leverage=10` em `settings.json`. Possível interação com risk tiers da Bybit ou decisão da LLM/scanner não clampada uniformemente.

---

## 4. Mapeamento de Vulnerabilidades Críticas

### 4.1 Assimetria R:R Estrutural (Causa Raiz #1)

- TP1 R:R planejado médio: **1,51:1** — teoricamente viável com 47-57% WR
- R:R **realizado**: **0,54:1** — catastroficamente invertido
- Mecanismo: 50% da posição fecha no TP1 (~1% de movimento); se o restante 50% bate SL (~1% contra), o loss líquido supera o win parcial
- Com 20x, movimento de 1% = 20% ROE; mas fees sobre notional completo em cada fill corroem o edge

### 4.2 Hemorragia de Custos (Causa Raiz #2)

- **$3.161 em taxas** sobre 171 fechamentos = ~$18,50/fill médio
- Fee rate observado: 0,055% (taker) sobre notional médio elevado por 20x leverage
- Cada ciclo TP parcial = 2 fills (open + close fee) → **3 TPs + 1 SL = até 8 fills por trade**
- Funding marginal (-$3,34 neto) — não é o vilão; **trading fees são**
- Sem taxas, PnL do período seria **~-$363** (quase breakeven direcional)

### 4.3 Execução de Stop Loss (Causa Raiz #3)

- 116 execuções stop/trigger com slippage médio **3,3%**
- Em alts (SOON, AVA, XAN, BTW), slippage >7% transforma SL de 1% em loss efetivo de 8%+
- Stop-market sem proteção de preço máximo em baixa liquidez

### 4.4 Comportamento de Margem

- 1 liquidação confirmada (VANRYUSDT)
- 0 eventos ADL
- 3 slots concorrentes × 5% max position × 20x = exposição teórica de 300% do saldo em notional
- `max_portfolio_risk_pct=3%` pode ser violado quando múltiplas posições movem contra simultaneamente
- Loss tail concentrado: top 10 losses = 156% do prejuízo total

### 4.5 Divergência Lógica vs Execução

- Estratégia calcula SL/TP em TF 5m com Fibonacci/IMBA — níveis teoricamente coerentes (SL ~0,94%, TP1 R:R ~1,5)
- Execução degrada níveis via: slippage market entry, SL trigger slippage, fees, e parciais assimétricos
- Journal não captura fees, slippage, nem tipo de fechamento — impossível auditar sem API
- Win rate reportado (54,8% / 86W/71L) provavelmente conta fechamentos, não trades — **confirma viés otimista**

---

## 5. Próximos Passos (Isolamento de Risco)

Antes de qualquer alteração na lógica de trade, a arquitetura precisa:

1. **Parar de operar ou reduzir para 5x** até reconciliação completa — o sistema perde dinheiro mesmo com direção quase certa
2. **Implementar reconciliação trade-level** — agrupar closed-PnL por posição (orderLinkId/entry) para métricas honestas de WR e PF
3. **Auditar os 10 mega-losses** — BTW, WLFI, NEAR, ZEC: cruzar SL planejado vs exec price vs liquidação estimada
4. **Quantificar custo por trade** — fee/notional/leverage; meta: fees < 20% do risco por trade
5. **Investigar leverage 50x** — rastrear origem (LLM decision vs exchange tier vs bug no clamp)
6. **Validar journal sync** — substituir `position_closed_on_exchange` por parsing real de execution list
7. **Simular R:R pós-parciais** — backtest com tp_close_pcts [50,30,20] vs resultado real para confirmar assimetria
8. **Blacklist temporária de alts ilíquidos** — SOON, AVA, XAN, BTW, VANRY mostraram slippage/liquidação inaceitáveis

---

*Relatório gerado em 2026-07-06 | Dados brutos em `data/audit/` (closed_pnl.json, executions.json, transaction_log.json, analysis_summary.json)*
