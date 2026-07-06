"""Human-readable parsing of strategy pattern labels for the dashboard."""

from __future__ import annotations

from typing import Any


def _parse_kv_part(part: str) -> tuple[str, str] | None:
    if "=" not in part:
        return None
    key, value = part.split("=", 1)
    return key.strip(), value.strip()


def parse_pattern_label(label: str) -> dict[str, Any]:
    """Parse pipe-separated pattern label into display fields."""
    parts = label.split("|")
    result: dict[str, Any] = {
        "raw": label,
        "source": parts[0] if parts else "unknown",
        "direction": parts[1] if len(parts) > 1 else "—",
    }
    for part in parts[2:]:
        kv = _parse_kv_part(part)
        if not kv:
            continue
        key, value = kv
        result[key] = value
    return result


def humanize_strategy_key(name: str) -> dict[str, Any]:
    """Convert ranking bucket key into structured card data."""
    if name.startswith("pattern:"):
        label = name[len("pattern:") :]
        parsed = parse_pattern_label(label)
        return {
            "kind": "pattern",
            "key": name,
            "label": label,
            "parsed": parsed,
            "display_name": f"{parsed.get('direction', '—')} · {parsed.get('source', 'scanner')}",
        }
    if name.startswith("scanner:"):
        strategy = name[len("scanner:") :]
        return {
            "kind": "pipeline",
            "key": name,
            "label": strategy,
            "parsed": {"source": "scanner", "entry_strategy": strategy},
            "display_name": f"Scanner ({strategy})",
        }
    if name.startswith("telegram:"):
        pipeline = name[len("telegram:") :]
        return {
            "kind": "pipeline",
            "key": name,
            "label": pipeline,
            "parsed": {"source": "telegram", "pipeline": pipeline},
            "display_name": f"Telegram ({pipeline})",
        }
    return {
        "kind": "other",
        "key": name,
        "label": name,
        "parsed": {},
        "display_name": name,
    }
