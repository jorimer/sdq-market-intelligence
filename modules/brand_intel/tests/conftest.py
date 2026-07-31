"""Fixtures for brand_intel tests: in-memory DB and a small, fully-controlled engagement.

The fixture engagement is deliberately tiny and hand-computable, so a test asserts against
arithmetic anyone can redo on paper rather than against a snapshot of previous behaviour.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.settings.models import AppSetting  # noqa: F401 — registers the table the
# macro contract reads from; the deflation path queries it even when it is empty.
from modules.brand_intel.models.models import (
    BrandEngagement,
    BrandEntity,
    BrandObservation,
    BrandWave,
)

# Three waves, two in-set brands plus one out-of-set. Reach chosen so the category totals
# 100 in every wave: share then reads directly off the reach value.
WAVES = [
    ("w1", "Ola 1", 1, date(2025, 1, 1)),
    ("w2", "Ola 2", 2, date(2025, 7, 1)),
    ("w3", "Ola 3", 3, date(2026, 1, 1)),
]
REACH = {"focal": [40, 35, 45], "rival": [60, 65, 55], "outside": [10, 10, 10]}
FAVOURITE = {"focal": [30, 32, 28], "rival": [20, 22, 25]}


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    yield session
    session.close()


@pytest.fixture()
def engagement(db):
    eng = BrandEngagement(
        slug="demo", client_name="Cliente Demo", focal_brand="Focal",
        market="RD", category="QSR", research_provider="Proveedor",
    )
    db.add(eng)
    db.flush()

    wave_ids = {}
    for code, label, order, ref in WAVES:
        w = BrandWave(engagement_id=eng.id, code=code, label=label,
                      sort_order=order, period_date=ref, nominal_base=300)
        db.add(w)
        db.flush()
        wave_ids[code] = w.id

    for slug, name, focal, in_set in [
        ("focal", "Focal", True, True),
        ("rival", "Rival", False, True),
        ("outside", "Fuera", False, False),
    ]:
        db.add(BrandEntity(engagement_id=eng.id, slug=slug, name=name,
                           is_focal=focal, in_category_set=in_set))

    for brand, values in REACH.items():
        for (code, *_), value in zip(WAVES, values):
            db.add(BrandObservation(
                engagement_id=eng.id, wave_id=wave_ids[code], brand_slug=brand,
                metric_code="reach_7d", segment="total", value=value,
                base_n=300, unit="pct", source="fixture",
            ))
    for brand, values in FAVOURITE.items():
        for (code, *_), value in zip(WAVES, values):
            db.add(BrandObservation(
                engagement_id=eng.id, wave_id=wave_ids[code], brand_slug=brand,
                metric_code="favourite_place", segment="total", value=value,
                base_n=300, unit="pct", source="fixture",
            ))
    db.commit()
    eng.wave_ids = wave_ids          # convenience for tests
    return eng
