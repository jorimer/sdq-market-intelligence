"""Partner-country concentration (geographic resilience). Offline."""
from modules.trade_intel.partners import _block, partner_concentration_report


def test_block_hhi_top_and_diversification():
    b = _block({"USA": 60.0, "Haiti": 20.0, "China": 20.0})
    assert b["total"] == 100.0
    assert b["hhi"] == 0.44                       # 0.6² + 0.2² + 0.2²
    assert b["diversification"] == 56.0           # (1 - 0.44) * 100
    assert b["n_partners"] == 3
    assert b["top"][0] == {"partner": "USA", "value": 60.0, "share": 0.6}


def test_block_empty_is_safe():
    b = _block({})
    assert b["total"] == 0 and b["hhi"] is None and b["diversification"] is None and b["top"] == []


def test_report_latest_period_with_both_directions():
    ds = {
        "meta": {"source": "UN Comtrade"},
        "partners": {
            "2022": {"export": {"USA": 5.0}, "import": {"USA": 9.0}},
            "2023": {"export": {"USA": 7.0, "Haiti": 1.0}, "import": {"USA": 12.0, "China": 5.0}},
        },
    }
    r = partner_concentration_report(ds)
    assert r["has_data"] and r["period"] == "2023"   # latest year wins
    assert r["export"]["n_partners"] == 2 and r["export"]["top"][0]["partner"] == "USA"
    assert r["import"]["n_partners"] == 2


def test_report_no_data():
    assert partner_concentration_report({})["has_data"] is False
    assert partner_concentration_report({"partners": {}})["has_data"] is False
