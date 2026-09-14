"""El sensor de anonimización sobre los Pulses YA cacheados — sin generar nada.

Lo que estos tests protegen es que el escaneo no MIENTA:

  * un Pulse cacheado VIGENTE cuyo texto nombra una entidad del roster aparece, marcado
    `vigente` — es el 500 que recibiría quien lo pida;
  * el mismo texto con huella VIEJA aparece también, pero `vigente=false`: ya no se sirve;
  * un texto anónimo NO aparece, y los niveles nombrados no se barren;
  * un eje declarado sin roster se CUENTA aparte en vez de «pasar» contra un roster vacío;
  * y el escaneo no toca la caché.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.observability.anonimizacion_en_cache import escanear_pulses_cacheados
from shared.products import ProductTier, get_product
from shared.products.assembler import _narrative_fingerprint
from shared.products.models import ProductReportCache
from modules.social_dev.models.models import DevelopmentScore


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    s.add(DevelopmentScore(entity_key="enriquillo", period="2024", development_score=38.4,
                           band="Bajo", breakdown={}))
    s.add(DevelopmentScore(entity_key="valdesia", period="2024", development_score=61.2,
                           band="Medio", breakdown={}))
    s.commit()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)


def _huella_vigente(db, sector, period, lang):
    producto = get_product(sector, db)
    snap = producto.snapshot(ProductTier.pulse, period, None)
    return _narrative_fingerprint(snap.payload, ProductTier.pulse.value, lang,
                                  modulo_producto=type(producto).__module__)


def _fila(db, *, sector="social_dev", tier="pulse", scope="", period="2024", lang="es",
          fingerprint, texto):
    db.add(ProductReportCache(sector_key=sector, tier=tier, scope=scope, period=period,
                              lang=lang, fingerprint=fingerprint,
                              narratives={"social_pulse": texto}))
    db.commit()


def test_un_pulse_VIGENTE_que_nombra_una_region_aparece_como_el_500_que_es(db):
    _fila(db, fingerprint=_huella_vigente(db, "social_dev", "2024", "es"),
          texto="Enriquillo registra el menor desarrollo del panel.")
    out = escanear_pulses_cacheados(db)
    assert [(v["sector"], v["periodo"], v["idioma"]) for v in out["vetadas_vigentes"]] == [
        ("social_dev", "2024", "es")]
    assert "Enriquillo" in out["vetadas_vigentes"][0]["motivo"]
    assert out["por_sector"]["social_dev"]["vigentes"] == 1


def test_el_mismo_texto_con_huella_VIEJA_se_lista_pero_no_como_vigente(db):
    _fila(db, lang="en", fingerprint="huella-de-otra-receta",
          texto="Ozama leads the regional ranking.")
    out = escanear_pulses_cacheados(db)
    assert out["vetadas_vigentes"] == []
    vetadas = out["por_sector"]["social_dev"]["vetadas"]
    assert len(vetadas) == 1 and vetadas[0]["vigente"] is False


def test_un_pulse_ANONIMO_no_aparece(db):
    _fila(db, lang="fr", fingerprint=_huella_vigente(db, "social_dev", "2024", "fr"),
          texto="La distribución del desarrollo entre regiones sigue dispersa.")
    out = escanear_pulses_cacheados(db)
    assert out["por_sector"]["social_dev"] == {
        "filas": 1, "vigentes": 1, "sin_roster": 0, "sin_snapshot": 0, "vetadas": []}


def test_los_niveles_NOMBRADOS_no_se_barren(db):
    """Un Insight de Enriquillo nombra a Enriquillo por diseño."""
    _fila(db, tier="insight", scope="enriquillo", fingerprint="f",
          texto="Enriquillo registra el menor desarrollo del panel.")
    out = escanear_pulses_cacheados(db)
    assert out["filas_leidas"] == 0 and out["por_sector"] == {}


def test_un_eje_SIN_roster_se_cuenta_aparte_en_vez_de_pasar_limpio(db):
    _fila(db, sector="trade", period="2025", fingerprint="f",
          texto="Estados Unidos sigue siendo el primer socio comercial.")
    out = escanear_pulses_cacheados(db, sector="trade")
    assert out["por_sector"]["trade"]["sin_roster"] == 1
    assert out["por_sector"]["trade"]["vetadas"] == []


def test_el_escaneo_no_toca_la_cache(db):
    texto = "Enriquillo registra el menor desarrollo del panel."
    _fila(db, fingerprint=_huella_vigente(db, "social_dev", "2024", "es"), texto=texto)
    escanear_pulses_cacheados(db)
    filas = db.query(ProductReportCache).all()
    assert len(filas) == 1 and filas[0].narratives == {"social_pulse": texto}


def test_una_cache_vacia_lo_DECLARA_en_vez_de_parecer_limpia(db):
    out = escanear_pulses_cacheados(db)
    assert out["filas_leidas"] == 0 and out["vetadas_vigentes"] == []


# ── Por HTTP: el entregable es la ruta, no la función ────────────────────────────

class _Usuario:
    id = "admin-1"
    role = None
    organization_id = None
    email = "admin@sdq.test"


def _cliente(db, rol):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from shared.auth.dependencies import get_current_user
    from shared.database.session import get_db
    from shared.operations.router import router

    _Usuario.role = rol
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/operations")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _Usuario()
    return TestClient(app)


def test_por_HTTP_el_admin_VE_el_pulse_vigente_que_nombra_una_region(db):
    from shared.auth.models import UserRole

    _fila(db, fingerprint=_huella_vigente(db, "social_dev", "2024", "es"),
          texto="Enriquillo registra el menor desarrollo del panel.")
    r = _cliente(db, UserRole.admin).get(
        "/api/v1/operations/anonimizacion-en-cache", params={"sector": "social_dev"})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["sector"] == "social_dev"
    assert [(v["sector"], v["periodo"]) for v in cuerpo["vetadas_vigentes"]] == [
        ("social_dev", "2024")]


def test_por_HTTP_el_escaneo_es_de_ADMIN(db):
    from shared.auth.models import UserRole

    r = _cliente(db, UserRole.viewer).get("/api/v1/operations/anonimizacion-en-cache")
    assert r.status_code == 403
