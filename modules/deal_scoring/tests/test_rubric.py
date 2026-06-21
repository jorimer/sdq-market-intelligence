"""Tests de la rúbrica pura de Deal Scoring."""
from modules.deal_scoring.scoring.rubric import compute_deal_score


def test_full_analyst_signals_high_confidence():
    feats = {
        "deal_stage": "term_sheet", "days_since_first_contact": 20,
        "promoter_track_record": 80, "financial_quality": 70,
        "market_validation": 75, "regulatory_readiness": 60,
    }
    r = compute_deal_score(feats, {"country_irmp": None, "sector_iai": None, "country_irc": None})
    assert 0 <= r["score"] <= 100
    assert r["confidence"] == "alta"
    assert r["is_trained_model"] is False
    # los 4 analista + stage + momentum presentes; climate ausente
    assert r["components_present"] == 6


def test_market_anchored_to_iai_when_analyst_missing():
    feats = {"deal_stage": "due_diligence", "promoter_track_record": 50,
             "financial_quality": 50, "market_validation": None, "regulatory_readiness": 50}
    r = compute_deal_score(feats, {"country_irmp": None, "sector_iai": 88.0, "country_irc": None})
    market = next(f for f in r["key_factors"] if f["factor"] == "market")
    assert market["value"] == 88.0
    assert "IAI" in market["source"]


def test_regulatory_anchored_to_irmp_when_analyst_missing():
    feats = {"deal_stage": "legal", "promoter_track_record": 60, "financial_quality": 60,
             "market_validation": 60, "regulatory_readiness": None}
    r = compute_deal_score(feats, {"country_irmp": 42.0, "sector_iai": None, "country_irc": None})
    reg = next(f for f in r["key_factors"] if f["factor"] == "regulatory")
    assert reg["value"] == 42.0
    assert "IRMP" in reg["source"]


def test_weights_redistribute_when_components_missing():
    # solo promoter + stage presentes → score = promedio ponderado de esos dos
    feats = {"deal_stage": "initial", "promoter_track_record": 100}
    r = compute_deal_score(feats, {"country_irmp": None, "sector_iai": None, "country_irc": None})
    # promoter=100 (w0.18) + stage=25 (w0.20) → (0.18*100+0.20*25)/(0.38)
    expected = (0.18 * 100 + 0.20 * 25) / 0.38
    assert abs(r["score"] - round(expected, 1)) < 0.2
    assert r["confidence"] == "baja"  # solo 1 señal de analista


def test_clamps_out_of_range_analyst_inputs():
    """Inputs fuera de 0-100 se acotan → el score nunca sale del rango 0-100."""
    hi = compute_deal_score({"promoter_track_record": 150, "deal_stage": "legal"}, {})
    lo = compute_deal_score({"promoter_track_record": -50, "deal_stage": "initial"}, {})
    assert 0.0 <= hi["score"] <= 100.0
    assert 0.0 <= lo["score"] <= 100.0
    promoter = next(f for f in hi["key_factors"] if f["factor"] == "promoter")
    assert promoter["value"] == 100.0  # 150 → clamp 100


def test_stage_and_momentum_monotonic():
    base = {"promoter_track_record": 50, "financial_quality": 50,
            "market_validation": 50, "regulatory_readiness": 50}
    early = compute_deal_score({**base, "deal_stage": "initial"}, {})["score"]
    late = compute_deal_score({**base, "deal_stage": "legal"}, {})["score"]
    assert late > early  # etapa más avanzada sube el score
