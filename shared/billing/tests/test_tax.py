"""Tests del motor de impuesto (ITBIS) — correctitud fiscal al centavo."""
from shared.billing.tax import (
    EXEMPT_REASON_FOREIGN,
    compute_tax,
    compute_tax_from_total,
    normalize_country,
)

CFG = {"enabled": True, "rate": "18", "label": "ITBIS", "home_country": "DO",
       "exempt_foreign": True}


def test_rd_client_pays_itbis():
    b = compute_tax("100.00", currency="USD", country="DO", config=CFG)
    assert b.subtotal == "100.00" and b.tax == "18.00" and b.total == "118.00"
    assert b.rate_pct == "18" and b.label == "ITBIS" and b.exempt is False


def test_foreign_client_exempt():
    b = compute_tax("100.00", currency="USD", country="US", config=CFG)
    assert b.tax == "0.00" and b.total == "100.00" and b.exempt is True
    assert b.exempt_reason == EXEMPT_REASON_FOREIGN and b.rate_pct == "0"


def test_rounding_half_up_to_cents():
    # 49.99 * 0.18 = 8.9982 → 9.00 ; 19.95 * 0.18 = 3.591 → 3.59
    assert compute_tax("49.99", currency="USD", country="DO", config=CFG).tax == "9.00"
    assert compute_tax("19.95", currency="USD", country="DO", config=CFG).tax == "3.59"


def test_total_equals_subtotal_plus_tax_exactly():
    for sub in ["1.00", "9.99", "33.33", "250.50", "1000.00"]:
        b = compute_tax(sub, currency="USD", country="DO", config=CFG)
        assert float(b.total) == round(float(b.subtotal) + float(b.tax), 2)


def test_tax_disabled_charges_subtotal_only():
    b = compute_tax("100.00", currency="USD", country="DO", config={**CFG, "enabled": False})
    assert b.tax == "0.00" and b.total == "100.00" and b.exempt is False  # no exención: apagado


def test_exempt_foreign_off_taxes_everyone():
    b = compute_tax("100.00", currency="USD", country="US",
                    config={**CFG, "exempt_foreign": False})
    assert b.tax == "18.00" and b.total == "118.00" and b.exempt is False


def test_from_total_reverses_to_subtotal():
    # 118.00 total con 18% → subtotal 100.00 + tax 18.00
    b = compute_tax_from_total("118.00", currency="USD", country="DO", config=CFG)
    assert b.subtotal == "100.00" and b.tax == "18.00" and b.total == "118.00"


def test_from_total_foreign_is_all_subtotal():
    b = compute_tax_from_total("100.00", currency="USD", country="US", config=CFG)
    assert b.subtotal == "100.00" and b.tax == "0.00" and b.exempt is True


def test_normalize_country_defaults_to_do():
    assert normalize_country(None) == "DO" and normalize_country("") == "DO"
    assert normalize_country("us") == "US" and normalize_country("  es ") == "ES"
