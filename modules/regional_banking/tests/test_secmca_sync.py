"""El sync de SECMCA: qué persiste, y qué se niega a afirmar."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main  # noqa: F401 — registra todos los modelos antes del create_all
from modules.regional_banking.models.models import CountryBankingAggregate
from modules.regional_banking.secmca_sync import secmca_sync
from shared.data.secmca_client import SECMCAClient
from shared.database.base import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    sesion = sessionmaker(bind=engine, autoflush=False)()
    yield sesion
    sesion.close()


def test_persiste_con_su_norma_contable(db):
    """Sin `norma_contable` el guard de no-comparabilidad no tiene sobre qué decidir."""
    resumen = secmca_sync(db, client=SECMCAClient())
    assert resumen["synced"] > 0 and not resumen["errors"]
    normas = {f.norma_contable for f in db.query(CountryBankingAggregate).all()}
    assert normas == {"EMFA armonizado"}


def test_declara_el_corte_pais_por_pais(db):
    """Las plazas publican con rezagos muy distintos y el boletín lo dice explícitamente:
    un corte único desperdiciaría la frescura de las rápidas por la más lenta."""
    cortes = secmca_sync(db, client=SECMCAClient())["cortes_por_pais"]
    assert len(cortes) > 1
    assert len(set(cortes.values())) > 1, "si todos coincidieran, no habría nada que declarar"


def test_el_ausente_se_persiste_ausente(db):
    """`n.a` en el cuadro no es cero: en una tasa, cero es una afirmación fuerte y falsa."""
    secmca_sync(db, client=SECMCAClient())
    nulos = db.query(CountryBankingAggregate).filter(
        CountryBankingAggregate.value.is_(None)).all()
    assert nulos, "el recorte incluye ausencias reales de la fuente"
    assert all(f.meta.get("reason") for f in nulos), "una ausencia se explica, no se calla"


def test_solo_las_tasas_se_marcan_comparables_entre_paises(db):
    """EMFA armoniza la METODOLOGÍA, no la unidad: el crédito va en moneda local y el
    cuadro deja la unidad en blanco («Saldos en millones de ___»)."""
    secmca_sync(db, client=SECMCAClient())
    for fila in db.query(CountryBankingAggregate).all():
        esperado = fila.metric.startswith("tasa_")
        assert fila.meta["comparable_entre_paises"] is esperado


def test_es_idempotente(db):
    """Se corre cada mes sobre la misma serie: la segunda pasada actualiza, no duplica."""
    primera = secmca_sync(db, client=SECMCAClient())["synced"]
    n1 = db.query(CountryBankingAggregate).count()
    secmca_sync(db, client=SECMCAClient())
    assert db.query(CountryBankingAggregate).count() == n1 == primera


def test_un_fallo_de_la_fuente_no_fabrica_datos(db):
    """Si el conector falla, se reporta y no se persiste nada. Nunca se rellena."""
    class _Rota(SECMCAClient):
        def fetch(self, series=None, period=None):
            raise RuntimeError("secmca.org no responde")

    resumen = secmca_sync(db, client=_Rota())
    assert resumen["synced"] == 0 and resumen["errors"]
    assert db.query(CountryBankingAggregate).count() == 0
