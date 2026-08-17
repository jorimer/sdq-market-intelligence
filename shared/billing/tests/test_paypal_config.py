"""Tests de la config PayPal (settings.service): masking, preservar secreto ante MASK,
enabled requiere credenciales."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.settings.models import AppSetting
from shared.settings.schemas import MASK
from shared.settings.service import get_paypal_config, paypal_config_masked, set_paypal_config


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[AppSetting.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def test_empty_is_not_configured(db):
    cfg = get_paypal_config(db)
    assert cfg["enabled"] is False
    assert paypal_config_masked(db)["configured"] is False


def test_set_and_mask(db):
    set_paypal_config(db, client_id="CID", secret="SECRET", webhook_id="WH", env="live",
                      enabled=True, plans={"all_access": {"monthly": "P-AM", "annual": ""}})
    cfg = get_paypal_config(db)
    assert cfg["enabled"] is True and cfg["env"] == "live"
    assert cfg["client_id"] == "CID" and cfg["secret"] == "SECRET"
    # El mapa de planes limpia entradas vacías (annual="" se descarta).
    assert cfg["plans"] == {"all_access": {"monthly": "P-AM"}}
    masked = paypal_config_masked(db)
    assert masked["clientId"] == MASK and masked["secret"] == MASK  # nunca en claro
    assert masked["webhookId"] == "WH" and masked["configured"] is True
    assert masked["plans"] == {"all_access": {"monthly": "P-AM"}}


def test_mask_preserves_secret(db):
    set_paypal_config(db, client_id="CID", secret="SECRET", webhook_id="WH", env="sandbox",
                      enabled=True)
    # Reenviar MASK NO debe pisar el secreto guardado.
    set_paypal_config(db, client_id=MASK, secret=MASK, webhook_id="WH2", env="sandbox",
                      enabled=True)
    cfg = get_paypal_config(db)
    assert cfg["secret"] == "SECRET" and cfg["client_id"] == "CID"
    assert cfg["webhook_id"] == "WH2"  # el no-secreto sí se actualiza


def test_enabled_requires_credentials(db):
    # Habilitado pero sin credenciales → NO configurado (fail-closed).
    set_paypal_config(db, client_id=None, secret=None, webhook_id=None, env=None, enabled=True)
    assert get_paypal_config(db)["enabled"] is False


def test_la_primera_configuracion_conserva_los_planes(db):
    """Sin entorno previo no hay mudanza: es el alta. Borrar el mapa acá tiraría los planes
    que el admin está cargando en ese mismo request."""
    set_paypal_config(db, client_id="CID", secret="S", webhook_id="WH", env="live",
                      enabled=True, plans={"all_access": {"monthly": "P-LIVE"}})
    assert get_paypal_config(db)["plans"] == {"all_access": {"monthly": "P-LIVE"}}


def test_mudarse_de_sandbox_a_live_invalida_los_planes(db):
    """Un ``plan_id`` de sandbox NO existe en live: dejarlo mapeado hacía que el checkout
    intentara cobrar contra un plan inexistente. Se limpia para forzar el sync."""
    set_paypal_config(db, client_id="CID", secret="S", webhook_id="WH", env="sandbox",
                      enabled=True, plans={"all_access": {"monthly": "P-SANDBOX"}})
    assert get_paypal_config(db)["plans"] == {"all_access": {"monthly": "P-SANDBOX"}}

    set_paypal_config(db, client_id=None, secret=None, webhook_id=None, env="live",
                      enabled=None)
    assert get_paypal_config(db)["plans"] == {}, "quedaron planes de sandbox mapeados en live"


def test_mudarse_con_planes_nuevos_en_el_mismo_request_los_respeta(db):
    """Si el admin manda el mapa junto con el cambio de entorno, ese mapa es su intención
    explícita para el entorno nuevo y manda sobre la limpieza."""
    set_paypal_config(db, client_id="CID", secret="S", webhook_id="WH", env="sandbox",
                      enabled=True, plans={"all_access": {"monthly": "P-SANDBOX"}})
    set_paypal_config(db, client_id=None, secret=None, webhook_id=None, env="live",
                      enabled=None, plans={"all_access": {"monthly": "P-LIVE"}})
    assert get_paypal_config(db)["plans"] == {"all_access": {"monthly": "P-LIVE"}}


def test_el_webhook_id_se_reporta_como_capacidad_aparte(db):
    """Cobrar y RECIBIR EVENTOS son capacidades distintas: con credenciales se cobra, pero
    sin webhook_id no se verifica un solo evento entrante."""
    set_paypal_config(db, client_id="CID", secret="S", webhook_id="", env="sandbox",
                      enabled=True)
    masked = paypal_config_masked(db)
    assert masked["configured"] is True and masked["webhookReady"] is False

    set_paypal_config(db, client_id=None, secret=None, webhook_id="WH-1", env=None,
                      enabled=None)
    assert paypal_config_masked(db)["webhookReady"] is True
