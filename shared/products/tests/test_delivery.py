"""Tests de la superficie de ENTREGA comercial (/api/v1/products/{sector}/{tier}/report
y /download). Verifican el gate (activación + tier) integrado con el ensamblador, la
forma del JSON y la traducción de errores. El ensamblador se mockea (sin llamar a Claude).
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.products.router as prod_router
from shared.auth.dependencies import get_current_user
from shared.auth.models import AccessTier
from shared.database.base import Base
from shared.database.session import get_db
from shared.products.assembler import ProductContent
from shared.products.contract import ProductSnapshot
from shared.products.models import ProductActivation, ProductReadiness
from shared.products.tiers import Granularity, ProductTier, TierLevelSpec


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[ProductActivation.__table__,
                                             ProductReadiness.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


class _User:
    def __init__(self, tier):
        self.tier = tier


def _activate(db, sector, tier):
    db.add(ProductActivation(sector_key=sector, tier=tier.value, is_active=True))
    db.commit()


_PULSE_LEVEL = TierLevelSpec(
    tier=ProductTier.pulse, granularity=Granularity.system,
    sections=("system_overview",), narrative_templates=("sector_outlook",),
    audience="mercado / abierto", cadence="periodic",
    watermark="Vista abierta · SDQMIP", price_band="abierto",
)
_INSIGHT_LEVEL = TierLevelSpec(
    tier=ProductTier.insight, granularity=Granularity.named_entity,
    sections=("executive_summary",), narrative_templates=("executive_summary",),
    audience="cliente / comité", cadence="recurring", price_band="suscripción",
)


def _client(db, user_tier=AccessTier.free, monkeypatch=None, content=None,
            pdf_path=None, raises=None):
    """Monta el router real con el ensamblador mockeado."""
    app = FastAPI()
    app.include_router(prod_router.router, prefix="/api/v1/products")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _User(user_tier)

    if monkeypatch is not None:
        monkeypatch.setattr(prod_router, "get_product", lambda sector, db: object())

        async def _fake_content(product, tier, *, period, scope=None, lang="es"):
            if raises is not None:
                raise raises
            return content
        monkeypatch.setattr(prod_router, "assemble_product_content", _fake_content)

        async def _fake_report(product, tier, *, period, scope=None, lang="es", **kw):
            if raises is not None:
                raise raises
            return pdf_path
        monkeypatch.setattr(prod_router, "assemble_product_report", _fake_report)

    return TestClient(app)


# ─── Gate de entrega: la entrega respeta activación + tier ──────────────

def test_report_not_published_404(db, monkeypatch):
    c = _client(db, AccessTier.enterprise, monkeypatch)
    assert c.get("/api/v1/products/banking/pulse/report").status_code == 404


def test_report_tier_insufficient_402(db, monkeypatch):
    _activate(db, "banking", ProductTier.insight)
    c = _client(db, AccessTier.free, monkeypatch)
    r = c.get("/api/v1/products/banking/insight/report")
    assert r.status_code == 402
    assert r.json()["detail"]["required_tier"] == "pro"


def test_report_allowed_returns_content(db, monkeypatch):
    _activate(db, "banking", ProductTier.pulse)
    content = ProductContent(
        level=_PULSE_LEVEL,
        snapshot=ProductSnapshot(tier=ProductTier.pulse, period="2024-12-31",
                                 payload={"band_distribution": {"Fuerte": 3}}, entity_name=None),
        narratives={"system_overview": "El sistema bancario muestra solidez."},
    )
    c = _client(db, AccessTier.free, monkeypatch, content=content)
    r = c.get("/api/v1/products/banking/pulse/report")
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "pulse"
    assert body["period"] == "2024-12-31"
    assert body["entity_name"] is None
    assert body["narratives"]["system_overview"].startswith("El sistema")
    assert body["commercial"]["price_band"] == "abierto"
    assert body["commercial"]["watermark"] == "Vista abierta · SDQMIP"
    assert body["commercial"]["sections"] == ["system_overview"]


def test_insight_requires_pro_and_serves_named(db, monkeypatch):
    _activate(db, "banking", ProductTier.insight)
    content = ProductContent(
        level=_INSIGHT_LEVEL,
        snapshot=ProductSnapshot(tier=ProductTier.insight, period="2024-12-31",
                                 payload={"scoring_result": {"overall_score": 82.0}},
                                 entity_name="Banco Demo, S.A."),
        narratives={"executive_summary": "Banco Demo mantiene calificación sólida."},
    )
    c = _client(db, AccessTier.pro, monkeypatch, content=content)
    r = c.get("/api/v1/products/banking/insight/report")
    assert r.status_code == 200
    assert r.json()["entity_name"] == "Banco Demo, S.A."
    assert r.json()["commercial"]["price_band"] == "suscripción"


# ─── Errores del ensamblador → HTTP en español ─────────────────────────

def test_report_value_error_is_422(db, monkeypatch):
    _activate(db, "banking", ProductTier.insight)
    c = _client(db, AccessTier.enterprise, monkeypatch,
                raises=ValueError("Se requiere 'scope' (entidad) para Insight/Deep Dive."))
    r = c.get("/api/v1/products/banking/insight/report")
    assert r.status_code == 422
    assert "scope" in r.json()["detail"]


def test_report_anonymization_error_is_500(db, monkeypatch):
    from shared.products.anonymization import AnonymizationError
    _activate(db, "banking", ProductTier.pulse)
    c = _client(db, AccessTier.free, monkeypatch, raises=AnonymizationError("fuga"))
    r = c.get("/api/v1/products/banking/pulse/report")
    assert r.status_code == 500
    assert "gobernanza" in r.json()["detail"]


# ─── Descarga PDF ──────────────────────────────────────────────────────

def test_download_returns_pdf(db, monkeypatch, tmp_path):
    _activate(db, "banking", ProductTier.pulse)
    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    c = _client(db, AccessTier.free, monkeypatch, pdf_path=str(pdf))
    r = c.get("/api/v1/products/banking/pulse/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


def test_download_respects_gate_402(db, monkeypatch):
    _activate(db, "banking", ProductTier.deep_dive)
    c = _client(db, AccessTier.pro, monkeypatch)
    assert c.get("/api/v1/products/banking/deep_dive/download").status_code == 402


def test_download_not_published_404(db, monkeypatch):
    # Asimetría cerrada: la descarga también da 404 para lo no publicado.
    c = _client(db, AccessTier.enterprise, monkeypatch)
    assert c.get("/api/v1/products/banking/pulse/download").status_code == 404


# ─── Nivel inválido + passthrough de scope ─────────────────────────────

def test_delivery_invalid_tier_400(db, monkeypatch):
    c = _client(db, AccessTier.enterprise, monkeypatch)
    assert c.get("/api/v1/products/banking/nope/report").status_code == 400
    assert c.get("/api/v1/products/banking/nope/download").status_code == 400


def test_scope_reaches_assembler(db, monkeypatch):
    """El ``scope`` del query string debe llegar al ensamblador (entidad de Insight)."""
    _activate(db, "banking", ProductTier.insight)
    seen = {}

    async def _spy(product, tier, *, period, scope=None, lang="es"):
        seen["scope"] = scope
        seen["period"] = period
        return ProductContent(
            level=_INSIGHT_LEVEL,
            snapshot=ProductSnapshot(tier=ProductTier.insight, period="2024-12-31",
                                     payload={}, entity_name="Banco Demo, S.A."),
            narratives={"executive_summary": "ok"})

    app = FastAPI()
    app.include_router(prod_router.router, prefix="/api/v1/products")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _User(AccessTier.enterprise)
    monkeypatch.setattr(prod_router, "get_product", lambda sector, db: object())
    monkeypatch.setattr(prod_router, "assemble_product_content", _spy)
    r = TestClient(app).get(
        "/api/v1/products/banking/insight/report?scope=Banco%20Demo%2C%20S.A.&period=2024-12-31")
    assert r.status_code == 200
    assert seen["scope"] == "Banco Demo, S.A."
    assert seen["period"] == "2024-12-31"
