"""Analisa gaps de parsing nas amostras exportadas."""
import json
import re
from pathlib import Path

import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config.settings import Settings
from src.services.telegram_client import TelegramClient

data = json.loads((ROOT / "data/telegram_samples.json").read_text(encoding="utf-8"))
c = TelegramClient(Settings(telegram_api_id=1, telegram_api_hash="x", telegram_channel_id=1))

signal_kw = re.compile(
    r"(long|short|entrada|stop|tp\d|take\s*profit|day\s*trade|scalp|usdt|swing)",
    re.I,
)
trade_msgs = [m for m in data["messages"] if signal_kw.search(m.get("text") or "")]

print(f"Total: {len(data['messages'])} | trade-like: {len(trade_msgs)}")

issues = []
ok = 0
for m in trade_msgs:
    t = m["text"]
    sym = c._extract_symbol(t)
    direction = c._extract_direction(t)
    entry = c._extract_entry(t)
    sl = c._extract_stop_loss(t)
    tps = c._extract_take_profits(t)
    if direction and sym:
        if entry and sl and tps:
            ok += 1
        else:
            issues.append(
                {
                    "id": m["id"],
                    "topic": m["topic_title"],
                    "sym": sym,
                    "entry": entry,
                    "sl": sl,
                    "tps": tps,
                    "preview": " ".join(t.split())[:150],
                }
            )

print(f"OK: {ok} | gaps: {len(issues)}")
for i in issues:
    print("---")
    print(i)
