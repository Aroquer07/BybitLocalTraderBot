"""Read-only and write helpers for dashboard endpoints."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.api.services.strategy_pattern import humanize_strategy_key
from src.config.runtime_config import BotRuntimeConfig
from src.config.settings import get_settings
from src.models.schemas import StoredTrade, TradeStatus
from src.services.pnl_reporter import realized_pnl_usd
from src.services.runtime_config_store import RuntimeConfigStore, load_runtime_config
from src.services.trade_learning import (
    analyze_closed_trades,
    trade_pattern_label,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_PID_FILE = _PROJECT_ROOT / ".run" / "bot.pid"
_LOG_FILE = _PROJECT_ROOT / ".run" / "bot.log"
_LOG_HEARTBEAT_DEFAULT_SECONDS = 600


def project_root() -> Path:
    return _PROJECT_ROOT


def _runtime_store() -> RuntimeConfigStore:
    return RuntimeConfigStore(get_settings().settings_path)


def _read_display_from_settings_file() -> dict[str, Any] | None:
    path = Path(get_settings().settings_path)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    display = raw.get("display")
    return display if isinstance(display, dict) else None


def _utc_offset_hours(runtime: BotRuntimeConfig | None = None) -> float:
    if runtime is not None:
        display = getattr(runtime, "display", None)
        if display is not None:
            return float(display.utc_offset_hours)
    file_display = _read_display_from_settings_file()
    if file_display and "utc_offset_hours" in file_display:
        try:
            return float(file_display["utc_offset_hours"])
        except (TypeError, ValueError):
            pass
    return -3.0


def _ensure_display_in_payload(payload: dict[str, Any]) -> dict[str, Any]:
    display = payload.get("display")
    if isinstance(display, dict) and display.get("utc_offset_hours") is not None:
        return payload
    file_display = _read_display_from_settings_file()
    merged_display = file_display if file_display else {"utc_offset_hours": -3.0}
    return {**payload, "display": merged_display}


def _load_trades_raw() -> dict[str, Any]:
    store = _runtime_store()
    path = Path(store.reload().trade_journal_path)
    if not path.is_file():
        return {"trades": [], "stats": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"trades": [], "stats": {}}


def _parse_trades() -> list[StoredTrade]:
    raw = _load_trades_raw().get("trades", [])
    trades: list[StoredTrade] = []
    for item in raw:
        try:
            trades.append(StoredTrade.model_validate(item))
        except ValueError:
            continue
    return trades


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid_file() -> int | None:
    if not _PID_FILE.is_file():
        return None
    try:
        raw = _PID_FILE.read_text(encoding="utf-8").strip()
        pid = int(raw)
        return pid if pid > 0 else None
    except (ValueError, OSError):
        return None


def _log_heartbeat_recent(max_age_seconds: float) -> bool:
    if not _LOG_FILE.is_file():
        return False
    try:
        age = time.time() - _LOG_FILE.stat().st_mtime
        return age <= max_age_seconds
    except OSError:
        return False


def _discover_bot_pid() -> int | None:
    """Find a live main.py process for this project (fallback when bot.pid is stale)."""
    root = str(_PROJECT_ROOT).lower()
    if sys.platform == "win32":
        script = (
            "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | "
            "Where-Object { $_.CommandLine -match 'main\\.py' } | "
            "ForEach-Object { $_.ProcessId }"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line.isdigit():
                continue
            pid = int(line)
            if _pid_alive(pid):
                return pid
        return None

    try:
        result = subprocess.run(
            ["ps", "-ax", "-o", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in result.stdout.splitlines():
        if "main.py" not in line:
            continue
        if root not in line.lower():
            continue
        parts = line.strip().split(None, 1)
        if not parts or not parts[0].isdigit():
            continue
        pid = int(parts[0])
        if _pid_alive(pid):
            return pid
    return None


def _resolve_bot_running(
    *,
    heartbeat_seconds: float,
) -> tuple[bool, int | None, str]:
    pid = _read_pid_file()
    if pid is not None and _pid_alive(pid):
        return True, pid, "pid_file"

    discovered = _discover_bot_pid()
    if discovered is not None:
        return True, discovered, "process_scan"

    if _log_heartbeat_recent(heartbeat_seconds):
        return True, pid, "log_heartbeat"

    return False, pid, "stopped"


def get_bot_status() -> dict[str, Any]:
    settings = get_settings()
    runtime = _runtime_store().reload()
    journal = _load_trades_raw().get("stats", {})
    heartbeat_seconds = max(
        _LOG_HEARTBEAT_DEFAULT_SECONDS,
        float(runtime.scanner.interval_seconds) * 2.5,
    )
    running, pid, status_source = _resolve_bot_running(
        heartbeat_seconds=heartbeat_seconds,
    )

    log_lines = tail_log(80)
    activity = log_lines[-1] if log_lines else "No activity logged yet"

    ngrok_url: str | None = None
    ngrok_file = _PROJECT_ROOT / ".run" / "ngrok_url.txt"
    if ngrok_file.is_file():
        try:
            url = ngrok_file.read_text(encoding="utf-8").strip()
            if url:
                ngrok_url = url
        except OSError:
            pass

    from src.api.services.admin_auth import get_admin_info

    admin_info = get_admin_info()

    return {
        "running": running,
        "pid": pid,
        "status_source": status_source,
        "ngrok_url": ngrok_url,
        "admin_email": admin_info.get("email"),
        "admin_configured": admin_info.get("configured", False),
        "bybit_mode": settings.bybit_mode,
        "settings_path": settings.settings_path,
        "scanner_enabled": runtime.scanner.enabled,
        "scanner_interval_seconds": runtime.scanner.interval_seconds,
        "entry_strategy": runtime.strategies.scanner.entry_strategy,
        "scanner_mode": runtime.strategies.scanner.mode,
        "learning_enabled": runtime.learning.enabled,
        "open_positions": journal.get("open_trades", 0),
        "journal_stats": journal,
        "activity": activity,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def tail_log(limit: int = 100) -> list[str]:
    if not _LOG_FILE.is_file():
        return []
    try:
        lines = _LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-limit:]
    except OSError:
        return []


def get_settings_payload() -> dict[str, Any]:
    try:
        store = _runtime_store()
        runtime = store.reload()
        return _ensure_display_in_payload(runtime.model_dump(mode="json"))
    except Exception as exc:
        path = get_settings().settings_path
        if Path(path).is_file():
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            return raw
        raise RuntimeError(f"settings inválido: {exc}") from exc


def save_settings_payload(data: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    path = Path(settings.settings_path)
    validated = BotRuntimeConfig.model_validate(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(validated.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    store = _runtime_store()
    store.reload()
    return validated.model_dump(mode="json")


def get_trades_payload() -> dict[str, Any]:
    raw = _load_trades_raw()
    trades = raw.get("trades", [])
    enriched: list[dict[str, Any]] = []
    for item in trades:
        try:
            trade = StoredTrade.model_validate(item)
            row = dict(item)
            row["pnl_usd"] = round(realized_pnl_usd(trade), 2)
            enriched.append(row)
        except ValueError:
            enriched.append(item)
    return {
        "trades": enriched,
        "stats": raw.get("stats", {}),
        "updated_at": raw.get("updated_at"),
    }


def get_strategy_ranking() -> list[dict[str, Any]]:
    runtime = _runtime_store().reload()
    entry_strategy = runtime.strategies.scanner.entry_strategy
    closed = [t for t in _parse_trades() if t.status == TradeStatus.CLOSED]

    buckets: dict[str, list[StoredTrade]] = defaultdict(list)
    for trade in closed:
        if trade.source.value == "scanner":
            key = f"scanner:{entry_strategy}"
        else:
            key = f"telegram:pipeline"
        buckets[key].append(trade)

        pattern = (
            trade_pattern_label(trade)
            if trade.probability_features
            else trade.notes[:48] or "unknown"
        )
        buckets[f"pattern:{pattern}"].append(trade)

    ranking: list[dict[str, Any]] = []
    for name, group in buckets.items():
        wins = sum(1 for t in group if (t.pnl_pct or 0) > 0)
        total = len(group)
        total_pnl = sum(t.pnl_pct or 0 for t in group)
        total_pnl_usd = sum(realized_pnl_usd(t) for t in group)
        humanized = humanize_strategy_key(name)
        ranking.append(
            {
                "strategy": name,
                "kind": humanized["kind"],
                "display_name": humanized["display_name"],
                "parsed": humanized.get("parsed", {}),
                "trades": total,
                "wins": wins,
                "losses": total - wins,
                "win_rate_pct": round(wins / total * 100, 2) if total else 0.0,
                "total_pnl_pct": round(total_pnl, 4),
                "total_pnl_usd": round(total_pnl_usd, 2),
                "avg_pnl_pct": round(total_pnl / total, 4) if total else 0.0,
            }
        )

    pattern_rows = [r for r in ranking if r["kind"] == "pattern"]
    other_rows = [r for r in ranking if r["kind"] != "pattern"]
    pattern_rows.sort(key=lambda r: (r["win_rate_pct"], r["total_pnl_pct"]), reverse=True)
    other_rows.sort(key=lambda r: (r["win_rate_pct"], r["total_pnl_pct"]), reverse=True)
    return pattern_rows + other_rows


def get_learning_payload() -> dict[str, Any]:
    runtime = _runtime_store().reload()
    trades = _parse_trades()
    report = analyze_closed_trades(trades)
    rejections_path = Path(runtime.learning.rejections_path)
    rejections: list[dict[str, Any]] = []
    rejection_total = 0
    if rejections_path.is_file():
        try:
            raw = json.loads(rejections_path.read_text(encoding="utf-8"))
            rejections = raw.get("rejections", [])[-50:]
            rejection_total = raw.get("total", len(rejections))
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "report": {
            "total_closed": report.total_closed,
            "with_features": report.with_features,
            "big_wins": [asdict(x) for x in report.big_wins],
            "big_losses": [asdict(x) for x in report.big_losses],
            "best_patterns": [asdict(x) for x in report.best_patterns],
            "worst_patterns": [asdict(x) for x in report.worst_patterns],
            "calibration": [asdict(x) for x in report.calibration],
            "recommendations": report.recommendations,
        },
        "learning_config": runtime.learning.model_dump(mode="json"),
        "strategies": runtime.strategies.model_dump(mode="json"),
        "rejections_recent": rejections,
        "rejections_total": rejection_total,
    }


def get_analysis_payload() -> dict[str, Any]:
    runtime = _runtime_store().reload()
    rejections_path = Path(runtime.learning.rejections_path)
    approvals_path = Path(runtime.learning.approvals_path)
    rejections: list[dict[str, Any]] = []
    approvals: list[dict[str, Any]] = []
    if rejections_path.is_file():
        try:
            raw = json.loads(rejections_path.read_text(encoding="utf-8"))
            rejections = raw.get("rejections", [])[-100:]
        except (json.JSONDecodeError, OSError):
            pass
    if approvals_path.is_file():
        try:
            raw = json.loads(approvals_path.read_text(encoding="utf-8"))
            approvals = raw.get("approvals", [])[-100:]
        except (json.JSONDecodeError, OSError):
            pass

    from src.services.chart_snapshot import sanitize_chart_snapshot

    def _sanitize_decision(item: dict[str, Any]) -> dict[str, Any]:
        snap = item.get("chart_snapshot")
        if not snap:
            return item
        # Replay usa estratégia do momento do registro (meta ou campo strategy)
        meta = snap.get("meta") or {}
        entry_strategy = meta.get("entry_strategy") or item.get("strategy")
        if not entry_strategy and not meta:
            return item
        cleaned = sanitize_chart_snapshot(snap, entry_strategy=entry_strategy)
        return {**item, "chart_snapshot": cleaned}

    rejections = [_sanitize_decision(r) for r in rejections]
    approvals = [_sanitize_decision(a) for a in approvals]

    topic_signals_path = _PROJECT_ROOT / "data" / "topic_signals.json"
    signals: list[dict[str, Any]] = []
    if topic_signals_path.is_file():
        try:
            raw = json.loads(topic_signals_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                signals = raw[-30:]
            elif isinstance(raw, dict):
                signals = raw.get("signals", [])[-30:]
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "rejections": rejections,
        "approvals": approvals,
        "recent_signals": signals,
        "log_tail": tail_log(50),
        "utc_offset_hours": _utc_offset_hours(runtime),
    }


def get_chart_payload() -> dict[str, Any]:
    closed = sorted(
        [t for t in _parse_trades() if t.status == TradeStatus.CLOSED and t.closed_at],
        key=lambda t: t.closed_at or datetime.min.replace(tzinfo=timezone.utc),
    )
    cumulative_usd = 0.0
    equity_curve: list[dict[str, Any]] = []
    pnl_by_source: dict[str, float] = defaultdict(float)
    pnl_by_symbol: dict[str, float] = defaultdict(float)

    pnl_by_source_usd: dict[str, float] = defaultdict(float)
    pnl_by_symbol_usd: dict[str, float] = defaultdict(float)

    for trade in closed:
        pnl_pct = trade.pnl_pct or 0.0
        pnl_usd = realized_pnl_usd(trade)
        cumulative_usd += pnl_usd
        equity_curve.append(
            {
                "time": (trade.closed_at or datetime.now(timezone.utc)).isoformat(),
                "symbol": trade.symbol,
                "pnl_usd": round(pnl_usd, 2),
                "cumulative_pnl_usd": round(cumulative_usd, 2),
            }
        )
        pnl_by_source[trade.source.value] += pnl_pct
        pnl_by_symbol[trade.symbol] += pnl_pct
        pnl_by_source_usd[trade.source.value] += pnl_usd
        pnl_by_symbol_usd[trade.symbol] += pnl_usd

    top_symbols = sorted(pnl_by_symbol_usd.items(), key=lambda x: x[1], reverse=True)[:10]
    return {
        "equity_curve": equity_curve,
        "pnl_by_source": [
            {
                "source": k,
                "pnl_pct": round(pnl_by_source[k], 4),
                "pnl_usd": round(v, 2),
            }
            for k, v in pnl_by_source_usd.items()
        ],
        "top_symbols": [
            {
                "symbol": sym,
                "pnl_pct": round(pnl_by_symbol[sym], 4),
                "pnl_usd": round(pnl, 2),
            }
            for sym, pnl in top_symbols
        ],
    }


def snapshot_version() -> str:
    """Cheap fingerprint for SSE change detection."""
    parts: list[str] = []
    settings = get_settings()
    for path in (
        Path(settings.settings_path),
        Path(_runtime_store().reload().trade_journal_path),
        Path(_runtime_store().reload().learning.rejections_path),
        _LOG_FILE,
        _PID_FILE,
    ):
        if path.is_file():
            parts.append(f"{path}:{path.stat().st_mtime_ns}")
        else:
            parts.append(f"{path}:missing")
    return "|".join(parts)


def _watchlist_path() -> Path:
    runtime = _runtime_store().reload()
    path = Path(runtime.scanner.watchlist_path)
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    return path


def get_watchlist() -> dict[str, Any]:
    path = _watchlist_path()
    symbols: list[str] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            symbols.append(line.upper())
    return {"symbols": symbols, "path": str(path)}


def save_watchlist(symbols: list[str]) -> dict[str, Any]:
    path = _watchlist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        sym = raw.strip().upper()
        if not sym or sym.startswith("#") or sym in seen:
            continue
        seen.add(sym)
        cleaned.append(sym)
    lines = [
        "# Watchlist do scanner — uma moeda por linha (editar sem reiniciar o bot)",
        "# Formatos aceitos: HMSTR | HMSTRUSDT | HMSTR/USDT",
        "",
        *cleaned,
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return get_watchlist()


def _env_path() -> Path:
    return _PROJECT_ROOT / ".env"


def update_account_mode(mode: str) -> dict[str, Any]:
    allowed = {"testnet", "demo", "live"}
    normalized = mode.strip().lower()
    if normalized not in allowed:
        raise ValueError(f"Invalid mode: {mode}. Use testnet, demo or live.")

    env_path = _env_path()
    lines: list[str] = []
    found = False
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("BYBIT_MODE="):
                lines.append(f"BYBIT_MODE={normalized}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"BYBIT_MODE={normalized}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    get_settings.cache_clear()
    settings = get_settings()
    return {
        "mode": settings.bybit_mode,
        "requires_restart": True,
        "message": "Account mode updated. Restart bot and API for changes to take effect.",
    }


async def get_breakout_outlook(limit: int = 25) -> dict[str, Any]:
    """Breakout Probability por símbolo da watchlist (próximo candle)."""
    runtime = _runtime_store().reload()
    raw_symbols = get_watchlist().get("symbols", [])
    from src.services.watchlist_loader import normalize_watchlist_symbols

    symbols = normalize_watchlist_symbols(raw_symbols)[: max(1, min(limit, 50))]
    exec_tf = runtime.timeframes.execution
    min_prob = float(runtime.strategies.scanner.indicators.min_breakout_probability_pct)

    outlooks: list[dict[str, Any]] = []
    error: str | None = None

    if not symbols:
        return {
            "timeframe": exec_tf,
            "min_probability_pct": min_prob,
            "outlooks": [],
            "error": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    try:
        from src.config.settings import get_settings as gs
        from src.services.exchange_client import ExchangeClient
        from src.services.runtime_config_store import RuntimeConfigStore
        from src.strategies.indicator_modules.breakout_probability import (
            evaluate_breakout_probability,
        )

        client = ExchangeClient(gs(), RuntimeConfigStore(gs().settings_path))
        await client.connect()
        try:
            for symbol in symbols:
                try:
                    ohlcv = await client.fetch_ohlcv(
                        symbol, timeframe=exec_tf, limit=runtime.ohlcv_limit
                    )
                    outlook = evaluate_breakout_probability(
                        ohlcv,
                        min_probability_pct=min_prob,
                    )
                    outlooks.append(
                        {
                            "symbol": symbol,
                            "bias": outlook.bias,
                            "probability_pct": round(outlook.probability_pct, 1),
                            "prob_high_pct": round(outlook.prob_high_pct, 1),
                            "prob_low_pct": round(outlook.prob_low_pct, 1),
                            "prev_candle": outlook.prev_candle,
                            "reason": outlook.reason,
                            "meets_threshold": outlook.probability_pct >= min_prob,
                        }
                    )
                except Exception as exc:
                    outlooks.append(
                        {
                            "symbol": symbol,
                            "error": str(exc)[:120],
                        }
                    )
        finally:
            await client.disconnect()
    except Exception as exc:
        error = str(exc)[:200]

    return {
        "timeframe": exec_tf,
        "min_probability_pct": min_prob,
        "outlooks": outlooks,
        "error": error,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


async def get_exchange_pnl_payload(period: str = "week") -> dict[str, Any]:
    """PnL realizado da Bybit com fills e posições agrupadas."""
    from src.config.settings import get_settings
    from src.services.exchange_client import ExchangeClient
    from src.services.pnl_reporter import PERIOD_DAYS, period_range_ms
    from src.services.runtime_config_store import RuntimeConfigStore

    settings = get_settings()
    pnl_period = period if period in PERIOD_DAYS else "week"
    start_ms, end_ms = period_range_ms(pnl_period)  # type: ignore[arg-type]

    result: dict[str, Any] = {
        "period": pnl_period,
        "available": False,
        "fills": {},
        "position_groups": {},
        "error": None,
    }
    try:
        client = ExchangeClient(settings, RuntimeConfigStore(settings.settings_path))
        await client.connect()
        stats = await client.fetch_closed_pnl_stats(start_ms, end_ms)
        await client.disconnect()
        result["available"] = True
        result["fills"] = {
            k: v for k, v in stats.items() if k not in ("position_groups", "position_group_rows")
        }
        result["position_groups"] = stats.get("position_groups") or {}
        result["group_rows"] = (stats.get("position_group_rows") or [])[-20:]
    except Exception as exc:
        result["error"] = str(exc)[:200]
    return result


async def get_account_info() -> dict[str, Any]:
    settings = get_settings()
    result: dict[str, Any] = {
        "mode": settings.bybit_mode,
        "market_type": settings.bybit_market_type,
        "available": False,
        "balance_usdt": None,
        "total_usdt": None,
        "used_usdt": None,
        "error": None,
    }
    try:
        from src.config.settings import get_settings as gs
        from src.services.exchange_client import ExchangeClient
        from src.services.runtime_config_store import RuntimeConfigStore

        client = ExchangeClient(gs(), RuntimeConfigStore(gs().settings_path))
        await client.connect()
        balance = await client.fetch_balance()
        usdt = balance.get("USDT", {})
        result["available"] = True
        result["balance_usdt"] = round(float(usdt.get("free") or 0), 2)
        result["total_usdt"] = round(float(usdt.get("total") or 0), 2)
        result["used_usdt"] = round(float(usdt.get("used") or 0), 2)
        await client.disconnect()
    except Exception as exc:
        result["error"] = str(exc)[:200]
    return result
