# AI Guidelines — BybitLocalTraderBot

Registro vivo de **erros encontrados**, **melhorias pendentes** e **decisões técnicas** descobertas em sessões de desenvolvimento ou auditoria.

> Toda sessão de IA que encontrar bugs, regressões ou melhorias relevantes **deve atualizar este arquivo** antes de encerrar o trabalho.

**Documentação canônica do projeto:** [README.md](README.md)  
**Relatório forense detalhado:** [relatorio_auditoria_bot.md](relatorio_auditoria_bot.md)  
**Injeção automática:** hook `.cursor/hooks/inject-ai-guidelines.ps1` (em `sessionStart` + cada mensagem do usuário)

---

## Como usar este arquivo

| Ação | Onde registrar |
|------|----------------|
| Bug novo ou regressão | **Adicionar** entrada em [Erros conhecidos](#erros-conhecidos-abertos) |
| Melhoria ou débito técnico | **Adicionar** entrada em [Melhorias pendentes](#melhorias-pendentes) |
| Erro/melhoria resolvido | **Adicionar** bloco `Solução` no mesmo ID + entrada em [Resolvidos](#resolvidos) |
| Mudança de arquitetura/fluxo | Atualizar **README.md** (não criar doc paralelo) |
| Alteração concluída | **Commit no Git** com mensagem clara (ver [Versionamento Git](#versionamento-git)) |

### Política de edição (append-only)

Este arquivo é um **log cumulativo** — preserva histórico para rastreabilidade.

| Permitido | Proibido (sem pedido explícito do usuário) |
|-----------|---------------------------------------------|
| Adicionar novas entradas `ERR-*`, `IMP-*`, `FIX-*` | Apagar entradas ou seções |
| Adicionar linhas/campos a entradas existentes | Reescrever ou substituir texto já registrado |
| Adicionar bloco **Solução** abaixo do erro original | Remover erro da lista porque foi corrigido |
| Adicionar `- **Status (atualização YYYY-MM-DD):** resolved` | Editar descrição/evidência já gravadas |

**Exceção:** só deletar ou substituir conteúdo quando o usuário pedir **explicitamente**.

### Formato de entrada (erro / melhoria)

```markdown
### [ID] Título curto
- **Severidade:** critical | high | medium | low
- **Área:** execução | journal | dashboard | telegram | scanner | api | infra
- **Arquivo(s):** `src/...`
- **Descrição:** o que acontece e impacto
- **Evidência:** log, métrica, link para auditoria
- **Status:** open | in_progress | blocked | resolved
- **Sugestão de fix:** (opcional)
```

### Formato ao resolver (adicionar abaixo do mesmo ID)

```markdown
#### Solução (YYYY-MM-DD)
- **O que foi feito:** descrição objetiva da correção
- **Arquivo(s) alterados:** `src/...`
- **Commit:** `fix - mensagem do commit` (hash curto se disponível)
- **Validação:** teste manual, métrica, ou como confirmar que ficou ok
```

Manter o bloco original do erro **intacto** acima. Registrar também em [Resolvidos](#resolvidos) com referência `Ref: ERR-NNN` ou `Ref: IMP-NNN`.

---

## Erros conhecidos (abertos)

### [ERR-001] R:R realizado invertido vs planejado
- **Severidade:** critical
- **Área:** execução
- **Arquivo(s):** `src/services/position_manager.py`, `data/settings.json` (`imba.tp_close_pcts`)
- **Descrição:** TP1 R:R planejado ~1,51:1, mas R:R realizado ~0,54:1. Parciais 50/30/20 truncam lucros; SL no restante gera perdas maiores que wins parciais.
- **Evidência:** [relatorio_auditoria_bot.md](relatorio_auditoria_bot.md) §4.1 — avg win $90,77 vs avg loss $166,60
- **Status:** open
- **Sugestão de fix:** simular R:R pós-parciais; revisar `tp_close_pcts` ou breakeven mais cedo

### [ERR-002] Taxas consomem ~90% do prejuízo
- **Severidade:** critical
- **Área:** execução
- **Arquivo(s):** `src/services/exchange_client.py`, `src/controllers/execution_controller.py`
- **Descrição:** $3.161 em trading fees sobre PnL -$3.524. Sem taxas, período seria ~-$363 (quase breakeven direcional). Múltiplos fills parciais amplificam custo.
- **Evidência:** [relatorio_auditoria_bot.md](relatorio_auditoria_bot.md) §4.2
- **Status:** open
- **Sugestão de fix:** reduzir fills por trade; limitar alavancagem; filtrar pares de baixa liquidez

### [ERR-003] Slippage severo em stops de alts
- **Severidade:** high
- **Área:** execução
- **Arquivo(s):** `src/services/slippage_guard.py`, `src/strategies/scanner_filters.py`
- **Descrição:** 116 triggers de stop com slippage médio 3,3%; picos >10% em SOON, AVA, XAN, BTW. Stop-market sem proteção de preço em baixa liquidez.
- **Evidência:** [relatorio_auditoria_bot.md](relatorio_auditoria_bot.md) §3.1 — BTWUSDT -$1.337 com slippage 7%
- **Status:** open
- **Sugestão de fix:** blacklist temporária de alts ilíquidos; limit orders para SL onde possível

### [ERR-004] Journal diverge da API Bybit
- **Severidade:** high
- **Área:** journal
- **Arquivo(s):** `src/services/trade_journal.py`, `src/controllers/execution_controller.py`
- **Descrição:** 91 trades no journal vs 171 closed-PnL records na API. PnL journal (-$1.128) subestima perdas reais (-$3.524). `close_reason=position_closed_on_exchange` em 100% — sem distinção TP/SL/liquidação.
- **Evidência:** [relatorio_auditoria_bot.md](relatorio_auditoria_bot.md) §3.5
- **Status:** open
- **Sugestão de fix:** reconciliação trade-level via execution list; parsing de tipo de fechamento

### [ERR-005] Alavancagem acima do config em alguns trades
- **Severidade:** high
- **Área:** execução
- **Arquivo(s):** `src/services/exchange_client.py` (`clamp_leverage_hard`)
- **Descrição:** Trades a 50x (NEAR, OP) apesar de `max_leverage=30` no settings. Pode ser tier Bybit + clamp incompleto em algum caminho.
- **Evidência:** [relatorio_auditoria_bot.md](relatorio_auditoria_bot.md) §3.6
- **Status:** open
- **Sugestão de fix:** auditar todos os call sites de `set_leverage`; logar leverage efetiva pós-fill

### [ERR-006] Liquidação não distinguida no journal
- **Severidade:** high
- **Área:** journal
- **Arquivo(s):** `src/services/trade_journal.py`
- **Descrição:** VANRYUSDT liquidado (-$172,31) registrado como `position_closed_on_exchange` genérico.
- **Evidência:** [relatorio_auditoria_bot.md](relatorio_auditoria_bot.md) §3.4
- **Status:** open

### [ERR-007] Win rate inflado por TPs parciais
- **Severidade:** medium
- **Área:** dashboard / métricas
- **Arquivo(s):** `src/api/routes/trades.py`, `dashboard/`
- **Descrição:** WR de fechamentos API (56,7%) vs trades lógicos (47,6%). Dashboard já tem `ExchangePnlCard` com agrupamento, mas journal/stats legados ainda podem confundir.
- **Evidência:** `closed_pnl_groups.py` + auditoria §1
- **Status:** open
- **Sugestão de fix:** usar `position_groups` como métrica padrão em todo o dashboard

---

## Melhorias pendentes

### [IMP-001] Persistir slippage em log estruturado
- **Prioridade:** high
- **Área:** execução
- **Arquivo(s):** `src/services/slippage_guard.py`
- **Descrição:** Alertas Telegram existem, mas não há `data/slippage_log.json` para análise histórica.
- **Status:** open

### [IMP-002] Tabela de posições agrupadas no TradesPage
- **Prioridade:** medium
- **Área:** dashboard
- **Arquivo(s):** `dashboard/src/pages/TradesPage.tsx`
- **Descrição:** Hoje só `ExchangePnlCard` no Dashboard (`/`). TradesPage deveria mostrar trades lógicos agrupados.
- **Status:** open

### [IMP-003] Journal com tipo de fechamento real
- **Prioridade:** high
- **Área:** journal
- **Arquivo(s):** `src/controllers/execution_controller.py`, `src/services/trade_journal.py`
- **Descrição:** Distinguir TP1, TP2, TP3, SL, liquidação, ADL no sync com exchange.
- **Status:** open

### [IMP-004] Reconciliação trade-level automática no journal
- **Prioridade:** high
- **Área:** journal
- **Arquivo(s):** `src/services/closed_pnl_groups.py`, `src/services/trade_journal.py`
- **Descrição:** Parcial via `GET /api/trades/exchange-pnl`; falta sync periódico journal ↔ API.
- **Status:** open

### [IMP-005] Blacklist de alts ilíquidos
- **Prioridade:** medium
- **Área:** scanner
- **Arquivo(s):** `src/strategies/scanner_filters.py`, `data/settings.json`
- **Descrição:** SOON, AVA, XAN, BTW, VANRY mostraram slippage/liquidação inaceitáveis na auditoria.
- **Status:** open

### [IMP-006] Quantificar custo por trade (fee/risco)
- **Prioridade:** medium
- **Área:** execução / relatórios
- **Descrição:** Meta: fees < 20% do risco por trade. Incluir no PnL report e dashboard.
- **Status:** open

### [IMP-007] Simular R:R pós-parciais antes de live
- **Prioridade:** high
- **Área:** estratégia
- **Descrição:** Backtest com `tp_close_pcts [50,30,20]` vs resultado real para validar assimetria estrutural.
- **Status:** open

---

## Resolvidos

> Log append-only. Cada fix referencia o `ERR-*` / `IMP-*` original. A solução detalhada fica **no mesmo bloco do erro** (seção acima); aqui fica o índice cronológico.

### [FIX-001] Hard limit de leverage 30x
- **Data:** 2026-07-06
- **Área:** execução
- **Arquivo(s):** `src/services/exchange_client.py` (`clamp_leverage_hard`)
- **Descrição:** Cap absoluto `ABSOLUTE_MAX_LEVERAGE = 30` aplicado em set_leverage, execute_trade, execution_controller, position_manager.

### [FIX-002] Agrupador de PnL (trades lógicos)
- **Data:** 2026-07-06
- **Área:** api / telegram / dashboard
- **Arquivo(s):** `src/services/closed_pnl_groups.py`, `ExchangePnlCard.tsx`
- **Descrição:** Agrupa fills por símbolo+lado+entry; expõe via `/api/trades/exchange-pnl`.

### [FIX-003] Slippage guard wired
- **Data:** 2026-07-06
- **Área:** execução
- **Arquivo(s):** `src/services/slippage_guard.py`
- **Descrição:** Alerta Telegram se slippage > 1% na entrada e audit na sync de fechamentos.

### [FIX-004] Correções LLM confidence
- **Data:** 2026-07-06
- **Área:** telegram / llm
- **Arquivo(s):** `src/services/llm_client.py`, `src/strategies/win_probability.py`
- **Descrição:** `_normalize_confidence()`, `llm_confidence` separado de P(win), retry em schema inválido.

### [FIX-005] Market screener automático (substitui CoinGlass)
- **Data:** 2026-07-06
- **Área:** scanner
- **Arquivo(s):** `src/strategies/market_screener.py`
- **Descrição:** RSI multi-TF + derivativos Bybit; modo `discovery_only`.

### [FIX-006] Gráfico Análise — níveis reais do bot no Pine
- **Data:** 2026-07-06
- **Área:** dashboard
- **Arquivo(s):** `dashboard/src/lib/pineToChart.ts`
- **Descrição:** Sobrescreve preços ENTRY/SL/TP quando `snapshot.levels` existe.

### [FIX-007] Documentação centralizada no README
- **Data:** 2026-07-06
- **Descrição:** `DOCUMENTACAO_COMPLETA.md` removido; conteúdo migrado para `README.md`. Backlog técnico em `AI_GUIDELINES.md`.

---

## Versionamento Git

Ao **final de cada alteração** (código, docs, hooks, config versionável), fazer commit no Git com mensagem clara para rastreabilidade.

### Formato de commit

```
fix - descrição curta do que foi corrigido
feat - descrição curta do que foi adicionado
docs - alterações só de documentação
refactor - mudança interna sem alterar comportamento
test - testes adicionados ou corrigidos
chore - manutenção (deps, scripts, gitignore)
```

- **Idioma:** inglês
- **Separador:** ` - ` (tipo, espaço, hífen, espaço, mensagem)
- **Sem ticket obrigatório** — não usar `fix(TICKET):` neste repo
- **Mensagem:** imperativo, específica, focada no *porquê* ou no *o quê* mudou

### Exemplos

```
fix - clamp leverage before partial TP execution
feat - add grouped positions table to TradesPage
docs - centralize architecture in README
chore - add Cursor hook to inject AI guidelines
```

### Checklist ao encerrar uma sessão com alterações

1. Revisar `git status` e `git diff` — nada de `.env`, `data/`, sessões
2. Atualizar `AI_GUIDELINES.md` se aplicável (ERR/IMP/Resolvidos)
3. Atualizar `README.md` se mudou arquitetura ou fluxos
4. **Commit** com mensagem no formato acima
5. **Push** somente se o usuário pedir (padrão: commit local)

### O que não commitar

- `.env`, `*.session`, `data/` (runtime), `.run/`, `.venv/`, logs, `node_modules/`

---

## Regras para agentes de IA

1. **README.md é a única documentação de arquitetura** — nunca recriar `DOCUMENTACAO_COMPLETA.md` ou docs paralelos.
2. **Este arquivo é o backlog técnico** — erros e melhorias vão aqui, não espalhados em comentários ou chats.
3. **Append-only** — só adicionar conteúdo; nunca apagar nem reescrever entradas existentes, exceto se o usuário pedir explicitamente.
4. **Ao resolver um erro** → adicionar bloco **Solução** no mesmo `ERR-*`/`IMP-*` (manter o erro original) + nova entrada em Resolvidos com `Ref:`.
5. **Ao alterar fluxos, API ou estrutura de pastas** → atualizar README.md na mesma sessão.
6. **Ao concluir alterações** → commit no Git com mensagem clara (`fix - ...`, `feat - ...`, etc.) — ver [Versionamento Git](#versionamento-git).
7. **Nunca commitar** `.env`, sessões Telegram, `data/` com credenciais ou PII.

---

*Última atualização: 2026-07-06 (append-only + solução junto do erro)*
