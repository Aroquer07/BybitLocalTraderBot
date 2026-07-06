"""Séries de indicadores para replay no dashboard (estilo TradingView)."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pandas_ta as ta

from src.config.strategy_config import IndicatorModulesConfig
from src.strategies.indicator_modules.base import ModuleResult
from src.strategies.indicator_modules.breakout_probability import (
    compute_breakout_backtest,
    compute_breakout_levels,
    evaluate_breakout_probability,
)
from src.strategies.indicator_modules.range_detector import _detect_range_state
from src.strategies.indicator_modules.sniper_entry import _vwap
from src.strategies.indicator_modules.trend_speed import _compute_dyn_ema, _wma
from src.services.sniper_chart import (
    build_ema_ribbon_values,
    build_sniper_markers_and_setup,
    build_sniper_panel,
)
from src.strategies.indicators import ohlcv_to_dataframe

# Cores alinhadas aos Pine Scripts originais (TradingView)
TV_COLORS = {
    "trend_speed_bull": "#84cc16",
    "trend_speed_bear": "#ef4444",
    "trend_speed_hist_up": "#82ffc3",
    "trend_speed_hist_dn": "#f78c8c",
    "range_top": "#a78bfa",
    "range_bottom": "#a78bfa",
    "sniper_ema9": "#22d3ee",
    "sniper_ema21": "#f97316",
    "sniper_vwap": "#c084fc",
    "entry": "#facc15",
    "stop_loss": "#f87171",
    "take_profit": "#4ade80",
}

DISPLAY_NAMES = {
    "trend_speed": "Trend Speed Analyzer",
    "range_detector": "Range Detector",
    "sniper": "Sniper Entry/Exit",
    "breakout_probability": "Breakout Probability",
    "imba": "IMBA ALGO",
}


def chart_module_flags(
    config: IndicatorModulesConfig,
    entry_strategy: str | None = None,
) -> dict[str, bool]:
    """Overlays allowed for the active scanner entry strategy."""
    if entry_strategy == "sniper":
        return {
            "trend_speed": False,
            "range_detector": False,
            "sniper": config.sniper,
            "breakout": True,
        }
    if entry_strategy == "imba":
        return {
            "trend_speed": False,
            "range_detector": False,
            "sniper": False,
            "breakout": False,
        }
    return {
        "trend_speed": config.trend_speed,
        "range_detector": config.range_detector,
        "sniper": config.sniper,
        "breakout": config.sniper,
    }


def _strategy_module_names(entry_strategy: str | None) -> set[str]:
    if entry_strategy == "sniper":
        return {"sniper", "breakout_probability"}
    if entry_strategy == "imba":
        return {"imba"}
    return {"trend_speed", "range_detector", "sniper", "breakout_probability"}


def _series_points(timestamps: list[int], values: pd.Series) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    for i, t in enumerate(timestamps):
        if i >= len(values):
            break
        v = values.iloc[i]
        if pd.isna(v):
            continue
        out.append({"t": int(t), "v": round(float(v), 8)})
    return out


def _module_dict(mod: ModuleResult) -> dict[str, Any]:
    return {
        "name": mod.name,
        "display_name": DISPLAY_NAMES.get(mod.name, mod.name),
        "triggered": mod.triggered,
        "direction": mod.direction,
        "confidence": mod.confidence,
        "reason": mod.reason,
        "regime": mod.regime,
        "entry_price": mod.entry_price,
        "stop_loss": mod.stop_loss,
        "take_profits": list(mod.take_profits) if mod.take_profits else [],
    }


def build_indicator_overlays(
    ohlcv: list[list[float]],
    *,
    timestamps: list[int] | None = None,
    config: IndicatorModulesConfig | None = None,
    module_results: list[ModuleResult] | None = None,
    entry_strategy: str | None = None,
) -> dict[str, Any]:
    """Monta overlays + metadados dos módulos para o chart snapshot."""
    if len(ohlcv) < 30:
        return {
            "modules": [],
            "overlays": [],
            "panels": [],
            "breakout": None,
            "markers": [],
            "sniper_panel": None,
            "trade_setup": None,
        }

    df = ohlcv_to_dataframe(ohlcv)
    ts = timestamps or [int(c[0]) for c in ohlcv]
    overlays: list[dict[str, Any]] = []
    panels: list[dict[str, Any]] = []
    cfg = config or IndicatorModulesConfig()
    flags = chart_module_flags(cfg, entry_strategy)

    close = df["close"]
    high = df["high"]
    low = df["low"]
    open_ = df["open"]

    # --- Trend Speed Analyzer ---
    if flags["trend_speed"]:
        dyn_ema = _compute_dyn_ema(close, 50, 5.0)
        wma2 = _wma(close, 2)
        bullish = wma2 > dyn_ema

        trend_line: list[dict[str, float]] = []
        for i, t in enumerate(ts):
            if i >= len(dyn_ema) or pd.isna(dyn_ema.iloc[i]):
                continue
            trend_line.append(
                {
                    "t": int(t),
                    "v": round(float(dyn_ema.iloc[i]), 8),
                    "bull": bool(bullish.iloc[i]) if i < len(bullish) and not pd.isna(bullish.iloc[i]) else True,
                }
            )
        if trend_line:
            overlays.append(
                {
                    "id": "trend_speed_line",
                    "type": "trend_line",
                    "label": "Dynamic Trend",
                    "values": trend_line,
                    "color_bull": TV_COLORS["trend_speed_bull"],
                    "color_bear": TV_COLORS["trend_speed_bear"],
                }
            )

        c_rma = ta.rma(close, length=10)
        o_rma = ta.rma(open_, length=10)
        if c_rma is not None and o_rma is not None:
            speed = (c_rma - o_rma).cumsum()
            trendspeed = ta.hma(speed, length=5)
            if trendspeed is not None:
                hist_vals = []
                for i, t in enumerate(ts):
                    if i >= len(trendspeed) or pd.isna(trendspeed.iloc[i]):
                        continue
                    v = float(trendspeed.iloc[i])
                    hist_vals.append(
                        {
                            "t": int(t),
                            "v": round(v, 8),
                            "color": TV_COLORS["trend_speed_hist_up"] if v >= 0 else TV_COLORS["trend_speed_hist_dn"],
                        }
                    )
                if hist_vals:
                    panels.append(
                        {
                            "id": "trend_speed_hist",
                            "type": "histogram",
                            "label": "Trend Speed",
                            "values": hist_vals,
                        }
                    )

    # --- Range Detector ---
    if flags["range_detector"]:
        state = _detect_range_state(df, length=20, mult=1.0, atr_len=500)
        if state and state.active:
            from_t = ts[min(state.bar_start, len(ts) - 1)]
            to_t = ts[min(state.bar_end, len(ts) - 1)]
            overlays.append(
                {
                    "id": "range_box",
                    "type": "box",
                    "label": "Range Zone",
                    "top": round(state.top, 8),
                    "bottom": round(state.bottom, 8),
                    "mid": round(state.mid, 8),
                    "from_t": int(from_t),
                    "to_t": int(to_t),
                    "color": TV_COLORS["range_top"],
                    "opacity": 0.12,
                }
            )

    # --- Sniper (EMA ribbon + VWAP + painel + markers + trade setup) ---
    markers: list[dict[str, Any]] = []
    sniper_panel: dict[str, Any] | None = None
    trade_setup: dict[str, Any] | None = None

    if flags["sniper"] and len(ohlcv) >= 50:
        ema9 = ta.ema(close, length=9)
        ema21 = ta.ema(close, length=21)
        vwap_s = _vwap(df)

        ribbon_vals = build_ema_ribbon_values(df, ts)
        if ribbon_vals:
            overlays.append(
                {
                    "id": "sniper_ribbon",
                    "type": "ema_ribbon",
                    "label": "EMA Ribbon",
                    "values": ribbon_vals,
                    "color_bull": "#22c55e",
                    "color_bear": "#ef4444",
                }
            )

        if ema9 is not None:
            overlays.append(
                {
                    "id": "sniper_ema9",
                    "type": "line",
                    "label": "EMA 9",
                    "color": TV_COLORS["sniper_ema9"],
                    "values": _series_points(ts, ema9),
                }
            )
        if ema21 is not None:
            overlays.append(
                {
                    "id": "sniper_ema21",
                    "type": "line",
                    "label": "EMA 21",
                    "color": TV_COLORS["sniper_ema21"],
                    "values": _series_points(ts, ema21),
                }
            )

        # VWAP segmentado verde/vermelho (close vs vwap)
        vwap_line: list[dict[str, Any]] = []
        for i, t in enumerate(ts):
            if i >= len(vwap_s) or pd.isna(vwap_s.iloc[i]):
                continue
            bull = float(close.iloc[i]) > float(vwap_s.iloc[i])
            vwap_line.append(
                {
                    "t": int(t),
                    "v": round(float(vwap_s.iloc[i]), 8),
                    "bull": bull,
                }
            )
        if vwap_line:
            overlays.append(
                {
                    "id": "sniper_vwap",
                    "type": "trend_line",
                    "label": "VWAP",
                    "values": vwap_line,
                    "color_bull": "#22c55e",
                    "color_bear": "#ef4444",
                }
            )

        sniper_panel = build_sniper_panel(df)
        markers, trade_setup = build_sniper_markers_and_setup(df, ts)
        if sniper_panel and trade_setup:
            signal_t = trade_setup.get("signal_t")
            last_t = ts[-1] if ts else None
            sniper_panel["status"] = "NEW" if signal_t == last_t else "WAIT"
            sniper_panel["rows"] = [
                *sniper_panel.get("rows", []),
                {
                    "label": "Status",
                    "value": sniper_panel["status"],
                    "tone": "neutral" if sniper_panel["status"] == "WAIT" else "bull",
                },
            ]
        if ts:
            markers.append(
                {
                    "t": int(ts[-1]),
                    "shape": "decision",
                    "text": "DECISÃO",
                }
            )

    # --- Breakout Probability (levels + panel metadata) ---
    breakout = None
    if flags["breakout"]:
        outlook = evaluate_breakout_probability(ohlcv)
        backtest = compute_breakout_backtest(ohlcv)
        breakout = {
            "bias": outlook.bias,
            "probability_pct": round(outlook.probability_pct, 1),
            "prob_high_pct": round(outlook.prob_high_pct, 1),
            "prob_low_pct": round(outlook.prob_low_pct, 1),
            "prev_candle": outlook.prev_candle,
            "reason": outlook.reason,
            "backtest": backtest,
        }
        if len(df) >= 2:
            level_rows = compute_breakout_levels(ohlcv, nbr=5, perc=1.0)
            if not level_rows:
                prev_high = round(float(high.iloc[-2]), 8)
                prev_low = round(float(low.iloc[-2]), 8)
                level_rows = [
                    {
                        "step_index": 0,
                        "price": prev_high,
                        "prob_pct": breakout["prob_high_pct"],
                        "side": "high",
                        "color": "#22c55e",
                    },
                    {
                        "step_index": 0,
                        "price": prev_low,
                        "prob_pct": breakout["prob_low_pct"],
                        "side": "low",
                        "color": "#ef4444",
                    },
                ]
            overlays.append(
                {
                    "id": "breakout_levels",
                    "type": "breakout_levels",
                    "label": "Breakout Probability",
                    "levels": level_rows,
                    "bias": outlook.bias,
                }
            )

    allowed = _strategy_module_names(entry_strategy)
    modules = [_module_dict(m) for m in (module_results or []) if m.name in allowed]

    return {
        "modules": modules,
        "overlays": overlays,
        "panels": panels,
        "breakout": breakout,
        "markers": markers,
        "sniper_panel": sniper_panel,
        "trade_setup": trade_setup,
    }
