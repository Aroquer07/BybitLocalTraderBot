"""Tests for dashboard chart snapshot building and strategy filtering."""

from __future__ import annotations

from src.config.strategy_config import IndicatorModulesConfig
from src.services.chart_snapshot import (
    DEFAULT_CANDLE_LIMIT,
    build_chart_snapshot,
    sanitize_chart_snapshot,
)
from src.services.indicator_overlays import build_indicator_overlays
from src.strategies.indicator_modules.base import ModuleResult


def _sample_ohlcv(n: int = 150) -> list[list[float]]:
    candles: list[list[float]] = []
    price = 100.0
    for i in range(n):
        o = price
        h = price + 0.5
        l = price - 0.5
        c = price + (0.1 if i % 2 == 0 else -0.1)
        candles.append([1_700_000_000_000 + i * 300_000, o, h, l, c, 1000.0])
        price = c
    return candles


def _sniper_config() -> IndicatorModulesConfig:
    return IndicatorModulesConfig(
        trend_speed=False,
        range_detector=False,
        sniper=True,
    )


class TestChartSnapshot:
    def test_default_candle_limit_is_120(self) -> None:
        assert DEFAULT_CANDLE_LIMIT == 120

    def test_build_snapshot_trims_to_120_candles(self) -> None:
        ohlcv = _sample_ohlcv(200)
        snap = build_chart_snapshot(
            {"5m": ohlcv},
            config=_sniper_config(),
            entry_strategy="sniper",
        )
        assert snap is not None
        assert len(snap["candles"]) == 120

    def test_sniper_strategy_excludes_kalman_and_trend_speed(self) -> None:
        ohlcv = _sample_ohlcv(150)
        data = build_indicator_overlays(
            ohlcv,
            config=_sniper_config(),
            entry_strategy="sniper",
        )
        overlay_ids = {o["id"] for o in data["overlays"]}
        assert "kalman_filtered" not in overlay_ids
        assert "trend_speed_line" not in overlay_ids
        assert "sniper_ema9" in overlay_ids
        assert "sniper_ema21" in overlay_ids
        assert "breakout_levels" in overlay_ids
        assert data["breakout"] is not None

    def test_combined_respects_disabled_modules(self) -> None:
        ohlcv = _sample_ohlcv(150)
        cfg = IndicatorModulesConfig(
            trend_speed=False,
            range_detector=False,
            sniper=True,
        )
        data = build_indicator_overlays(ohlcv, config=cfg, entry_strategy="combined")
        overlay_ids = {o["id"] for o in data["overlays"]}
        assert "trend_speed_line" not in overlay_ids
        assert "range_box" not in overlay_ids
        assert "sniper_ema9" in overlay_ids

    def test_build_snapshot_stores_meta_at_record_time(self) -> None:
        ohlcv = _sample_ohlcv(150)
        snap = build_chart_snapshot(
            {"5m": ohlcv},
            config=_sniper_config(),
            entry_strategy="sniper",
        )
        assert snap is not None
        assert snap["meta"]["entry_strategy"] == "sniper"
        assert "sniper" in snap["meta"]["active_indicators"]
        assert "breakout_probability" in snap["meta"]["active_indicators"]
        assert snap["meta"]["indicators_config"]["trend_speed"] is False

    def test_sanitize_uses_meta_from_snapshot_not_parameter(self) -> None:
        ohlcv = _sample_ohlcv(150)
        combined_cfg = IndicatorModulesConfig(
            trend_speed=True,
            range_detector=False,
            sniper=False,
        )
        stored = build_chart_snapshot(
            {"5m": ohlcv},
            config=combined_cfg,
            entry_strategy="combined",
        )
        assert stored is not None
        # Mesmo passando sniper, meta gravada (combined) prevalece
        cleaned = sanitize_chart_snapshot(stored, entry_strategy="sniper")
        assert cleaned is not None
        overlay_ids = {o["id"] for o in cleaned["overlays"]}
        assert "trend_speed_line" in overlay_ids
        assert "sniper_ema9" not in overlay_ids

    def test_legacy_snapshot_without_meta_left_unchanged(self) -> None:
        legacy = {
            "timeframe": "5m",
            "candles": [{"t": 1, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 1}],
            "overlays": [{"id": "kalman_filtered", "type": "line", "values": []}],
        }
        assert sanitize_chart_snapshot(legacy) == legacy

    def test_sanitize_rebuilds_overlays_from_stored_candles(self) -> None:
        ohlcv = _sample_ohlcv(150)
        stored = {
            "timeframe": "5m",
            "meta": {
                "entry_strategy": "sniper",
                "active_indicators": ["sniper", "breakout_probability"],
                "indicators_config": _sniper_config().model_dump(),
            },
            "candles": [
                {
                    "t": int(c[0]),
                    "o": c[1],
                    "h": c[2],
                    "l": c[3],
                    "c": c[4],
                    "v": c[5],
                }
                for c in ohlcv[-60:]
            ],
            "overlays": [{"id": "kalman_filtered", "type": "line", "values": []}],
            "kalman_meta": {"kalman_signal": "bearish"},
            "modules": [
                {"name": "sniper", "triggered": True, "confidence": 0.8},
                {"name": "trend_speed", "triggered": False, "confidence": 0.0},
            ],
        }
        cleaned = sanitize_chart_snapshot(stored)
        assert cleaned is not None
        assert len(cleaned["candles"]) == 60
        overlay_ids = {o["id"] for o in cleaned["overlays"]}
        assert "kalman_filtered" not in overlay_ids
        assert "sniper_ema9" in overlay_ids
        assert "breakout_levels" in overlay_ids
        assert "kalman_meta" not in cleaned
        assert all(m["name"] != "trend_speed" for m in cleaned["modules"])

    def test_modules_filtered_by_strategy(self) -> None:
        ohlcv = _sample_ohlcv(150)
        modules = [
            ModuleResult("sniper", "LONG", 0.9, True, "ok"),
            ModuleResult("breakout_probability", "LONG", 0.7, True, "ok"),
            ModuleResult("trend_speed", "LONG", 0.5, False, "off"),
        ]
        data = build_indicator_overlays(
            ohlcv,
            config=_sniper_config(),
            module_results=modules,
            entry_strategy="sniper",
        )
        names = {m["name"] for m in data["modules"]}
        assert names == {"sniper", "breakout_probability"}
