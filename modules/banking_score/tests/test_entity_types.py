"""Tests for Fase 1A: entity_type weight profiles + IRMP outlook overlay."""
from modules.banking_score.events import (
    IRMPOutlookContext,
    overlay_outlook,
    register_subscribers,
)
from modules.banking_score.models.models import BankType
from modules.banking_score.scoring.weights import (
    SUB_COMPONENT_WEIGHTS,
    WEIGHT_PROFILES,
    get_sub_component_weights,
)
from shared.events.event_bus import event_bus


class TestWeightProfiles:
    def test_all_profiles_sum_to_one(self):
        for name, profile in WEIGHT_PROFILES.items():
            assert round(sum(profile.values()), 6) == 1.0, name

    def test_every_enum_type_has_a_profile(self):
        for t in BankType:
            assert t.value in WEIGHT_PROFILES

    def test_unknown_type_falls_back_to_base(self):
        assert get_sub_component_weights("inexistente") == SUB_COMPONENT_WEIGHTS

    def test_none_returns_base(self):
        assert get_sub_component_weights(None) == SUB_COMPONENT_WEIGHTS

    def test_aap_is_more_asset_quality_weighted_than_base(self):
        assert get_sub_component_weights("aap")["calidad"] > SUB_COMPONENT_WEIGHTS["calidad"]

    def test_cambiaria_is_more_liquidity_weighted(self):
        assert get_sub_component_weights("cambiaria")["liquidez"] > SUB_COMPONENT_WEIGHTS["liquidez"]


class TestNewEntityTypes:
    def test_enum_has_full_sib_universe(self):
        values = {t.value for t in BankType}
        assert {"corporacion_credito", "cambiaria", "fiduciaria"} <= values


class TestOutlookOverlay:
    def test_high_risk_biases_estable_to_negative(self):
        ctx = IRMPOutlookContext()
        ctx.on_irmp({"country_code": "DO", "risk_band": "Alto"})
        res = overlay_outlook("estable", "DO", ctx)
        assert res["outlook"] == "negativa"
        assert res["adjusted"] is True

    def test_low_risk_biases_estable_to_positive(self):
        ctx = IRMPOutlookContext()
        ctx.on_irmp({"country_code": "DO", "risk_band": "Bajo"})
        res = overlay_outlook("estable", "DO", ctx)
        assert res["outlook"] == "positiva"

    def test_does_not_override_explicit_outlook(self):
        ctx = IRMPOutlookContext()
        ctx.on_irmp({"country_code": "DO", "risk_band": "Alto"})
        # an explicit negativa/positiva from score delta is preserved
        assert overlay_outlook("positiva", "DO", ctx)["outlook"] == "positiva"

    def test_no_irmp_data_leaves_outlook_unchanged(self):
        ctx = IRMPOutlookContext()
        res = overlay_outlook("estable", "DO", ctx)
        assert res["outlook"] == "estable"
        assert res["adjusted"] is False

    def test_subscriber_updates_context_from_bus(self):
        event_bus.clear()
        ctx = IRMPOutlookContext()
        register_subscribers(event_bus, ctx)
        event_bus.publish("irmp.updated", {"country_code": "DO", "risk_band": "Elevado"})
        assert ctx.band("DO") == "Elevado"
        event_bus.clear()
