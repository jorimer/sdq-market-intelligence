"""Estado del rollout de la muestra + sensor de gate (A3, doctrina curada).

La muestra es un EXEMPLAR CURADO tier-1 (no generación al vuelo). Un sector la ofrece
solo si tiene la narrativa curada (`sample_narratives`); los datos demo (`sample_snapshot`)
son la base, ya cableada en los 10, pero no bastan por sí solos.

- Los 10 sectores tienen `sample_snapshot` (datos demo listos para curar).
- Hoy SOLO los sectores con exemplar curado ofrecen muestra (Banca); los demás quedan
  apagados, honestos, hasta que se redacte su exemplar.
- Banca renderiza su muestra curada en los 3 niveles (con el sensor de anonimización).
- Ninguna superficie de ENTREGA de producto (report / download / sample / catalog) es anónima.
"""
import asyncio
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.products.router as prod_router
from shared.database.base import Base
from shared.database.session import get_db
from shared.products import (
    PRODUCT_CATALOG,
    assemble_sample_report,
    get_product,
    registered_sectors,
    supports_sample,
)
from shared.products.models import (
    ProductActivation,
    ProductEntitlement,
    ProductReadiness,
    SampleGrant,
)
from shared.products.tiers import ProductTier

# Sectores con exemplar curado. Hoy los 10 (cada sector tiene su narrativa tier-1).
# Si se agrega un sector nuevo al catálogo, debe redactarse su exemplar o salir de aquí.
_CURATED = {e.sector_key for e in PRODUCT_CATALOG}


def _register_all():
    """Importa los módulos de sector → se auto-registran en el catálogo de productos."""
    import app.products_macro  # noqa: F401
    import modules.banking_score.products  # noqa: F401
    import modules.energy_intel.products  # noqa: F401
    import modules.esg_climate.products  # noqa: F401
    import modules.free_zones_intel.products  # noqa: F401
    import modules.sector_intel.products  # noqa: F401
    import modules.sector_intel.structure_product  # noqa: F401 — economic_structure (agregado)
    import modules.telecom_intel.products  # noqa: F401
    import modules.tourism_intel.products  # noqa: F401
    import modules.construction_intel.products  # noqa: F401 — construction (dedicado, ICC)
    import modules.trade_intel.products  # noqa: F401
    import modules.pension_intel.products  # noqa: F401
    import modules.insurance_intel.products  # noqa: F401 — insurance (dedicado, SIS)
    import modules.social_dev.products  # noqa: F401 — social_dev (panel SUB-NACIONAL)
    import modules.law_intel.products  # noqa: F401 — law (sujeto = instrumento normativo)


def test_all_ten_sectors_have_demo_data():
    """Los 10 sectores tienen datos demo (`sample_snapshot`) — base del exemplar."""
    _register_all()
    sectors = registered_sectors()
    assert len(sectors) == len(PRODUCT_CATALOG)
    for key in sectors:
        product = get_product(key, None)
        assert callable(getattr(product, "sample_snapshot", None)), f"{key} sin datos demo"


def test_only_curated_sectors_offer_sample():
    """`supports_sample` exige exemplar curado: hoy solo los sectores en _CURATED."""
    _register_all()
    for key in registered_sectors():
        product = get_product(key, None)
        assert supports_sample(product) == (key in _CURATED), f"{key}: gate de muestra incorrecto"


@pytest.mark.parametrize("tier", [ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive])
def test_curated_sample_renders(tier, tmp_path):
    """Cada sector curado renderiza su muestra (exemplar) en cada nivel, con el sensor de
    anonimización corriendo sobre el Pulse (sin DB, sin fuga de identificadores)."""
    _register_all()
    for key in sorted(_CURATED):
        product = get_product(key, None)
        path = asyncio.run(assemble_sample_report(product, tier, output_dir=str(tmp_path)))
        assert os.path.exists(path) and path.endswith(".pdf"), f"{key}/{tier.value} no renderizó"


def test_product_without_curated_exemplar_raises():
    """Un producto sin exemplar curado (sample_narratives) no produce muestra: ValueError
    en español. Blinda la doctrina aunque hoy los 10 sectores estén curados."""
    class _NoExemplar:
        sector_key = "x"

        def sample_snapshot(self, tier):  # datos demo pero SIN narrativa curada
            return None
    with pytest.raises(ValueError, match="muestra curada"):
        asyncio.run(assemble_sample_report(_NoExemplar(), ProductTier.insight))


# ─── Sensor de gate: ninguna superficie de producto es anónima ─────────

@pytest.fixture()
def _app():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[ProductActivation.__table__,
                                             ProductReadiness.__table__, SampleGrant.__table__,
                                             ProductEntitlement.__table__])
    db = sessionmaker(bind=engine)()
    app = FastAPI()
    app.include_router(prod_router.router, prefix="/api/v1/products")
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield app
    finally:
        db.close()


@pytest.mark.parametrize("path", [
    "/api/v1/products/banking/insight/report",
    "/api/v1/products/banking/insight/download",
    "/api/v1/products/banking/insight/sample",
    "/api/v1/products/catalog",
])
def test_product_surfaces_require_auth(_app, path):
    """Sin credenciales, ninguna superficie de producto/consumo responde 200 (HTTPBearer
    rechaza con 401/403). Si una ruta nueva se sirviera anónima, este sensor falla."""
    r = TestClient(_app).get(path)
    assert r.status_code in (401, 403), f"{path} respondió {r.status_code} sin auth"
