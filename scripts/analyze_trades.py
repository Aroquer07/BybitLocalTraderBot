"""Relatório de aprendizado a partir do trade journal."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config.settings import get_settings
from src.models.schemas import StoredTrade
from src.services.runtime_config_store import RuntimeConfigStore
from src.services.rejection_log import RejectionLog
from src.services.trade_journal import TradeJournal
from src.services.trade_learning import analyze_closed_trades, format_learning_report, summarize_rejections


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    settings = get_settings()
    runtime = RuntimeConfigStore(settings.settings_path)
    journal = TradeJournal(runtime)
    path = journal._path
    if not path.exists():
        print("Journal vazio.")
        return
    raw = json.loads(path.read_text(encoding="utf-8"))
    trades = [StoredTrade.model_validate(t) for t in raw.get("trades", [])]
    report = analyze_closed_trades(trades)
    rejections = RejectionLog(runtime).list_all()
    rejection_summary = summarize_rejections(rejections)
    print(format_learning_report(report, rejection_summary=rejection_summary))


if __name__ == "__main__":
    main()
