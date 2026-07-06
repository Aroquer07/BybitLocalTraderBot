"""Compact OHLCV snapshot for rejection/approval analysis (dashboard chart replay)."""



from __future__ import annotations



from typing import Any



from src.config.strategy_config import IndicatorModulesConfig

from src.services.chart_indicator_config import resolve_chart_render_for_entry

from src.services.indicator_overlays import _strategy_module_names, build_indicator_overlays

from src.strategies.indicator_modules.base import ModuleResult



DEFAULT_TIMEFRAME = "5m"

DEFAULT_CANDLE_LIMIT = 120





def _build_snapshot_meta(

    entry_strategy: str | None,

    config: IndicatorModulesConfig | None,

) -> dict[str, Any]:

    """Metadados congelados no momento do registro — replay não usa estratégia atual."""

    strategy = entry_strategy or "combined"

    cfg = config or IndicatorModulesConfig()

    render = resolve_chart_render_for_entry(strategy, cfg)

    return {

        "entry_strategy": strategy,

        "active_indicators": list(render.active_names),

        "indicators_config": cfg.model_dump(),

    }





def _resolve_snapshot_context(

    snapshot: dict[str, Any] | None,

    *,

    entry_strategy: str | None = None,

    config: IndicatorModulesConfig | None = None,

) -> tuple[str, IndicatorModulesConfig]:

    """Prioriza meta gravada no snapshot; fallback só para registros legados."""

    meta = (snapshot or {}).get("meta") or {}

    strategy = meta.get("entry_strategy") or entry_strategy or "combined"

    raw_cfg = meta.get("indicators_config")

    if raw_cfg:

        cfg = IndicatorModulesConfig.model_validate(raw_cfg)

    elif config is not None:

        cfg = config

    else:

        cfg = IndicatorModulesConfig()

    return strategy, cfg





def build_chart_snapshot(

    ohlcv_by_tf: dict[str, list[list[float]]] | None,

    *,

    timeframe: str = DEFAULT_TIMEFRAME,

    limit: int = DEFAULT_CANDLE_LIMIT,

    levels: dict[str, Any] | None = None,

    config: IndicatorModulesConfig | None = None,

    module_results: list[ModuleResult] | None = None,

    entry_strategy: str | None = None,

) -> dict[str, Any] | None:

    """Build a lightweight candle snapshot from in-memory OHLCV data."""

    if not ohlcv_by_tf:

        return None



    candles = ohlcv_by_tf.get(timeframe)

    if not candles:

        for tf in (timeframe, "5m", "15m"):

            candles = ohlcv_by_tf.get(tf)

            if candles:

                timeframe = tf

                break

    if not candles:

        first_tf = next(iter(ohlcv_by_tf), None)

        if not first_tf:

            return None

        timeframe = first_tf

        candles = ohlcv_by_tf[first_tf]



    trimmed = candles[-limit:] if len(candles) > limit else candles

    if not trimmed:

        return None



    strategy, cfg = _resolve_snapshot_context(

        None,

        entry_strategy=entry_strategy,

        config=config,

    )



    snapshot: dict[str, Any] = {
        "timeframe": timeframe,
        "candles": [
            {
                "t": int(c[0]),
                "o": round(float(c[1]), 8),
                "h": round(float(c[2]), 8),
                "l": round(float(c[3]), 8),
                "c": round(float(c[4]), 8),
                "v": round(float(c[5]), 4) if len(c) > 5 else 0.0,
            }
            for c in trimmed
        ],
        "meta": _build_snapshot_meta(strategy, cfg),
    }
    if trimmed:
        snapshot["meta"]["snapshot_at"] = int(trimmed[-1][0])

    if levels:

        snapshot["levels"] = {

            k: round(float(v), 8) if isinstance(v, (int, float)) else v

            for k, v in levels.items()

            if v is not None

        }



    indicator_data = build_indicator_overlays(

        trimmed,

        timestamps=[int(c[0]) for c in trimmed],

        config=cfg,

        module_results=module_results,

        entry_strategy=strategy,

    )

    snapshot["modules"] = indicator_data.get("modules", [])

    snapshot["overlays"] = indicator_data.get("overlays", [])

    snapshot["panels"] = indicator_data.get("panels", [])

    if indicator_data.get("breakout"):

        snapshot["breakout"] = indicator_data["breakout"]

    if indicator_data.get("markers"):

        snapshot["markers"] = indicator_data["markers"]

    if indicator_data.get("sniper_panel"):

        snapshot["sniper_panel"] = indicator_data["sniper_panel"]

    if indicator_data.get("trade_setup"):

        snapshot["trade_setup"] = indicator_data["trade_setup"]



    return snapshot





def _candles_to_ohlcv(candles: list[dict[str, Any]]) -> list[list[float]]:

    return [

        [

            float(c["t"]),

            float(c["o"]),

            float(c["h"]),

            float(c["l"]),

            float(c["c"]),

            float(c.get("v") or 0.0),

        ]

        for c in candles

    ]





def sanitize_chart_snapshot(

    snapshot: dict[str, Any] | None,

    *,

    entry_strategy: str | None = None,

    config: IndicatorModulesConfig | None = None,

    module_results: list[ModuleResult] | None = None,

    limit: int = DEFAULT_CANDLE_LIMIT,

) -> dict[str, Any] | None:

    """Recompute overlays usando a estratégia gravada no snapshot (não a atual)."""

    if not snapshot or not snapshot.get("candles"):

        return snapshot



    # Registros antigos sem meta: mantém snapshot original (evita misturar estratégias)

    if not snapshot.get("meta") and entry_strategy is None:

        return snapshot



    strategy, cfg = _resolve_snapshot_context(

        snapshot,

        entry_strategy=entry_strategy,

        config=config,

    )



    candles = snapshot["candles"][-limit:]

    ohlcv = _candles_to_ohlcv(candles)

    if len(ohlcv) < 30:

        return {**snapshot, "candles": candles}



    indicator_data = build_indicator_overlays(

        ohlcv,

        timestamps=[int(c[0]) for c in ohlcv],

        config=cfg,

        module_results=module_results,

        entry_strategy=strategy,

    )



    stored_modules = snapshot.get("modules") or []

    allowed = _strategy_module_names(strategy)

    if module_results:

        modules = indicator_data.get("modules", [])

    elif stored_modules:

        modules = [m for m in stored_modules if m.get("name") in allowed]

    else:

        modules = indicator_data.get("modules", [])



    meta = snapshot.get("meta") or _build_snapshot_meta(strategy, cfg)
    if candles:
        meta = {**meta, "snapshot_at": int(candles[-1]["t"])}



    cleaned: dict[str, Any] = {

        "timeframe": snapshot.get("timeframe", DEFAULT_TIMEFRAME),

        "candles": candles,

        "meta": meta,

        "modules": modules,

        "overlays": indicator_data.get("overlays", []),

        "panels": indicator_data.get("panels", []),

    }

    if snapshot.get("levels"):

        cleaned["levels"] = snapshot["levels"]

    if indicator_data.get("breakout"):

        cleaned["breakout"] = indicator_data["breakout"]

    if indicator_data.get("markers"):

        cleaned["markers"] = indicator_data["markers"]

    if indicator_data.get("sniper_panel"):

        cleaned["sniper_panel"] = indicator_data["sniper_panel"]

    if indicator_data.get("trade_setup"):

        cleaned["trade_setup"] = indicator_data["trade_setup"]

    return cleaned


