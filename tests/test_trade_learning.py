"""Testes do módulo de aprendizado."""

from __future__ import annotations

from src.models.schemas import (
    StoredTrade,
    TradeDirection,
    TradeSource,
    TradeStatus,
)
from src.config.runtime_config import LearningConfig
from src.services.trade_learning import (
    analyze_closed_trades,
    evaluate_learning_risk,
    features_pattern_family_label,
    is_pattern_blocked,
    pattern_probability_adjustment,
    summarize_rejections,
    trade_pattern_label,
)


def _trade(
    pnl: float,
    *,
    imba: float = 0.8,
    conf: int = 60,
    kalman: str = "bullish",
) -> StoredTrade:
    return StoredTrade(
        id=f"id-{pnl}",
        symbol="BTC/USDT",
        direction=TradeDirection.LONG,
        source=TradeSource.SCANNER,
        status=TradeStatus.CLOSED,
        entry_price=100,
        stop_loss=98,
        confidence=0.68,
        pnl_pct=pnl,
        probability_features={
            "imba_score": imba,
            "confluence_score": conf,
            "kalman_signal": kalman,
            "spread_pct": 0.04,
            "direction": "LONG",
            "source": "scanner",
            "symbol": "BTC/USDT",
        },
    )


class TestTradeLearning:
    def test_pattern_label(self) -> None:
        t = _trade(1.0)
        label = trade_pattern_label(t)
        assert "scanner" in label
        assert "kalman=bullish" in label

    def test_detects_big_wins_and_losses(self) -> None:
        trades = [_trade(2.0), _trade(-1.5), _trade(0.3), _trade(-0.2)]
        report = analyze_closed_trades(trades)
        assert len(report.big_wins) == 1
        assert len(report.big_losses) == 1

    def test_recommendations_with_enough_samples(self) -> None:
        wins = [_trade(1.2, imba=0.9, conf=80) for _ in range(4)]
        losses = [_trade(-1.5, imba=0.7, conf=40, kalman="bearish") for _ in range(4)]
        report = analyze_closed_trades(wins + losses)
        assert report.best_patterns
        assert report.worst_patterns
        assert report.recommendations

    def test_pattern_blocked_when_winrate_low(self) -> None:
        losses = [_trade(-1.2, imba=0.7, conf=40, kalman="bearish") for _ in range(4)]
        features = losses[0].probability_features or {}
        config = LearningConfig(bad_pattern_winrate_pct=40.0, min_pattern_samples=3)
        blocked, reason = is_pattern_blocked(features, losses, config)
        assert blocked
        assert "wr" in reason.lower()

    def test_pattern_probability_penalty(self) -> None:
        losses = [_trade(-1.2, imba=0.7, conf=40, kalman="bearish") for _ in range(4)]
        features = losses[0].probability_features or {}
        config = LearningConfig(bad_pattern_winrate_pct=40.0, min_pattern_samples=3)
        mult, note = pattern_probability_adjustment(features, losses, config)
        assert mult < 1.0
        assert "pattern" in note

    def test_summarize_rejections(self) -> None:
        from types import SimpleNamespace

        items = [
            SimpleNamespace(stage="llm"),
            SimpleNamespace(stage="pwin"),
            SimpleNamespace(stage="llm"),
        ]
        summary = summarize_rejections(items)
        assert "llm=2" in summary
        assert "pwin=1" in summary

    def test_blocks_zero_winrate_exact_pattern(self) -> None:
        losses = [_trade(-1.2, imba=0.7, conf=40, kalman="bearish") for _ in range(2)]
        features = losses[0].probability_features or {}
        config = LearningConfig(zero_winrate_block_samples=2, min_pattern_samples=2)
        blocked, reason = is_pattern_blocked(features, losses, config)
        assert blocked
        assert "0% WR" in reason

    def test_blocks_family_on_severe_loss(self) -> None:
        t1 = _trade(-0.9, imba=0.85, conf=50, kalman="bullish")
        t2 = _trade(-0.3, imba=0.85, conf=55, kalman="bullish")
        t2.probability_features = dict(t2.probability_features or {})
        t2.probability_features["pattern_name"] = "other_chart"
        features = t1.probability_features or {}
        config = LearningConfig(
            block_family_on_big_loss=True,
            big_loss_block_pct=-0.80,
            pattern_family_min_samples=2,
            min_pattern_samples=5,
        )
        verdict = evaluate_learning_risk(features, [t1, t2], config)
        assert verdict.blocked
        assert "loss grave" in verdict.reason.lower()

    def test_legacy_trades_do_not_block_sniper_strategy(self) -> None:
        losses = [_trade(-1.2, imba=0.7, conf=40, kalman="bearish") for _ in range(4)]
        features = dict(losses[0].probability_features or {})
        features["entry_strategy"] = "sniper"
        config = LearningConfig(bad_pattern_winrate_pct=40.0, min_pattern_samples=3)
        blocked, _reason = is_pattern_blocked(features, losses, config)
        assert not blocked

    def test_family_label_ignores_chart(self) -> None:
        feat = {
            "direction": "LONG",
            "source": "scanner",
            "imba_score": 0.8,
            "confluence_score": 60,
            "kalman_signal": "bullish",
            "spread_pct": 0.04,
            "leverage": 20,
            "sl_atr_multiple": 1.0,
            "pattern_name": "hammer",
        }
        family = features_pattern_family_label(feat)
        assert "chart=" not in family
        assert "lev=med" in family
