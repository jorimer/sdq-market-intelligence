"""Caché de narrativas del assembler: un HIT evita regenerar; el cambio de dato invalida."""
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.products.assembler import _narratives_cached, _narrative_fingerprint
from shared.products.contract import ProductSnapshot
from shared.products.models import ProductReportCache  # noqa: F401 — registra la tabla
from shared.products.tiers import ProductTier


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[ProductReportCache.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


class _FakeProduct:
    sector_key = "macro"

    def __init__(self, db):
        self.db = db
        self.calls = 0

    async def narratives(self, tier, snapshot, lang):
        self.calls += 1
        return {"risk_assessment": f"generación #{self.calls}"}


def _snap(payload):
    return ProductSnapshot(tier=ProductTier.deep_dive, period="2024", payload=payload)


def test_second_call_is_a_cache_hit(db):
    p = _FakeProduct(db)
    snap = _snap({"irmp_score": 50})
    n1 = asyncio.run(_narratives_cached(p, ProductTier.deep_dive, snap, "es", "DO"))
    n2 = asyncio.run(_narratives_cached(p, ProductTier.deep_dive, snap, "es", "DO"))
    assert p.calls == 1                       # el 2º no regeneró (HIT)
    assert n1 == n2 == {"risk_assessment": "generación #1"}
    assert db.query(ProductReportCache).count() == 1


def test_changed_data_invalidates(db):
    p = _FakeProduct(db)
    asyncio.run(_narratives_cached(p, ProductTier.deep_dive, _snap({"irmp_score": 50}), "es", "DO"))
    asyncio.run(_narratives_cached(p, ProductTier.deep_dive, _snap({"irmp_score": 55}), "es", "DO"))
    assert p.calls == 2                        # el payload cambió → fingerprint distinto → MISS
    row = db.query(ProductReportCache).filter_by(scope="DO", period="2024").one()  # actualizado en sitio
    assert row.narratives == {"risk_assessment": "generación #2"}


def test_scope_and_lang_are_separate_keys(db):
    p = _FakeProduct(db)
    snap = _snap({"irmp_score": 50})
    asyncio.run(_narratives_cached(p, ProductTier.deep_dive, snap, "es", "DO"))
    asyncio.run(_narratives_cached(p, ProductTier.deep_dive, snap, "es", "CR"))  # otro ámbito
    asyncio.run(_narratives_cached(p, ProductTier.deep_dive, snap, "en", "DO"))  # otro idioma
    assert p.calls == 3 and db.query(ProductReportCache).count() == 3


def test_fingerprint_changes_with_version(monkeypatch):
    import shared.products.assembler as asm
    fp1 = _narrative_fingerprint({"x": 1}, "deep_dive", "es")
    monkeypatch.setattr(asm, "NARRATIVE_CACHE_VERSION", "2")
    fp2 = _narrative_fingerprint({"x": 1}, "deep_dive", "es")
    assert fp1 != fp2   # bumpear la versión invalida toda la caché


def test_no_db_falls_back_to_direct_generation():
    p = _FakeProduct(None)
    n = asyncio.run(_narratives_cached(p, ProductTier.deep_dive, _snap({"a": 1}), "es", None))
    assert p.calls == 1 and n == {"risk_assessment": "generación #1"}
