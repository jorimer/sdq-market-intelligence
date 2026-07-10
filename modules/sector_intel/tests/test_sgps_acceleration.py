"""Tests for SGPS and the event-driven acceleration factor."""
import pytest

from shared.events.event_bus import event_bus
from modules.sector_intel.events import (
    AccelerationContext,
    register_subscribers,
)
from modules.sector_intel.scoring.acceleration import compute_acceleration
from modules.sector_intel.scoring.sgps import compute_sgps


class TestSGPS:
    def test_weighted_blend(self):
        # 0.40*80 + 0.35*60 + 0.25*50 = 32 + 21 + 12.5 = 65.5
        res = compute_sgps(historical=80, structural=60, acceleration=50)
        assert res["sgps_score"] == 65.5

    def test_missing_inputs_imputed_neutral_and_flagged(self):
        res = compute_sgps(historical=None, structural=None, acceleration=50)
        assert res["sgps_score"] == 50.0
        assert res["factors"]["historical"]["imputed"] is True
        assert res["factors"]["structural"]["imputed"] is True

    def test_inputs_clamped(self):
        res = compute_sgps(historical=150, structural=-20, acceleration=50)
        assert res["factors"]["historical"]["value"] == 100.0
        assert res["factors"]["structural"]["value"] == 0.0

    def test_provenance_defaults_declared_rubric(self):
        # H1: histórico/estructural son rúbrica declarada por defecto; aceleración es real.
        res = compute_sgps(historical=60, structural=64, acceleration=62.4)
        assert res["factors"]["historical"]["source"] == "rubric"
        assert res["factors"]["structural"]["source"] == "rubric"
        assert res["factors"]["acceleration"]["source"] == "live"

    def test_provenance_flips_to_live_when_sourced(self):
        # Cuando una fuente real llegue (P1: BCRD histórico / ENAE estructural), el
        # ensamblador pasa "live" y el badge lo refleja.
        res = compute_sgps(historical=60, structural=64, acceleration=62.4,
                           sources={"historical": "live", "structural": "rubric"})
        assert res["factors"]["historical"]["source"] == "live"
        assert res["factors"]["structural"]["source"] == "rubric"


class TestAcceleration:
    def test_neutral_when_no_context(self):
        ctx = AccelerationContext()
        res = compute_acceleration(ctx)
        assert res["acceleration"] == 50.0
        assert res["components"] == {}

    def test_good_environment_lifts_acceleration(self):
        ctx = AccelerationContext()
        ctx.on_irmp({"country_code": "DO", "irmp_score": 75.0})   # +10
        ctx.on_trade({"resilience_score": 75.0})                   # +10
        res = compute_acceleration(ctx)
        assert res["acceleration"] == 70.0

    def test_macro_signals_penalize(self):
        ctx = AccelerationContext()
        ctx.on_macro({"signal_count": 2})                          # -10
        res = compute_acceleration(ctx)
        assert res["acceleration"] == 40.0

    def test_clamped_to_range(self):
        ctx = AccelerationContext()
        ctx.on_macro({"signal_count": 100})  # huge penalty
        res = compute_acceleration(ctx)
        assert res["acceleration"] == 0.0


class TestEventWiring:
    def test_context_updates_from_bus(self):
        event_bus.clear()
        ctx = AccelerationContext()
        register_subscribers(event_bus, ctx)

        event_bus.publish("irmp.updated", {"country_code": "DO", "irmp_score": 80.0})
        event_bus.publish("trade.updated", {"resilience_score": 60.0})
        event_bus.publish("macro.updated", {"signal_count": 1})

        assert ctx.irmp["DO"]["irmp_score"] == 80.0
        assert ctx.trade["resilience_score"] == 60.0
        assert ctx.macro["signal_count"] == 1
        event_bus.clear()
