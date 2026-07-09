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
                      enabled=True, plan_pro="P-PRO")
    cfg = get_paypal_config(db)
    assert cfg["enabled"] is True and cfg["env"] == "live"
    assert cfg["client_id"] == "CID" and cfg["secret"] == "SECRET"
    assert cfg["plans"]["pro"] == "P-PRO"
    masked = paypal_config_masked(db)
    assert masked["clientId"] == MASK and masked["secret"] == MASK  # nunca en claro
    assert masked["webhookId"] == "WH" and masked["configured"] is True


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
