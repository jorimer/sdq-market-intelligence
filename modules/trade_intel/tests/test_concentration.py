"""Tests for trade concentration / resilience scoring."""
from modules.trade_intel.scoring.concentration import (
    compute_trade_scores,
    herfindahl,
)


class TestHerfindahl:
    def test_single_product_is_max_concentration(self):
        assert herfindahl([100.0]) == 1.0

    def test_even_split_lowers_hhi(self):
        # 4 equal products → HHI = 4 * 0.25^2 = 0.25
        assert herfindahl([10, 10, 10, 10]) == 0.25

    def test_no_volume_returns_none(self):
        assert herfindahl([0, 0]) is None
        assert herfindahl([]) is None


class TestComputeTradeScores:
    FLOWS = [
        {"product": "A", "direction": "export", "value": 50.0},
        {"product": "B", "direction": "export", "value": 50.0},
        {"product": "oil", "direction": "import", "value": 100.0},
    ]

    def test_diversification_inverse_of_hhi(self):
        res = compute_trade_scores(self.FLOWS)
        # exports 50/50 → HHI 0.5 → diversification 50
        assert res["hhi_exports"] == 0.5
        assert res["export_diversification"] == 50.0

    def test_import_dependency(self):
        res = compute_trade_scores(self.FLOWS)
        # imports 100 / (exports 100 + imports 100) = 0.5
        assert res["import_dependency"] == 0.5

    def test_resilience_blend(self):
        res = compute_trade_scores(self.FLOWS)
        # 0.6*50 + 0.4*(1-0.5)*100 = 30 + 20 = 50
        assert res["resilience_score"] == 50.0

    def test_top_products_sorted_with_shares(self):
        flows = [
            {"product": "big", "direction": "export", "value": 80.0},
            {"product": "small", "direction": "export", "value": 20.0},
        ]
        res = compute_trade_scores(flows)
        assert res["top_export_products"][0]["product"] == "big"
        assert res["top_export_products"][0]["share"] == 0.8
        assert res["hhi_exports"] == round(0.8**2 + 0.2**2, 4)

    def test_concentrated_economy_is_less_resilient(self):
        concentrated = [{"product": "one", "direction": "export", "value": 100.0}]
        diversified = [
            {"product": p, "direction": "export", "value": 25.0}
            for p in ("a", "b", "c", "d")
        ]
        rc = compute_trade_scores(concentrated)["resilience_score"]
        rd = compute_trade_scores(diversified)["resilience_score"]
        assert rd > rc

    def test_missing_values_skipped(self):
        flows = [
            {"product": "A", "direction": "export", "value": 50.0},
            {"product": "B", "direction": "export", "value": None},
        ]
        res = compute_trade_scores(flows)
        assert res["hhi_exports"] == 1.0  # only A counts
