"""Tests del vocabulario de SKUs v2: por-sector + bundles, intervalos y grants de acceso."""
import pytest

from shared.billing.skus import (
    INTERVAL_ANNUAL,
    INTERVAL_MONTHLY,
    INTERVAL_ONCE,
    SKU_ALL_ACCESS,
    SKU_ENTERPRISE,
    SkuError,
    allowed_intervals,
    catalog_skus,
    deep_dive_sku,
    entitlement_for_sku,
    insight_sku,
    is_subscription_sku,
    parse_sku,
    sku_grants_access,
    sku_label,
    validate_sku,
)
from shared.products.registry import PRODUCT_CATALOG
from shared.products.tiers import ProductTier


def test_parse_sku_forms():
    assert parse_sku("insight:banking") == ("insight", "banking")
    assert parse_sku("deep_dive:banking") == ("deep_dive", "banking")
    assert parse_sku(SKU_ALL_ACCESS) == ("all_access", None)
    assert parse_sku(SKU_ENTERPRISE) == ("enterprise", None)
    assert parse_sku("special:soberano-2026") == ("special", "soberano-2026")
    for bad in ["", "insight", "insight:", "foo", "special:MAYÚS"]:
        with pytest.raises(SkuError):
            parse_sku(bad)


def test_validate_rejects_unknown_sector():
    assert validate_sku("insight:banking") == ("insight", "banking")
    with pytest.raises(SkuError):
        validate_sku("insight:no_existe")


def test_is_subscription_and_intervals():
    assert is_subscription_sku("insight:banking") is True
    assert is_subscription_sku(SKU_ALL_ACCESS) is True
    assert is_subscription_sku(SKU_ENTERPRISE) is True
    assert is_subscription_sku("deep_dive:banking") is False
    assert allowed_intervals("insight:banking") == [INTERVAL_MONTHLY, INTERVAL_ANNUAL]
    assert allowed_intervals("deep_dive:banking") == [INTERVAL_ONCE]


def test_sku_grants_access_scope():
    # insight:banking abre SOLO banking a nivel insight (no deep_dive, no otros sectores).
    assert sku_grants_access("insight:banking", "banking", ProductTier.insight.value) is True
    assert sku_grants_access("insight:banking", "banking", ProductTier.pulse.value) is True
    assert sku_grants_access("insight:banking", "banking", ProductTier.deep_dive.value) is False
    assert sku_grants_access("insight:banking", "macro", ProductTier.insight.value) is False
    # deep_dive:banking abre banking hasta deep_dive.
    assert sku_grants_access("deep_dive:banking", "banking", ProductTier.deep_dive.value) is True
    # all_access abre insight de TODOS los sectores, no deep_dive.
    assert sku_grants_access(SKU_ALL_ACCESS, "macro", ProductTier.insight.value) is True
    assert sku_grants_access(SKU_ALL_ACCESS, "macro", ProductTier.deep_dive.value) is False
    # enterprise abre todo.
    assert sku_grants_access(SKU_ENTERPRISE, "energy", ProductTier.deep_dive.value) is True


def test_entitlement_only_for_deep_dive():
    assert entitlement_for_sku("deep_dive:banking") == ("banking", ProductTier.deep_dive)
    assert entitlement_for_sku("insight:banking") is None
    assert entitlement_for_sku(SKU_ALL_ACCESS) is None


def test_sku_label():
    assert "Insight" in sku_label("insight:banking")
    assert "Deep Dive" in sku_label("deep_dive:banking")
    assert "All-Access" in sku_label(SKU_ALL_ACCESS)
    assert "Enterprise" in sku_label(SKU_ENTERPRISE)


def test_catalog_skus_enumerates_v2():
    items = catalog_skus()
    skus = {i["sku"] for i in items}
    # 2 por sector (insight + deep_dive) + 2 bundles.
    assert len(items) == 2 * len(PRODUCT_CATALOG) + 2
    assert SKU_ALL_ACCESS in skus and SKU_ENTERPRISE in skus
    for e in PRODUCT_CATALOG:
        assert insight_sku(e.sector_key) in skus and deep_dive_sku(e.sector_key) in skus
    ins = next(i for i in items if i["kind"] == "insight")
    assert ins["intervals"] == [INTERVAL_MONTHLY, INTERVAL_ANNUAL]
    dd = next(i for i in items if i["kind"] == "deep_dive")
    assert dd["intervals"] == [INTERVAL_ONCE]
