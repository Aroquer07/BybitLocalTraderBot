"""Testes do parser de resposta LLM."""

from __future__ import annotations

import json

from src.services.llm_client import (
    LLMClient,
    _is_trade_decision_schema,
    _loads_decision_dict,
    _normalize_confidence,
    _repair_json_text,
)


class TestJsonRepair:
    def test_repair_trailing_comma(self) -> None:
        raw = '{"approved": false, "confidence": 0.5,}'
        data = _loads_decision_dict(raw)
        assert data["approved"] is False
        assert data["confidence"] == 0.5

    def test_fallback_extracts_fields_from_broken_json(self) -> None:
        raw = (
            '{"approved": true, "confidence": 72, "direction": "LONG", '
            '"bias": "setup ok", "tp_sl_quality": "bom", "leverage": 20, '
            '"broken": '
        )
        data = _loads_decision_dict(raw)
        assert data["approved"] is True
        assert data["confidence"] == 72
        assert data["direction"] == "LONG"

    def test_repair_strips_code_fence(self) -> None:
        raw = '```json\n{"approved": false, "confidence": 0.4}\n```'
        assert _repair_json_text(raw).startswith('{"approved"')


class TestNormalizeConfidence:
    def test_fraction(self) -> None:
        assert _normalize_confidence(0.54) == 0.54

    def test_percentage(self) -> None:
        assert _normalize_confidence(54.0) == 0.54

    def test_caps_at_one(self) -> None:
        assert _normalize_confidence(150.0) == 1.0


class TestParseResponseConfidence:
    def test_parses_percentage_confidence(self) -> None:
        client = LLMClient.__new__(LLMClient)
        raw = json.dumps(
            {
                "approved": False,
                "confidence": 54.0,
                "direction": "LONG",
                "bias": "teste",
            }
        )
        decision = client._parse_response(raw, confidence_threshold=0.65)
        assert decision.confidence == 0.54
        assert decision.llm_confidence == 0.54


class TestTradeDecisionSchema:
    def test_valid_decision_json(self) -> None:
        assert _is_trade_decision_schema(
            {"approved": False, "confidence": 0.5, "bias": "conflito"}
        )

    def test_rejects_imba_echo(self) -> None:
        assert not _is_trade_decision_schema(
            {
                "symbol": "HEI/USDT",
                "aligned_direction": "SHORT",
                "fresh_signal_direction": None,
                "confidence_score": 0.75,
                "timeframes": {},
            }
        )


class TestParseTakeProfits:
    def test_accepts_float_list(self) -> None:
        tps = LLMClient._parse_take_profits([101.0, 102.0], entry_price=100.0)
        assert len(tps) == 2
        assert tps[0].price == 101.0
        assert tps[0].percentage == 1.0

    def test_accepts_dict_list(self) -> None:
        tps = LLMClient._parse_take_profits(
            [{"price": 101.0, "percentage": 1.0, "risk_reward": 1.5}],
            entry_price=100.0,
        )
        assert len(tps) == 1
        assert tps[0].risk_reward == 1.5

    def test_ignores_invalid_items(self) -> None:
        tps = LLMClient._parse_take_profits(["bad", 99.0], entry_price=100.0)
        assert len(tps) == 1
        assert tps[0].price == 99.0


class TestSchemaParseFailure:
    def test_detects_schema_rejection(self) -> None:
        decision = LLMClient._rejection_decision(
            reason="Resposta fora do schema — modelo ecoou entrada",
            raw="{}",
        )
        assert LLMClient._is_schema_parse_failure(decision)

    def test_legitimate_rejection_not_schema_failure(self) -> None:
        decision = LLMClient._rejection_decision(
            reason="Conflito entre IMBA e RSI",
            raw="{}",
        )
        assert not LLMClient._is_schema_parse_failure(decision)
