"""Tests for the macro→sectorial contract producer (T-E3-2).

Offline: the producer is fed a synthetic ``grouped`` series map + the real
doctrine, so no DB or network is touched.
"""
from modules.macro_monitor.macro_context import _classify, _yoy_change, build_macro_context
from shared.contracts.macro_sector import ADVERSO, FAVORABLE, ND, NEUTRAL
from shared.data.bcrd_sectors import sector_catalog
from shared.doctrine import load_doctrine_raw

# Synthetic latest reads close to the real prod values (2026-06).
GROUPED = {
    "bcrd.inflacion.inflacion.interanual": [("2025-04", 5.35)],
    "bcrd.xls.imae_2018.variacion_porcentual_interanual": [("2025-04", 5.4)],
    "bcrd.xls.serie_tpm.tasa_de_politica_monetaria": [("2025-04", 0.0525)],  # ×100 → 5.25%
    "bcrd.sector_externo.tasas_de_cambio.venta": [("2024-04", 54.0), ("2025-04", 59.3)],  # +9.8% YoY
    "bcrd.xls.reservas_internacionales.reservas_brutas": [("2024-04", 15000.0), ("2025-04", 15771.0)],  # +5.1%
    "public_debt_gdp": [("2025", 62.4)],
    "bcrd.xls.remesas_6.valor": [("2024", 2800.0), ("2025", 2998.0)],  # +7.1% YoY
}


def _factors():
    c = build_macro_context(None, period="2025", grouped=GROUPED)
    return c, {f.key: f for f in c.factors}


def test_contract_has_all_factors_with_real_data():
    c, by_key = _factors()
    assert c.period == "2025"
    assert c.doctrine_version == "1.0"
    assert len(c.factors) == 7
    assert c.available_count == 7  # every factor resolved to real data


def test_directions_match_doctrine_thresholds():
    _, f = _factors()
    assert f["inflation"].direction == ADVERSO      # 5.35 ≥ 5.0
    assert f["activity"].direction == FAVORABLE     # 5.4 ≥ 3.5
    assert f["policy_rate"].direction == NEUTRAL    # 5.0 < 5.25 < 7.0
    assert f["policy_rate"].value == 5.25           # scaled ×100
    assert f["fx_depreciation"].direction == ADVERSO  # +9.8% ≥ 8.0
    assert f["reserves"].direction == FAVORABLE     # +5.1% ≥ 0.0
    assert f["public_debt"].direction == ADVERSO    # 62.4 ≥ 60.0
    assert f["remittances"].direction == FAVORABLE  # +7.1% ≥ 3.0


def test_change_mode_computes_yoy():
    _, f = _factors()
    assert f["fx_depreciation"].value == 9.81       # 59.3/54 - 1
    assert "interanual" in f["fx_depreciation"].reading


def test_impacted_sectors_resolved_to_names():
    _, f = _factors()
    sectors = f["inflation"].impacted_sectors
    assert {"slug": "comercio", "name": "Comercio"} in sectors
    assert all("slug" in s and "name" in s for s in sectors)
    assert f["inflation"].impacted_agents  # non-empty


def test_missing_series_is_nd_not_fabricated():
    grouped = {k: v for k, v in GROUPED.items() if k != "public_debt_gdp"}
    c = build_macro_context(None, period="2025", grouped=grouped)
    debt = next(f for f in c.factors if f.key == "public_debt")
    assert debt.direction == ND
    assert debt.value is None
    assert c.available_count == 6


def test_yoy_returns_none_without_year_anchor():
    # Two points only a month apart → no ~1-year anchor → None (never fabricated).
    assert _yoy_change([("2025-03", 100.0), ("2025-04", 110.0)]) is None


def test_classify_low_is_good():
    fdoc = {"good_direction": "low", "favorable_at": 4.0, "adverse_at": 5.0, "magnitude_ref": 2.0}
    assert _classify(3.9, fdoc) == (FAVORABLE, "bajo")     # 0.1 past favorable < ref/2
    assert _classify(4.5, fdoc) == (NEUTRAL, "bajo")       # between thresholds
    assert _classify(5.5, fdoc) == (ADVERSO, "bajo")       # 0.5 past adverse < ref/2
    assert _classify(8.0, fdoc) == (ADVERSO, "alto")       # 3.0 past adverse ≥ ref


def test_doctrine_integrity_slugs_and_series_valid():
    """Every impacted sector slug must exist in the catalog; series codes are strings."""
    doctrine = load_doctrine_raw("macro_sector")
    valid_slugs = {slug for slug, _name in sector_catalog()}
    for fdoc in doctrine["factors"]:
        assert isinstance(fdoc["series_code"], str) and fdoc["series_code"]
        for slug in fdoc.get("impacted_sectors", []):
            assert slug in valid_slugs, f"factor {fdoc['key']}: sector '{slug}' no existe en el catálogo"
        assert fdoc["good_direction"] in ("low", "high")
