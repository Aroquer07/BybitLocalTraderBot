"""
Aprendizado a partir do journal — identifica padrões que ganham vs perdem.

Bloqueia famílias de setup com losses grandes e calibra P(win) para evitar
repetir erros caros (alta alavancagem, Kalman contra, confluência fraca).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.config.runtime_config import LearningConfig
from src.models.schemas import StoredTrade, TradeStatus
from src.strategies.win_probability import _confluence_bucket, _imba_bucket

BIG_WIN_PCT = 1.0
BIG_LOSS_PCT = -1.0
MIN_PATTERN_SAMPLES = 3


@dataclass(frozen=True)
class TradeOutcome:
    trade_id: str
    symbol: str
    direction: str
    source: str
    pnl_pct: float
    confidence: float
    pattern: str
    notes: str


@dataclass(frozen=True)
class PatternStats:
    pattern: str
    sample_n: int
    wins: int
    winrate_pct: float
    avg_pnl_pct: float
    big_losses: int = 0
    worst_pnl_pct: float = 0.0


@dataclass(frozen=True)
class CalibrationBucket:
    predicted_range: str
    sample_n: int
    actual_winrate_pct: float
    avg_pnl_pct: float


@dataclass(frozen=True)
class LearningReport:
    total_closed: int
    with_features: int
    big_wins: list[TradeOutcome]
    big_losses: list[TradeOutcome]
    best_patterns: list[PatternStats]
    worst_patterns: list[PatternStats]
    calibration: list[CalibrationBucket]
    recommendations: list[str]


@dataclass(frozen=True)
class LearningRiskVerdict:
    blocked: bool
    reason: str = ""
    probability_multiplier: float = 1.0
    adjustment_note: str = ""


def _leverage_bucket(leverage: int | float | None) -> str:
    lev = int(leverage or 15)
    if lev >= 30:
        return "high"
    if lev >= 15:
        return "med"
    return "low"


def trade_pattern_label(trade: StoredTrade) -> str:
    """Agrupa trades por perfil de features na abertura."""
    return features_pattern_label(trade.probability_features or {})


def _closed_for_strategy(
    closed: list[StoredTrade],
    features: dict[str, Any],
) -> list[StoredTrade]:
    """Restringe histórico à mesma entry_strategy quando definida nas features atuais."""
    strategy = features.get("entry_strategy")
    if not strategy:
        return closed
    return [
        t
        for t in closed
        if (t.probability_features or {}).get("entry_strategy") == strategy
    ]


def features_pattern_label(features: dict[str, Any]) -> str:
    """Label de padrão a partir de features (trade aberto ou rejeitado)."""
    direction = features.get("direction", "LONG")
    source = features.get("source", "scanner")
    if hasattr(direction, "value"):
        direction = direction.value
    if hasattr(source, "value"):
        source = source.value
    entry_strategy = features.get("entry_strategy")
    strategy_tag = f"|strategy={entry_strategy}" if entry_strategy else ""
    imba = _imba_bucket(float(features.get("imba_score", 0)))
    conf = _confluence_bucket(int(features.get("confluence_score", 0)))
    kalman = features.get("kalman_signal") or "na"
    spread = float(features.get("spread_pct", 0))
    spread_tag = "tight" if spread <= 0.08 else "wide"
    lev = _leverage_bucket(features.get("leverage"))
    chart = features.get("pattern_name") or "no_chart"
    sl_atr = float(features.get("sl_atr_multiple", 1.0))
    sl_tag = "tight" if sl_atr < 0.7 else "wide" if sl_atr > 2.0 else "ok"
    return (
        f"{source}{strategy_tag}|{direction}|imba={imba}|conf={conf}|kalman={kalman}|"
        f"lev={lev}|sl={sl_tag}|spread={spread_tag}|chart={chart}"
    )


def features_pattern_family_label(features: dict[str, Any]) -> str:
    """Família mais ampla — ignora chart para generalizar aprendizado."""
    exact = features_pattern_label(features)
    if "|chart=" in exact:
        return exact.rsplit("|chart=", 1)[0]
    return exact


def build_pattern_stats_map(
    closed: list[StoredTrade],
    *,
    min_samples: int = MIN_PATTERN_SAMPLES,
    label_fn=trade_pattern_label,
) -> dict[str, PatternStats]:
    groups = _aggregate_patterns(closed, label_fn=label_fn)
    return {
        pattern: _pattern_stats(pattern, group)
        for pattern, group in groups.items()
        if len(group) >= min_samples
    }


def pattern_stats_for_features(
    features: dict[str, Any],
    closed: list[StoredTrade],
    config: LearningConfig,
) -> PatternStats | None:
    if not config.enabled:
        return None
    label = features_pattern_label(features)
    return build_pattern_stats_map(
        closed,
        min_samples=config.min_pattern_samples,
    ).get(label)


def family_stats_for_features(
    features: dict[str, Any],
    closed: list[StoredTrade],
    config: LearningConfig,
) -> PatternStats | None:
    if not config.enabled or not config.use_pattern_family_blocking:
        return None
    label = features_pattern_family_label(features)
    return build_pattern_stats_map(
        closed,
        min_samples=config.pattern_family_min_samples,
        label_fn=lambda t: features_pattern_family_label(t.probability_features or {}),
    ).get(label)


def evaluate_learning_risk(
    features: dict[str, Any],
    closed: list[StoredTrade],
    config: LearningConfig,
) -> LearningRiskVerdict:
    """
    Avalia risco de repetir um setup com base no journal.

    Bloqueia padrões/famílias com WR baixo, loss grave ou PnL médio ruim.
    """
    if not config.enabled:
        return LearningRiskVerdict(blocked=False)

    closed = _closed_for_strategy(closed, features)

    exact = pattern_stats_for_features(features, closed, config)
    family = family_stats_for_features(features, closed, config)

    mult = 1.0
    notes: list[str] = []

    if exact is not None:
        if exact.wins == 0 and exact.sample_n >= config.zero_winrate_block_samples:
            return LearningRiskVerdict(
                blocked=True,
                reason=(
                    f"Padrão 0% WR em {exact.sample_n} trades | "
                    f"worst {exact.worst_pnl_pct:+.2f}% | {exact.pattern}"
                ),
            )
        if exact.winrate_pct < config.bad_pattern_winrate_pct:
            return LearningRiskVerdict(
                blocked=True,
                reason=(
                    f"Padrão bloqueado | WR {exact.winrate_pct:.0f}% "
                    f"em {exact.sample_n} | avg {exact.avg_pnl_pct:+.2f}% | {exact.pattern}"
                ),
            )
        if exact.winrate_pct < config.bad_pattern_winrate_pct + 10:
            mult = min(mult, max(0.5, 1.0 - config.pattern_probability_penalty))
            notes.append(f"pattern↓{exact.winrate_pct:.0f}%")
        elif exact.winrate_pct >= config.good_pattern_winrate_pct:
            mult = min(1.2, mult * (1.0 + config.good_pattern_boost))
            notes.append(f"pattern↑{exact.winrate_pct:.0f}%")

    if family is not None:
        family_label = features_pattern_family_label(features)
        family_trades = _trades_for_label(
            closed,
            family_label,
            label_fn=lambda t: features_pattern_family_label(t.probability_features or {}),
        )
        severe = _severe_loss_count(family_trades, config.big_loss_block_pct)
        if (
            config.block_family_on_big_loss
            and severe > 0
            and len(family_trades) >= config.pattern_family_min_samples
        ):
            return LearningRiskVerdict(
                blocked=True,
                reason=(
                    f"Família com {severe} loss grave(s) (≤{config.big_loss_block_pct:.2f}%) | "
                    f"avg {family.avg_pnl_pct:+.2f}% | worst {family.worst_pnl_pct:+.2f}% | "
                    f"{family.pattern}"
                ),
            )
        if (
            family.avg_pnl_pct <= config.max_avg_loss_pct
            and family.sample_n >= config.pattern_family_min_samples
        ):
            return LearningRiskVerdict(
                blocked=True,
                reason=(
                    f"Família PnL médio {family.avg_pnl_pct:+.2f}% "
                    f"em {family.sample_n} trades | {family.pattern}"
                ),
            )
        if (
            family.winrate_pct < config.bad_pattern_winrate_pct
            and family.sample_n >= config.pattern_family_min_samples
        ):
            return LearningRiskVerdict(
                blocked=True,
                reason=(
                    f"Família bloqueada | WR {family.winrate_pct:.0f}% "
                    f"em {family.sample_n} | {family.pattern}"
                ),
            )
        if severe > 0:
            mult = min(mult, max(0.45, 1.0 - config.severe_loss_penalty))
            notes.append(f"bigloss×{severe}")

    return LearningRiskVerdict(
        blocked=False,
        probability_multiplier=mult,
        adjustment_note="·".join(notes),
    )


def pattern_probability_adjustment(
    features: dict[str, Any],
    closed: list[StoredTrade],
    config: LearningConfig | None,
) -> tuple[float, str]:
    """Multiplicador de P(win) baseado em histórico do padrão."""
    if config is None or not config.enabled:
        return 1.0, ""
    verdict = evaluate_learning_risk(features, closed, config)
    if verdict.blocked:
        return max(0.4, 1.0 - (config.pattern_probability_penalty * 2)), "pattern⛔"
    if verdict.probability_multiplier != 1.0:
        return verdict.probability_multiplier, verdict.adjustment_note
    return 1.0, ""


def is_pattern_blocked(
    features: dict[str, Any],
    closed: list[StoredTrade],
    config: LearningConfig,
) -> tuple[bool, str]:
    """Bloqueia entrada se padrão/família histórica tem risco elevado."""
    verdict = evaluate_learning_risk(features, closed, config)
    return verdict.blocked, verdict.reason


def summarize_rejections(rejections: list[Any], limit: int = 100) -> str:
    """Resumo de rejeições recentes para o relatório."""
    if not rejections:
        return "🚫 Rejeições registradas: 0"
    recent = rejections[-limit:]
    by_stage: dict[str, int] = {}
    for r in recent:
        stage = getattr(r, "stage", "unknown")
        by_stage[stage] = by_stage.get(stage, 0) + 1
    parts = ", ".join(f"{k}={v}" for k, v in sorted(by_stage.items()))
    return f"🚫 Rejeições (últimas {len(recent)}): {parts}"


def _outcome_from_trade(trade: StoredTrade) -> TradeOutcome:
    return TradeOutcome(
        trade_id=trade.id,
        symbol=trade.symbol,
        direction=trade.direction.value,
        source=trade.source.value,
        pnl_pct=round(trade.pnl_pct or 0, 4),
        confidence=round(trade.confidence, 4),
        pattern=trade_pattern_label(trade),
        notes=(trade.notes or "")[:120],
    )


def _trades_for_label(
    closed: list[StoredTrade],
    label: str,
    *,
    label_fn=trade_pattern_label,
) -> list[StoredTrade]:
    return [
        t
        for t in closed
        if t.probability_features and label_fn(t) == label
    ]


def _severe_loss_count(trades: list[StoredTrade], threshold_pct: float) -> int:
    return sum(1 for t in trades if (t.pnl_pct or 0) <= threshold_pct)


def _aggregate_patterns(
    closed: list[StoredTrade],
    *,
    label_fn=trade_pattern_label,
) -> dict[str, list[StoredTrade]]:
    buckets: dict[str, list[StoredTrade]] = {}
    for trade in closed:
        if not trade.probability_features:
            continue
        key = label_fn(trade)
        buckets.setdefault(key, []).append(trade)
    return buckets


def _pattern_stats(pattern: str, trades: list[StoredTrade]) -> PatternStats:
    pnls = [t.pnl_pct or 0 for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    n = len(trades)
    big_losses = sum(1 for p in pnls if p <= BIG_LOSS_PCT)
    return PatternStats(
        pattern=pattern,
        sample_n=n,
        wins=wins,
        winrate_pct=round(wins / n * 100, 1) if n else 0.0,
        avg_pnl_pct=round(sum(pnls) / n, 4) if n else 0.0,
        big_losses=big_losses,
        worst_pnl_pct=round(min(pnls), 4) if pnls else 0.0,
    )


def _calibration_buckets(closed: list[StoredTrade]) -> list[CalibrationBucket]:
    ranges = [
        ("50-60%", 0.50, 0.60),
        ("60-70%", 0.60, 0.70),
        ("70-80%", 0.70, 0.80),
        ("80%+", 0.80, 1.01),
    ]
    out: list[CalibrationBucket] = []
    for label, lo, hi in ranges:
        bucket = [t for t in closed if lo <= t.confidence < hi]
        if not bucket:
            continue
        wins = sum(1 for t in bucket if (t.pnl_pct or 0) > 0)
        n = len(bucket)
        out.append(
            CalibrationBucket(
                predicted_range=label,
                sample_n=n,
                actual_winrate_pct=round(wins / n * 100, 1),
                avg_pnl_pct=round(sum(t.pnl_pct or 0 for t in bucket) / n, 4),
            )
        )
    return out


def _build_recommendations(
    best: list[PatternStats],
    worst: list[PatternStats],
    calibration: list[CalibrationBucket],
) -> list[str]:
    recs: list[str] = []
    for p in worst[:3]:
        extra = ""
        if p.big_losses:
            extra = f", {p.big_losses} loss(es) grave(s), worst {p.worst_pnl_pct:+.2f}%"
        recs.append(
            f"Evitar padrão [{p.pattern}]: WR {p.winrate_pct:.0f}% "
            f"em {p.sample_n} trades (PnL médio {p.avg_pnl_pct:+.2f}%{extra})"
        )
    for p in best[:3]:
        recs.append(
            f"Priorizar [{p.pattern}]: WR {p.winrate_pct:.0f}% "
            f"em {p.sample_n} trades (PnL médio {p.avg_pnl_pct:+.2f}%)"
        )
    for c in calibration:
        if c.sample_n >= MIN_PATTERN_SAMPLES and c.actual_winrate_pct < 45:
            recs.append(
                f"P(win) {c.predicted_range} subestimou risco: "
                f"WR real {c.actual_winrate_pct:.0f}% (n={c.sample_n})"
            )
    if not recs:
        recs.append(
            "Amostra ainda pequena — continue operando para calibrar padrões "
            f"(mínimo {MIN_PATTERN_SAMPLES} trades por padrão)."
        )
    return recs


def analyze_closed_trades(trades: list[StoredTrade]) -> LearningReport:
    """Gera relatório de aprendizado a partir de trades fechados."""
    closed = [t for t in trades if t.status == TradeStatus.CLOSED]
    with_features = [t for t in closed if t.probability_features]

    big_wins = sorted(
        [_outcome_from_trade(t) for t in closed if (t.pnl_pct or 0) >= BIG_WIN_PCT],
        key=lambda o: o.pnl_pct,
        reverse=True,
    )[:10]
    big_losses = sorted(
        [_outcome_from_trade(t) for t in closed if (t.pnl_pct or 0) <= BIG_LOSS_PCT],
        key=lambda o: o.pnl_pct,
    )[:10]

    pattern_groups = _aggregate_patterns(closed)
    all_stats = [
        _pattern_stats(pattern, group)
        for pattern, group in pattern_groups.items()
        if len(group) >= MIN_PATTERN_SAMPLES
    ]
    best = sorted(all_stats, key=lambda p: (p.winrate_pct, p.avg_pnl_pct), reverse=True)
    worst = sorted(all_stats, key=lambda p: (p.winrate_pct, p.avg_pnl_pct))

    calibration = _calibration_buckets(closed)
    recommendations = _build_recommendations(best, worst, calibration)

    return LearningReport(
        total_closed=len(closed),
        with_features=len(with_features),
        big_wins=big_wins,
        big_losses=big_losses,
        best_patterns=best[:5],
        worst_patterns=worst[:5],
        calibration=calibration,
        recommendations=recommendations,
    )


def format_learning_report(
    report: LearningReport,
    *,
    rejection_summary: str = "",
) -> str:
    """Formata relatório para Telegram/log."""
    lines = [
        "📚 APRENDIZADO DO JOURNAL",
        f"Fechados: {report.total_closed} | com features: {report.with_features}",
    ]
    if rejection_summary:
        lines.append(rejection_summary)
    lines.append("")

    if report.big_wins:
        lines.append("✅ Maiores acertos:")
        for t in report.big_wins[:5]:
            lines.append(f"  {t.symbol} {t.direction} {t.pnl_pct:+.2f}% | {t.pattern}")
        lines.append("")

    if report.big_losses:
        lines.append("❌ Maiores erros:")
        for t in report.big_losses[:5]:
            lines.append(f"  {t.symbol} {t.direction} {t.pnl_pct:+.2f}% | {t.pattern}")
        lines.append("")

    if report.best_patterns:
        lines.append("🏆 Melhores padrões:")
        for p in report.best_patterns:
            lines.append(
                f"  {p.pattern} → WR {p.winrate_pct:.0f}% "
                f"(n={p.sample_n}, PnL {p.avg_pnl_pct:+.2f}%)"
            )
        lines.append("")

    if report.worst_patterns:
        lines.append("⚠️ Piores padrões:")
        for p in report.worst_patterns:
            bl = f", {p.big_losses} grave(s)" if p.big_losses else ""
            lines.append(
                f"  {p.pattern} → WR {p.winrate_pct:.0f}% "
                f"(n={p.sample_n}, PnL {p.avg_pnl_pct:+.2f}%{bl})"
            )
        lines.append("")

    if report.calibration:
        lines.append("🎯 Calibração P(win):")
        for c in report.calibration:
            lines.append(
                f"  Previsto {c.predicted_range}: WR real {c.actual_winrate_pct:.0f}% "
                f"(n={c.sample_n}, PnL {c.avg_pnl_pct:+.2f}%)"
            )
        lines.append("")

    lines.append("💡 Recomendações:")
    for r in report.recommendations:
        lines.append(f"  • {r}")

    return "\n".join(lines)


def log_trade_outcome(trade: StoredTrade) -> None:
    """Loga insight rápido quando um trade fecha."""
    from src.utils.logger import get_logger

    logger = get_logger(__name__)
    if trade.status != TradeStatus.CLOSED:
        return
    pnl = trade.pnl_pct or 0
    tag = "BIG WIN" if pnl >= BIG_WIN_PCT else "BIG LOSS" if pnl <= BIG_LOSS_PCT else "closed"
    pattern = trade_pattern_label(trade) if trade.probability_features else "sem_features"
    logger.info(
        "Aprendizado | %s | %s %s | pnl=%.2f%% | conf=%.0f%% | pattern=%s",
        tag,
        trade.direction.value,
        trade.symbol,
        pnl,
        trade.confidence * 100,
        pattern,
    )
