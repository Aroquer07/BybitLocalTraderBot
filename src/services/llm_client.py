"""Cliente Ollama para inferência local — Juiz Estratégico (sem cálculo de indicadores)."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import ollama

from src.config.settings import Settings
from src.services.runtime_config_store import RuntimeConfigStore
from src.models.schemas import (
    MarketState,
    TakeProfitLevel,
    TelegramSignal,
    TradeDecision,
    TradeDirection,
    TradeStyle,
)
from src.utils.formatters import build_formatted_trade_output
from src.utils.logger import get_logger

logger = get_logger(__name__)

_SKILL_PATH = Path(__file__).resolve().parents[2] / "SKILL.md"


def _json_safe(value: Any) -> Any:
    """Converte numpy/pandas/datetime para tipos JSON nativos."""
    from datetime import date, datetime

    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    type_name = type(value).__name__
    if type_name in ("bool_", "bool8"):
        return bool(value)
    if hasattr(value, "item") and callable(value.item):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    return value


def _normalize_confidence(value: Any) -> float:
    """Normaliza confidence da LLM — aceita 0-1 ou percentual 0-100."""
    try:
        conf = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if conf > 1.0:
        conf = conf / 100.0 if conf <= 100.0 else 1.0
    return max(0.0, min(conf, 1.0))


def _repair_json_text(text: str) -> str:
    """Corrige problemas comuns em JSON gerado por LLM."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    text = re.sub(r",\s*([\]}])", r"\1", text)
    return text


def _extract_decision_fields_fallback(text: str) -> dict[str, Any] | None:
    """Extrai campos mínimos quando o JSON veio truncado ou malformado."""
    approved_m = re.search(r'"approved"\s*:\s*(true|false)', text, re.IGNORECASE)
    conf_m = re.search(r'"confidence"\s*:\s*([0-9.]+)', text, re.IGNORECASE)
    if not approved_m and not conf_m:
        return None

    data: dict[str, Any] = {}
    if approved_m:
        data["approved"] = approved_m.group(1).lower() == "true"
    if conf_m:
        data["confidence"] = float(conf_m.group(1))

    for field, pattern in (
        ("direction", r'"direction"\s*:\s*"(LONG|SHORT)"'),
        ("trade_style", r'"trade_style"\s*:\s*"(scalp|daytrade)"'),
        ("symbol", r'"symbol"\s*:\s*"([^"]+)"'),
        ("bias", r'"bias"\s*:\s*"([^"]{1,500})"'),
        ("tp_sl_quality", r'"tp_sl_quality"\s*:\s*"([^"]{1,500})"'),
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            data[field] = match.group(1)

    lev_m = re.search(r'"leverage"\s*:\s*(\d+)', text, re.IGNORECASE)
    if lev_m:
        data["leverage"] = int(lev_m.group(1))

    return data or None


def _loads_decision_dict(raw_content: str) -> dict[str, Any]:
    """Tenta parsear JSON da LLM com reparos e fallback de campos."""
    cleaned = _extract_json(raw_content)
    last_exc: json.JSONDecodeError | ValueError | None = None
    for candidate in (cleaned, _repair_json_text(cleaned)):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as exc:
            last_exc = exc

    fallback = _extract_decision_fields_fallback(raw_content)
    if fallback:
        logger.warning(
            "JSON LLM reparado via fallback | approved=%s confidence=%s",
            fallback.get("approved"),
            fallback.get("confidence"),
        )
        return fallback

    if last_exc is not None:
        raise last_exc
    raise ValueError("JSON inválido")


def _extract_json(text: str) -> str:
    """Extrai JSON de resposta que pode conter ruído."""
    text = _repair_json_text(text)
    if text.startswith("{"):
        return text
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0)
    raise ValueError("Nenhum JSON encontrado na resposta")


def _compact_market_state_for_scanner(ms_dump: dict[str, Any]) -> dict[str, Any]:
    """Reduz payload do scanner — só indicadores relevantes para a LLM."""
    keep_keys = {
        "rsi_12",
        "rsi_zone",
        "macd",
        "macd_signal",
        "macd_histogram",
        "macd_momentum",
        "kalman_signal",
        "kalman_reversal",
        "kalman_zone",
        "kalman_trend_strength",
        "adx",
        "supertrend",
        "ema_14",
        "sma_14",
    }
    compact = dict(ms_dump)
    tfs = compact.get("timeframes") or {}
    slim_tfs: dict[str, Any] = {}
    for tf, snap in tfs.items():
        if not isinstance(snap, dict):
            continue
        ind = snap.get("indicators") or {}
        if isinstance(ind, dict):
            slim_ind = {k: ind[k] for k in keep_keys if k in ind}
        else:
            slim_ind = {}
        slim_tfs[tf] = {
            "indicators": slim_ind,
            "fibonacci": (snap.get("fibonacci") or {}).get("nearest_levels"),
            "ohlcv_summary": {
                k: (snap.get("ohlcv_summary") or {}).get(k)
                for k in ("last_close", "price_change_pct", "volume_ratio")
                if (snap.get("ohlcv_summary") or {}).get(k) is not None
            },
        }
    compact["timeframes"] = slim_tfs
    ob = compact.get("orderbook_snapshot") or {}
    if isinstance(ob, dict):
        compact["orderbook_snapshot"] = {
            k: ob.get(k) for k in ("bid_ask_spread_pct", "imbalance") if k in ob
        }
    return compact


def _compact_imba_for_llm(imba: Any) -> dict[str, Any] | None:
    """Resumo IMBA compacto — evita o modelo ecoar o objeto inteiro na resposta."""
    if imba is None:
        return None
    if hasattr(imba, "model_dump"):
        data = imba.model_dump(mode="json")
    elif isinstance(imba, dict):
        data = imba
    else:
        return None
    per_tf: dict[str, Any] = {}
    for tf, row in (data.get("timeframes") or {}).items():
        if isinstance(row, dict):
            per_tf[tf] = {
                "trend": row.get("trend"),
                "signal_on_last_bar": row.get("signal_on_last_bar"),
                "signal_side": row.get("signal_side"),
            }
    return {
        "symbol": data.get("symbol"),
        "summary": data.get("summary"),
        "aligned_direction": data.get("aligned_direction"),
        "fresh_signal_direction": data.get("fresh_signal_direction"),
        "confidence_score": data.get("confidence_score"),
        "timeframes": per_tf,
    }


def _is_trade_decision_schema(data: dict[str, Any]) -> bool:
    """Detecta se o JSON parece decisão de trade (não eco de imba_analysis)."""
    if "approved" in data:
        return True
    if "confidence" in data and "bias" in data:
        return True
    # Eco típico do qwen3 quando confunde entrada/saída
    if "fresh_signal_direction" in data and "approved" not in data:
        return False
    if "timeframes" in data and "aligned_direction" in data and "approved" not in data:
        return False
    return False


def _load_skill_content() -> str:
    try:
        return _SKILL_PATH.read_text(encoding="utf-8")
    except OSError:
        logger.warning("SKILL.md não encontrado em %s", _SKILL_PATH)
        return ""


_SKILL_CONTENT = _load_skill_content()

_JSON_RESPONSE_SCHEMA = """{
  "approved": boolean,
  "confidence": float (0.0 a 1.0),
  "trade_style": "scalp" | "daytrade",
  "direction": "LONG" | "SHORT" | null,
  "symbol": string | null,
  "entry_zone_min": float | null,
  "entry_zone_max": float | null,
  "entry_price": float | null,
  "stop_loss": float | null,
  "leverage": int,
  "take_profits": [
    {"price": float, "percentage": float, "risk_reward": float}
  ],
  "bias": string,
  "entry_condition": string,
  "tp_sl_quality": string,
  "formatted_output": string
}"""

SYSTEM_PROMPT = f"""Você é o Juiz Estratégico de um agente de trading quantitativo BybitBot.

{_SKILL_CONTENT}

REGRAS INVIOLÁVEIS (resumo):
1. Você NÃO calcula indicadores técnicos. Todos os dados (multi-TF, RSI, MACD, IMBA ALGO, confluência, orderbook) já foram calculados pelo Python no JSON de entrada.
2. O campo `imba_analysis` contém o indicador [IMBA] ALGO em 3m/5m/15m — virada verde/vermelho no canal Fibonacci. USE como base principal para validar direção.
3. Para sinais TELEGRAM: valide se o sinal do Telegram ALINHA com imba_analysis (direção, tendência multi-TF). Rejeite se contraditório.
4. Sua função é analisar CONFLUÊNCIA entre sinal Telegram, IMBA ALGO, scores Python e dados técnicos.
5. Os níveis finais de entry, SL e 3 TPs são SEMPRE recalculados em Python no TF de execução (imba_execution_timeframe, default 5m). Você valida direção/confiança/leverage — NÃO use Fibonacci do 15m para TPs finais.
6. Os TPs usam split de execução 50/30/20 (TP4 pode ser 0% na exchange). Posição fica aberta até SL — NÃO fechar em reversão.
7. Aprove trades Telegram APENAS com confidence >= 0.90. Scanner autônomo: >= min_confidence do JSON (default 65%).
8. Zero DCA — uma única entrada. Você DEVE escolher `leverage` (inteiro) entre min_leverage e max_leverage do JSON: setup forte/confiante = mais alavancagem; setup fraco = menos.
9. Trades APROVADOS exigem: leverage, 3 TPs ordenados, SL coerente com direção, TP1 com R:R >= 0.5. Explique a validação em `tp_sl_quality`.
10. APENAS futures perpetual linear — LONG ou SHORT. NUNCA spot.
11. APENAS daytrade e scalp. REJEITE swing e spot.

VALIDAÇÃO DE COERÊNCIA (obrigatória em ambos os modos):
- `market_state.timeframes` traz RSI, MACD, EMA/SMA, Bollinger, Ichimoku, ATR, ADX, Supertrend, VWAP, `fibonacci`, **`market_patterns`** (padrões clássicos ≥80% WR detectados em Python) e **Kalman** (`kalman_trend_strength`, `kalman_signal`, `kalman_reversal`, `kalman_zone`) por TF.
- `confluence` traz long_score, short_score e checks booleanos — use como checklist.
- **Kalman** é prioritário para detectar **reversões** (cruzamento de zero, saída de OB/OS). Valide se `kalman_reversal` e `kalman_signal` alinham com a direção do trade.
- Para SCANNER: valide se IMBA, Kalman, confluência, **market_patterns** alinhados, RSI, MACD e Fibonacci apontam a MESMA direção. Rejeite divergências.
- Para TELEGRAM: valide alinhamento entre sinal humano e todos os indicadores acima.
- Em `tp_sl_quality` e `bias`, cite quais indicadores confirmam ou contradizem a entrada (inclua Kalman quando relevante).

Papéis dos timeframes no JSON:
- 5m: entrada fina / execução scalp
- 15m: confirmação principal (timeframe primário)
- 30m: filtro de ruído / tendência curta

O campo `confluence` contém long_score, short_score, long_checks, short_checks e recommendation (LONG|SHORT|NEUTRAL) — use como input, mas sua confidence final é soberana.

Você deve retornar um JSON válido (sem markdown, sem texto extra) com esta estrutura EXATA:
{_JSON_RESPONSE_SCHEMA}

Para trades APROVADOS (approved=true E confidence>=0.90), inclua "formatted_output" EXATAMENTE neste layout:

🚨 {{SCALP|DAYTRADE}} TÉCNICO - {{PAR}} 🚨
📊 Direção: {{LONG|SHORT}} {{🟢|🔴}}
📈 Viés: {{texto técnico conciso}}
📌 Probabilidade: {{XX}}%

🔻 Entrada: {{preco_min}} — {{preco_max}}
✅ Condição: {{condição de ativação}}
🛑 Stop: {{preco_stop}}

🎯 TP1: {{preco}} | R:R 1:{{ratio}}
🎯 TP2: {{preco}} | R:R 1:{{ratio}}
🎯 TP3: {{preco}} | R:R 1:{{ratio}}
🎯 TP4: {{preco}} | R:R 1:{{ratio}}

- Use SCALP ou DAYTRADE conforme trade_style
- Probabilidade = confidence * 100 (inteiro)
- R:R em formato brasileiro com vírgula: 1:2,1
- 🟢 para LONG, 🔴 para SHORT

Responda APENAS com o JSON. Nenhum texto antes ou depois."""

_SCANNER_OUTPUT_SCHEMA = """{
  "approved": boolean,
  "confidence": float,
  "trade_style": "scalp" | "daytrade",
  "direction": "LONG" | "SHORT" | null,
  "symbol": string,
  "leverage": int,
  "bias": string,
  "entry_condition": string,
  "tp_sl_quality": string,
  "take_profits": [{"price": float, "percentage": float, "risk_reward": float}]
}"""

SCANNER_SYSTEM_PROMPT = f"""Você é o juiz do modo SCANNER autônomo do BybitBot.

Tarefa: ler o JSON de entrada e decidir se o trade proposto deve ser APROVADO ou REJEITADO.

REGRAS:
1. NÃO recalcule indicadores. NÃO repita nem ecoe `imba_summary`, `market_state` ou `proposed_signal` na resposta.
2. A saída DEVE ser SOMENTE o JSON de decisão no schema abaixo — nunca devolva estrutura de entrada.
3. `proposed_signal.side` é a direção sugerida pelo IMBA. Valide coerência com confluência, RSI, MACD e Kalman em `market_state`.
4. Aprove (`approved=true`) apenas se setup coerente e `confidence` >= `constraints.min_confidence`.
   `confidence` é fração 0.0–1.0 (ex: 0.72 = 72%). NUNCA use 72 para 72%.
5. Se rejeitar, preencha `bias` e `tp_sl_quality` explicando o motivo (obrigatório, máx. 200 chars cada).
6. Escolha `leverage` entre min_leverage e max_leverage. Setup forte = mais alavancagem.
7. Para aprovados: 3 TPs, direction LONG ou SHORT, trade_style scalp ou daytrade.
8. Futures perpetual linear apenas. Sem DCA.

Schema de SAÍDA (único formato aceito):
{_SCANNER_OUTPUT_SCHEMA}

Responda APENAS com esse JSON. Sem markdown. Sem formatted_output. Máximo ~20 linhas.
Sem campos extras como timeframes, confidence_score ou summary."""


class LLMClient:
    """Motor de inferência Ollama com modelo persistente na VRAM."""

    def __init__(self, settings: Settings, runtime_store: RuntimeConfigStore) -> None:
        self._settings = settings
        self._runtime = runtime_store
        self._client = ollama.AsyncClient(host=settings.ollama_host)
        self._warmed_up = False

    @property
    def is_warmed_up(self) -> bool:
        """Indica se o warmup carregou o modelo com sucesso."""
        return self._warmed_up

    async def warmup(self) -> bool:
        """Pré-carrega o modelo na VRAM com keep_alive estendido."""
        try:
            await asyncio.wait_for(
                self._client.chat(
                    model=self._settings.ollama_model,
                    messages=[{"role": "user", "content": "ping /no_think"}],
                    think=False,
                    keep_alive=self._settings.ollama_keep_alive,
                ),
                timeout=60.0,
            )
            self._warmed_up = True
            logger.info(
                "Ollama warmup OK | model=%s | keep_alive=%s",
                self._settings.ollama_model,
                self._settings.ollama_keep_alive,
            )
            return True
        except asyncio.TimeoutError:
            logger.warning("Ollama warmup timeout — inferência pode ser lenta na 1ª chamada")
        except Exception:
            logger.exception("Ollama warmup falhou — continuando sem VRAM preload")
        return False

    async def evaluate_trade(
        self,
        signal: TelegramSignal,
        market_state: MarketState,
    ) -> TradeDecision:
        """
        Envia sinal + dados técnicos para a LLM e retorna decisão validada.

        Timeout ou erro retorna decisão de recusa sem derrubar o pipeline.
        """
        user_payload = self._build_user_payload(signal, market_state)
        try:
            response = await asyncio.wait_for(
                self._client.chat(
                    model=self._settings.ollama_model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": f"{user_payload}\n/no_think"},
                    ],
                    format="json",
                    think=False,
                    keep_alive=self._settings.ollama_keep_alive,
                ),
                timeout=self._settings.ollama_timeout_seconds,
            )
            raw_content = response["message"]["content"]
            return self._parse_response(raw_content)

        except asyncio.TimeoutError:
            logger.error(
                "Ollama timeout | symbol=%s | timeout=%ss",
                market_state.symbol,
                self._settings.ollama_timeout_seconds,
            )
            return self._rejection_decision(
                reason="Timeout na inferência LLM",
                raw="",
            )
        except Exception:
            logger.exception(
                "Erro Ollama | symbol=%s (pipeline continua)",
                market_state.symbol,
            )
            return self._rejection_decision(
                reason="Erro na inferência LLM",
                raw="",
            )

    async def evaluate_scanner_opportunity(
        self,
        market_state: MarketState,
        imba_signal: object,
    ) -> TradeDecision:
        """Valida oportunidade autônoma com indicadores completos + IMBA."""
        runtime = self._runtime.reload()
        user_payload = self._build_scanner_payload(market_state, imba_signal)
        scanner_prompt = (
            "Modo SCANNER autônomo.\n"
            "Valide COERÊNCIA entre proposed_signal, imba_summary, confluência e indicadores.\n"
            f"Aprove apenas se setup coerente e confidence >= {runtime.confidence.scanner:.0%}.\n"
            "Níveis de entry/SL/TP são aplicados em Python — você NÃO redefine preços.\n"
            "IMPORTANTE: responda SOMENTE o JSON de decisão (approved, confidence, bias, ...). "
            "NÃO repita imba_summary nem market_state na resposta.\n"
            "Se rejeitar, explique em bias e tp_sl_quality."
        )
        messages = [
            {"role": "system", "content": SCANNER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"{scanner_prompt}\n\n{user_payload}\n/no_think",
            },
        ]
        try:
            raw_content = await self._chat_json(messages)
            decision = self._parse_response(
                raw_content,
                confidence_threshold=runtime.confidence.scanner,
            )
            if not self._is_schema_parse_failure(decision):
                return self._finalize_scanner_decision(
                    decision,
                    market_state=market_state,
                    imba_signal=imba_signal,
                    min_confidence=runtime.confidence.scanner,
                )

            logger.warning(
                "LLM scanner schema inválido | %s — retry com lembrete",
                market_state.symbol,
            )
            retry_messages = messages + [
                {"role": "assistant", "content": raw_content},
                {
                    "role": "user",
                    "content": (
                        "ERRO: sua resposta NÃO seguiu o schema de decisão. "
                        "Retorne JSON VÁLIDO e COMPACTO (máx. 20 linhas) com: "
                        "approved, confidence (0.0 a 1.0, NÃO use 54 para 54%), direction, leverage, bias, "
                        "tp_sl_quality. Sem formatted_output. Sem repetir entrada.\n/no_think"
                    ),
                },
            ]
            raw_retry = await self._chat_json(retry_messages)
            decision = self._parse_response(
                raw_retry,
                confidence_threshold=runtime.confidence.scanner,
            )
            return self._finalize_scanner_decision(
                decision,
                market_state=market_state,
                imba_signal=imba_signal,
                min_confidence=runtime.confidence.scanner,
            )
        except Exception:
            logger.exception("Erro LLM scanner | %s", market_state.symbol)
            return self._rejection_decision(reason="Erro LLM scanner", raw="")

    def _finalize_scanner_decision(
        self,
        decision: TradeDecision,
        *,
        market_state: MarketState,
        imba_signal: object,
        min_confidence: float,
    ) -> TradeDecision:
        """Preenche níveis de execução via IMBA — LLM só julga direção/confiança."""
        if self._is_schema_parse_failure(decision):
            return decision

        imba_side = getattr(imba_signal, "side", None)
        imba_direction = None
        if imba_side == "LONG":
            imba_direction = TradeDirection.LONG
        elif imba_side == "SHORT":
            imba_direction = TradeDirection.SHORT

        direction = decision.direction or imba_direction
        confidence = decision.confidence
        approved = confidence >= min_confidence and direction is not None

        if not approved:
            return decision.model_copy(
                update={
                    "approved": False,
                    "direction": direction,
                    "confidence_threshold": min_confidence,
                }
            )

        entry = getattr(imba_signal, "entry_price", None)
        stop = getattr(imba_signal, "stop_loss", None)
        imba_tps = list(getattr(imba_signal, "take_profits", []) or [])
        tps = decision.take_profits or self._parse_take_profits(
            imba_tps,
            entry_price=entry,
        )

        return decision.model_copy(
            update={
                "approved": True,
                "direction": direction,
                "symbol": decision.symbol or market_state.symbol,
                "entry_price": decision.entry_price or entry,
                "stop_loss": decision.stop_loss or stop,
                "take_profits": tps,
                "llm_confidence": decision.llm_confidence if decision.llm_confidence is not None else confidence,
                "confidence_threshold": min_confidence,
            }
        )

    async def _chat_json(self, messages: list[dict[str, str]]) -> str:
        response = await asyncio.wait_for(
            self._client.chat(
                model=self._settings.ollama_model,
                messages=messages,
                format="json",
                think=False,
                keep_alive=self._settings.ollama_keep_alive,
            ),
            timeout=self._settings.ollama_timeout_seconds,
        )
        return response["message"]["content"]

    def _build_scanner_payload(
        self,
        market_state: MarketState,
        imba_signal: object,
    ) -> str:
        """JSON de entrada do scanner com indicadores técnicos completos."""
        runtime = self._runtime.reload()
        from src.strategies.imba_analyzer import imba_analysis_timeframes

        imba_tfs = imba_analysis_timeframes(runtime)
        ms_dump = _json_safe(market_state.model_dump())
        ms_dump.pop("imba_analysis", None)
        payload = {
            "mode": "scanner",
            "market_state": _compact_market_state_for_scanner(ms_dump),
            "imba_summary": _compact_imba_for_llm(market_state.imba_analysis),
            "proposed_signal": {
                "side": getattr(imba_signal, "side", None),
                "entry_price": getattr(imba_signal, "entry_price", None),
                "stop_loss": getattr(imba_signal, "stop_loss", None),
                "take_profits": list(getattr(imba_signal, "take_profits", [])),
            },
            "constraints": {
                "min_confidence": runtime.confidence.scanner,
                "min_leverage": runtime.risk.min_leverage,
                "max_leverage": runtime.risk.max_leverage,
                "required_tp_count": 3,
                "risk_per_trade_pct": runtime.risk.risk_per_trade_pct,
                "tp_split": {
                    "tp1_pct": runtime.imba.tp_close_pcts[0],
                    "tp2_pct": runtime.imba.tp_close_pcts[1],
                    "tp3_pct": runtime.imba.tp_close_pcts[2],
                },
                "imba_sensitivity": runtime.imba.sensitivity,
                "imba_execution_timeframe": runtime.timeframes.execution,
                "imba_analysis_timeframes": imba_tfs,
                "analysis_timeframes": runtime.timeframes.analysis,
                "hold_until_sl": True,
                "no_reversal_close": True,
                "no_dca": True,
                "market_type": self._settings.bybit_market_type,
                "futures_only": True,
                "directions": ["LONG", "SHORT"],
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _build_user_payload(
        self,
        signal: TelegramSignal,
        market_state: MarketState,
    ) -> str:
        """Monta JSON de entrada para a LLM (sem DataFrames)."""
        runtime = self._runtime.reload()
        imba_tfs = imba_analysis_timeframes(runtime)
        if not imba_tfs:
            imba_tfs = runtime.timeframes.analysis[:3]
        payload = {
            "telegram_signal": signal.model_dump(mode="json"),
            "market_state": _json_safe(market_state.model_dump()),
            "constraints": {
                "min_confidence": runtime.confidence.telegram,
                "min_leverage": runtime.risk.min_leverage,
                "max_leverage": runtime.risk.max_leverage,
                "required_tp_count": 3,
                "risk_per_trade_pct": runtime.risk.risk_per_trade_pct,
                "tp_split": {
                    "tp1_pct": runtime.imba.tp_close_pcts[0],
                    "tp2_pct": runtime.imba.tp_close_pcts[1],
                    "tp3_pct": runtime.imba.tp_close_pcts[2],
                },
                "imba_sensitivity": runtime.imba.sensitivity,
                "imba_execution_timeframe": runtime.timeframes.execution,
                "imba_analysis_timeframes": imba_tfs or runtime.timeframes.analysis,
                "hold_until_sl": True,
                "no_reversal_close": True,
                "no_dca": True,
                "market_type": self._settings.bybit_market_type,
                "allowed_trade_styles": runtime.telegram.allowed_trade_styles,
                "reject_trade_styles": runtime.telegram.reject_trade_styles,
                "futures_only": True,
                "directions": ["LONG", "SHORT"],
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @staticmethod
    def _parse_take_profits(
        raw: Any,
        *,
        entry_price: float | None = None,
    ) -> list[TakeProfitLevel]:
        """Normaliza take_profits — LLM pode devolver floats ou dicts parciais."""
        if not isinstance(raw, list):
            return []

        entry = float(entry_price) if entry_price is not None else None
        out: list[TakeProfitLevel] = []

        for tp in raw:
            if isinstance(tp, (int, float)):
                price = float(tp)
                pct = (
                    abs((price - entry) / entry * 100)
                    if entry and entry > 0
                    else 0.0
                )
                out.append(
                    TakeProfitLevel(
                        price=price,
                        percentage=round(pct, 4),
                        risk_reward=0.0,
                    )
                )
                continue

            if isinstance(tp, dict):
                price_raw = tp.get("price", tp.get("take_profit"))
                if price_raw is None:
                    logger.warning("take_profits dict sem price — ignorado: %s", tp)
                    continue
                price = float(price_raw)
                pct_raw = tp.get("percentage", tp.get("pct"))
                if pct_raw is not None:
                    pct = float(pct_raw)
                elif entry and entry > 0:
                    pct = abs((price - entry) / entry * 100)
                else:
                    pct = 0.0
                rr_raw = tp.get("risk_reward", tp.get("rr", 0))
                out.append(
                    TakeProfitLevel(
                        price=price,
                        percentage=round(pct, 4),
                        risk_reward=float(rr_raw or 0),
                    )
                )
                continue

            logger.warning(
                "take_profits item ignorado | type=%s",
                type(tp).__name__,
            )

        return out

    def _parse_response(
        self,
        raw_content: str,
        *,
        confidence_threshold: float | None = None,
    ) -> TradeDecision:
        """Parseia e valida resposta JSON da LLM."""
        threshold = confidence_threshold or self._runtime.reload().confidence.telegram
        try:
            data = _loads_decision_dict(raw_content)
        except (json.JSONDecodeError, ValueError) as exc:
            preview = raw_content[:400].replace("\n", " ")
            logger.error("Resposta LLM inválida: %s | preview=%s", exc, preview)
            return self._rejection_decision(
                reason=f"JSON inválido: {exc}",
                raw=raw_content,
            )

        if not _is_trade_decision_schema(data):
            preview = json.dumps(data, ensure_ascii=False)[:240]
            logger.error(
                "Resposta fora do schema de decisão (eco de entrada?) | preview=%s",
                preview,
            )
            return self._rejection_decision(
                reason="Resposta fora do schema — modelo ecoou entrada em vez de decisão",
                raw=raw_content,
            )

        confidence = _normalize_confidence(data.get("confidence", 0.0))
        approved = bool(data.get("approved", False))

        if approved and confidence < threshold:
            approved = False
            logger.info(
                "Kill switch ativado | confidence=%.0f%% < %.0f%%",
                confidence * 100,
                threshold * 100,
            )

        direction_raw = data.get("direction")
        direction = TradeDirection(direction_raw) if direction_raw else None

        if approved and any(
            v is None
            for v in (data.get("symbol"), direction, data.get("entry_price"), data.get("stop_loss"))
        ):
            # Scanner: LLM aprova direção/confiança; Python preenche níveis via IMBA depois
            approved = False

        take_profits = self._parse_take_profits(
            data.get("take_profits", []),
            entry_price=data.get("entry_price"),
        )

        trade_style_raw = data.get("trade_style")
        trade_style = TradeStyle(trade_style_raw) if trade_style_raw else None
        trade_style_label = (
            "SCALP" if trade_style == TradeStyle.SCALP else "DAYTRADE"
        ) if trade_style else None

        bias = data.get("bias", "") or data.get("ai_analysis", "")

        strength_raw = data.get("signal_strength")
        signal_strength = None
        if strength_raw:
            try:
                from src.models.schemas import SignalStrength
                signal_strength = SignalStrength(strength_raw)
            except ValueError:
                pass

        formatted = data.get("formatted_output", "")
        if approved and not formatted and data.get("entry_price") and data.get("stop_loss"):
            formatted = self._build_formatted_fallback(data, take_profits, bias)

        try:
            return TradeDecision(
                approved=approved,
                confidence=confidence,
                llm_confidence=confidence,
                trade_style=trade_style,
                trade_style_label=trade_style_label,
                direction=direction,
                symbol=data.get("symbol"),
                entry_zone_min=data.get("entry_zone_min"),
                entry_zone_max=data.get("entry_zone_max"),
                entry_price=data.get("entry_price"),
                stop_loss=data.get("stop_loss"),
                stop_loss_pct=data.get("stop_loss_pct"),
                leverage=data.get("leverage"),
                take_profits=take_profits,
                bias=bias,
                ai_analysis=bias,
                volume_cvd_note=data.get("volume_cvd_note", ""),
                entry_condition=data.get("entry_condition", ""),
                tp_sl_quality=data.get("tp_sl_quality", ""),
                signal_strength=signal_strength,
                formatted_output=formatted,
                raw_llm_response=raw_content,
                confidence_threshold=threshold,
            )
        except Exception as exc:
            logger.error("TradeDecision validation failed: %s", exc)
            return self._rejection_decision(
                reason=f"Validação falhou: {exc}",
                raw=raw_content,
            )

    def _build_formatted_fallback(
        self,
        data: dict[str, Any],
        take_profits: list[TakeProfitLevel],
        bias: str,
    ) -> str:
        """Monta output formatado caso a LLM não inclua formatted_output."""
        direction = TradeDirection(data["direction"])
        entry_price = data["entry_price"]
        entry_zone_min = data.get("entry_zone_min") or entry_price
        entry_zone_max = data.get("entry_zone_max") or entry_price
        tp_tuples = [(tp.price, tp.percentage, tp.risk_reward) for tp in take_profits]
        trade_style_raw = data.get("trade_style")
        trade_style = TradeStyle(trade_style_raw) if trade_style_raw else None

        return build_formatted_trade_output(
            direction=direction,
            symbol=data.get("symbol", "UNKNOWN"),
            entry_zone_min=entry_zone_min,
            entry_zone_max=entry_zone_max,
            stop_loss=data["stop_loss"],
            take_profits=tp_tuples,
            bias=bias,
            entry_condition=data.get("entry_condition", ""),
            confidence=float(data.get("confidence", 0.0)),
            trade_style=trade_style,
        )

    @staticmethod
    def _is_schema_parse_failure(decision: TradeDecision) -> bool:
        reason = decision.bias or ""
        return reason.startswith(
            ("JSON inválido", "Resposta fora do schema", "Validação falhou")
        )

    @staticmethod
    def _rejection_decision(reason: str, raw: str) -> TradeDecision:
        """Retorna decisão de recusa segura."""
        return TradeDecision(
            approved=False,
            confidence=0.0,
            bias=reason,
            ai_analysis=reason,
            raw_llm_response=raw,
        )
