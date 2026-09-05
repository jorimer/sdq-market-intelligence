"""El sync de Colombia: qué persiste y qué se niega a declarar comparable."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main  # noqa: F401
from modules.regional_banking.models.models import CountryBankingAggregate
from modules.regional_banking.sfc_sync import sfc_sync
from shared.data.sfc_client import SFCClient
from shared.database.base import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    sesion = sessionmaker(bind=engine, autoflush=False)()
    yield sesion
    sesion.close()


def test_persiste_con_la_norma_colombiana(db):
    resumen = sfc_sync(db, client=SFCClient())
    assert resumen["synced"] > 0 and not resumen["errors"]
    normas = {f.norma_contable for f in db.query(CountryBankingAggregate).all()}
    assert normas == {"CUIF Colombia (SFC)"}


def test_nada_de_colombia_se_declara_comparable_entre_paises(db):
    """CUIF no es EMFA. La solvencia colombiana y la brasileña bajo la Res. CMN 4966 no
    son la misma medición, y el boletín las narra como trayectoria dentro de cada sistema."""
    sfc_sync(db, client=SFCClient())
    assert all(f.meta["comparable_entre_paises"] is False
               for f in db.query(CountryBankingAggregate).all())


def test_convive_con_secmca_sin_pisarlo(db):
    """`source` está en la clave única justamente para esto: dos emisores pueden traer la
    misma métrica del mismo país y período sin que uno borre al otro."""
    from modules.regional_banking.secmca_sync import secmca_sync
    from shared.data.secmca_client import SECMCAClient
    secmca_sync(db, client=SECMCAClient())
    antes = db.query(CountryBankingAggregate).count()
    sfc_sync(db, client=SFCClient())
    fuentes = {f.source for f in db.query(CountryBankingAggregate).all()}
    assert fuentes == {"SECMCA", "SFC"}
    assert db.query(CountryBankingAggregate).count() > antes


def test_es_idempotente(db):
    sfc_sync(db, client=SFCClient())
    n = db.query(CountryBankingAggregate).count()
    sfc_sync(db, client=SFCClient())
    assert db.query(CountryBankingAggregate).count() == n
