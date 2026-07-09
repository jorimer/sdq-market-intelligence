"""Tests del vocabulario de SKUs del tarifario (shared/billing/skus)."""
import pytest

from shared.billing.skus import (
    SKU_INSIGHT,
    SkuError,
    catalog_skus,
    deep_dive_sku,
    entitlement_for_sku,
    parse_sku,
    sku_label,
    special_sku,
    validate_sku,
)
from shared.products.registry import PRODUCT_CATALOG
from shared.products.tiers import ProductTier


def test_insight_sku_parses():
    assert parse_sku(SKU_INSIGHT) == ("insight", None)
    assert validate_sku("insight") == ("insight", None)


def test_deep_dive_sku_roundtrip():
    sku = deep_dive_sku("banking")
    assert sku == "deep_dive:banking"
    assert parse_sku(sku) == ("deep_dive", "banking")
    assert validate_sku(sku) == ("deep_dive", "banking")


def test_special_sku_roundtrip():
    sku = special_sku("riesgo-soberano-2026")
    assert sku == "special:riesgo-soberano-2026"
    assert parse_sku(sku) == ("special", "riesgo-soberano-2026")


def test_validate_rejects_unknown_sector():
    with pytest.raises(SkuError):
        validate_sku("deep_dive:no_existe")


def test_parse_rejects_garbage():
    for bad in ["", "foo", "deep_dive:", "special:", "special:MAYÚS", "special:con espacio"]:
        with pytest.raises(SkuError):
            parse_sku(bad)


def test_entitlement_for_sku_only_for_deep_dive():
    assert entitlement_for_sku("deep_dive:banking") == ("banking", ProductTier.deep_dive)
    assert entitlement_for_sku("insight") is None
    assert entitlement_for_sku("special:algo") is None


def test_sku_label_human_readable():
    assert sku_label("insight") == "plan Insight"
    assert "Deep Dive" in sku_label("deep_dive:banking")
    assert sku_label("deep_dive:no_existe") == "Deep Dive de no_existe"  # parse ok, sin catálogo
    assert "informe especial" in sku_label("special:riesgo-2026")
    assert sku_label("basura") == "basura"  # inválido → best-effort


def test_catalog_skus_enumerates_insight_plus_every_product():
    items = catalog_skus()
    skus = {i["sku"] for i in items}
    assert SKU_INSIGHT in skus
    assert len(items) == 1 + len(PRODUCT_CATALOG)  # insight + un deep_dive por producto
    for entry in PRODUCT_CATALOG:
        assert deep_dive_sku(entry.sector_key) in skus
    insight = next(i for i in items if i["sku"] == SKU_INSIGHT)
    assert insight["kind"] == "insight" and insight["ref"] is None and insight["label"]
    dd = next(i for i in items if i["kind"] == "deep_dive")
    assert dd["ref"] in {e.sector_key for e in PRODUCT_CATALOG} and dd["label"]
