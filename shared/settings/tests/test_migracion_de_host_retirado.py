"""Cuando un emisor cambia de dominio y el viejo SIGUE respondiendo.

**El caso (2026-08-19).** JurisAI migró a `api.jurisai.do`. El host anterior —generado por
Railway, fuera de su control— siguió devolviendo 200 con la misma credencial y las mismas
rutas. Sin error, sin aviso y sin fecha de corte: una integración que se quedara apuntando
ahí funcionaría igual hasta el día que el dominio prestado desapareciera, con el entregable
ya en manos del cliente institucional.

**Por qué no alcanzaba con cambiar la constante.** `ensure_known_sources` es idempotente POR
PROVEEDOR: salta si el proveedor ya existe y nunca actualiza una fila. Cambiar el default
arregla las instalaciones nuevas y deja apuntando al host retirado a las que ya funcionaban —
que son justamente las que están en producción.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.settings.models import AppSetting, SectorApiConfig
from shared.settings.service import KNOWN_PROVIDERS, migrar_urls_obsoletas


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[AppSetting.__table__,
                                             SectorApiConfig.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _jurisai():
    return next(s for s in KNOWN_PROVIDERS if s["provider"] == "jurisai")


def test_el_default_apunta_al_dominio_PROPIO_del_emisor():
    assert _jurisai()["baseUrl"] == "https://api.jurisai.do/api/v1"


def test_el_host_retirado_queda_declarado_como_obsoleto():
    """Declararlo es lo que permite migrarlo. Borrarlo del código sin más dejaría a las
    instalaciones existentes apuntando ahí para siempre."""
    assert ("https://jurisai-production.up.railway.app/api/v1"
            in _jurisai()["obsoleteBaseUrls"])


def test_una_url_RETIRADA_se_migra_sola(db):
    cfg = SectorApiConfig(provider="jurisai", sector="law",
                          base_url="https://jurisai-production.up.railway.app/api/v1")
    db.add(cfg); db.commit()
    assert migrar_urls_obsoletas(db) == 1
    db.refresh(cfg)
    assert cfg.base_url == "https://api.jurisai.do/api/v1"


def test_migra_aunque_el_proveedor_difiera_en_MAYUSCULAS(db):
    """En producción convivían `jurisai` (sembrada) y `JurisAI` (creada a mano por el
    operador). La segunda quedaba inerte porque la búsqueda es exacta, pero su URL vieja
    seguía a la vista y confundía a quien la editara."""
    cfg = SectorApiConfig(provider="JurisAI", sector="law",
                          base_url="https://jurisai-production.up.railway.app/api/v1")
    db.add(cfg); db.commit()
    assert migrar_urls_obsoletas(db) == 1
    db.refresh(cfg)
    assert cfg.base_url == "https://api.jurisai.do/api/v1"


def test_una_url_que_el_OPERADOR_escribió_no_se_toca(db):
    """No sabemos por qué la puso —un proxy, un entorno de prueba, un túnel— y pisarla sería
    peor que dejarla vieja. Solo se migra lo que ESTE repo sirvió como default."""
    cfg = SectorApiConfig(provider="jurisai", sector="law",
                          base_url="https://mi-proxy.interno/api/v1")
    db.add(cfg); db.commit()
    assert migrar_urls_obsoletas(db) == 0
    db.refresh(cfg)
    assert cfg.base_url == "https://mi-proxy.interno/api/v1"


def test_es_idempotente(db):
    cfg = SectorApiConfig(provider="jurisai", sector="law",
                          base_url="https://jurisai-production.up.railway.app/api/v1")
    db.add(cfg); db.commit()
    assert migrar_urls_obsoletas(db) == 1
    assert migrar_urls_obsoletas(db) == 0


def test_el_resultado_de_la_prueba_NOMBRA_el_host():
    """Parece redundante y es la única defensa contra el cambio silencioso: una prueba que
    dijera solo «Conectado» daría verde apuntando al host retirado."""
    import inspect
    from shared.settings import service

    fuente = inspect.getsource(service._test_jurisai_connection)
    assert "Conectado a {host}" in fuente
