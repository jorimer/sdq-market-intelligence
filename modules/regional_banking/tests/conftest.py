"""Una base con el dato regional real de los fixtures, para probar contra el boletín."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main  # noqa: F401 — registra todos los modelos antes del create_all
from shared.database.base import Base


@pytest.fixture()
def db_regional():
    from modules.regional_banking.secmca_sync import secmca_sync
    from modules.regional_banking.sfc_sync import sfc_sync
    from shared.data.secmca_client import SECMCAClient
    from shared.data.sfc_client import SFCClient

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    sesion = sessionmaker(bind=engine, autoflush=False)()
    secmca_sync(sesion, client=SECMCAClient())
    sfc_sync(sesion, client=SFCClient())
    yield sesion
    sesion.close()
