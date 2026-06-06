"""Tests for macro early-warning signals."""
from modules.macro_monitor.scoring.signals import (
    debt_overhang_signal,
    detect_signals,
    sudden_stop_signal,
)


class TestDebtOverhang:
    def test_low_debt(self):
        assert debt_overhang_signal(45.0)["severity"] == "bajo"

    def test_moderate_debt(self):
        assert debt_overhang_signal(62.0)["severity"] == "elevado"

    def test_high_debt(self):
        assert debt_overhang_signal(95.0)["severity"] == "alto"

    def test_none_returns_none(self):
        assert debt_overhang_signal(None) is None


class TestSuddenStop:
    def test_no_signal_when_growing(self):
        assert sudden_stop_signal("remittances", 5.0) is None

    def test_no_signal_on_mild_drop(self):
        assert sudden_stop_signal("remittances", -10.0) is None

    def test_signal_on_sharp_drop(self):
        sig = sudden_stop_signal("remittances", -20.0)
        assert sig["signal"] == "sudden_stop"
        assert sig["severity"] == "elevado"

    def test_high_severity_on_severe_drop(self):
        sig = sudden_stop_signal("remittances", -35.0)
        assert sig["severity"] == "alto"

    def test_none_pct_returns_none(self):
        assert sudden_stop_signal("remittances", None) is None


class TestDetectSignals:
    def test_collects_debt_and_flow_signals(self):
        signals = detect_signals(
            debt_gdp=62.0,
            flow_pct_changes={"remittances": -20.0, "fdi": 3.0},
        )
        kinds = {s["signal"] for s in signals}
        assert "debt_overhang" in kinds
        assert "sudden_stop" in kinds
        assert len(signals) == 2  # fdi growing → no signal

    def test_low_debt_not_surfaced(self):
        signals = detect_signals(debt_gdp=40.0, flow_pct_changes={})
        assert signals == []
