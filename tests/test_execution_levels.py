"""Testes de resolução SMC + IMBA."""

from __future__ import annotations

from unittest.mock import patch

from src.config.runtime_config import BotRuntimeConfig
from src.models.schemas import ImbaAnalysis, TradeDirection
from src.strategies.execution_levels import _weighted_rr_meets_target, resolve_signal_execution_levels
from src.strategies.imba_algo import ImbaSignal
from src.strategies.smc_levels import SMCLevels


class TestExecutionLevels:
    def test_weighted_rr_target(self) -> None:
        smc = SMCLevels(
            entry=100.0,
            stop_loss=98.0,
            take_profits=(104.0, 106.0, 109.0, 112.0),
            tp_labels=("BSL", "FVG", "3R", "4R"),
            sl_reason="test",
            swing_high=110.0,
            swing_low=95.0,
            tp1_rr=2.0,
            weighted_rr=3.5,
        )
        assert _weighted_rr_meets_target(
            smc,
            wins_cover_losses=2,
            tp_close_pcts=(50, 30, 20),
        )

    def test_runtime_has_smc(self) -> None:
        cfg = BotRuntimeConfig()
        assert cfg.smc.enabled
        assert cfg.risk.wins_cover_losses >= 3

    def test_fib_priority_when_both_enabled(self) -> None:
        runtime = BotRuntimeConfig()
        runtime = runtime.model_copy(
            update={
                "imba": runtime.imba.model_copy(update={"use_fib_levels": True}),
                "smc": runtime.smc.model_copy(update={"enabled": True}),
                "strategies": runtime.strategies.model_copy(
                    update={
                        "scanner": runtime.strategies.scanner.model_copy(
                            update={"smc": True}
                        )
                    }
                ),
            }
        )
        signal = ImbaSignal(
            side="SHORT",
            entry_price=0.07573,
            stop_loss=0.08,
            take_profits=(0.07, 0.065, 0.06),
            levels={},
        )
        ohlcv = [[1, 0.079, 0.0792, 0.065, 0.066, 1000.0]] * 80

        with patch(
            "src.strategies.execution_levels.compute_fib_scalp_levels"
        ) as mock_fib:
            mock_fib.return_value = type(
                "Fib",
                (),
                {
                    "stop_loss": 0.077,
                    "take_profits": (0.074, 0.072, 0.071),
                    "swing_low": 0.065,
                    "swing_high": 0.079,
                    "tp1_rr": 1.5,
                },
            )()
            out, smc, reject = resolve_signal_execution_levels(
                signal, "DOGE/USDT", {"5m": ohlcv}, runtime
            )
        assert out is not None
        assert smc is None
        assert reject == ""
        mock_fib.assert_called_once()
