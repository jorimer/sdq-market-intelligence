"""Tests de la credencial y de la cuota de la Data API.

Lo que se protege acá: que el secreto no se pueda derivar de lo persistido, que un token
mal formado no cueste una consulta, y que la cuota cuente en DB (no en memoria) para que
sea la misma con uno o con cuatro workers.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.models import User
from shared.data_api import keys as key_utils
from shared.data_api.models import ApiKey, ApiUsage
from shared.data_api.quota import check_quota, quota_period, record_usage
from shared.data_api.service import ApiKeyError, create_key, list_keys, revoke_key
from shared.database.base import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(
        engine, tables=[User.__table__, ApiKey.__table__, ApiUsage.__table__]
    )
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def user(db):
    u = User(email="pms@sdqconsulting.com.do", password_hash="x", full_name="SDQ-PMS")
    db.add(u)
    db.commit()
    return u


# ─── Acuñación y verificación ─────────────────────────────────────────


def test_minted_token_parses_and_verifies():
    minted = key_utils.mint_key()
    parsed = key_utils.parse_token(minted.token)
    assert parsed is not None
    env, prefix, secret = parsed
    assert env == "live"
    assert prefix == minted.prefix
    assert key_utils.verify_secret(secret, minted.secret_hash)


def test_secret_is_not_recoverable_from_what_we_store():
    minted = key_utils.mint_key()
    _env, _prefix, secret = key_utils.parse_token(minted.token)
    # Lo persistido es el hash: no contiene el secreto ni el token.
    assert secret not in minted.secret_hash
    assert minted.token not in minted.secret_hash
    assert len(minted.secret_hash) == 64


def test_two_keys_never_collide():
    assert len({key_utils.mint_key().prefix for _ in range(50)}) == 50


@pytest.mark.parametrize("bad", [
    "", "sdq_live_short_x", "nope", "sdq_prod_abcdefgh_" + "a" * 43,
    "sdq_live_abcdefgh_tooshort",
])
def test_malformed_tokens_are_rejected_before_touching_db(bad):
    assert key_utils.parse_token(bad) is None


def test_wrong_secret_does_not_verify():
    a, b = key_utils.mint_key(), key_utils.mint_key()
    _e, _p, secret_b = key_utils.parse_token(b.token)
    assert not key_utils.verify_secret(secret_b, a.secret_hash)


# ─── Alta / listado / revocación ──────────────────────────────────────


def test_create_key_returns_token_once_and_stores_only_hash(db, user):
    out = create_key(db, user_id=user.id, name="SDQ-PMS · producción",
                     client_ref="sdq-pms", quota_per_month=10_000)
    assert out["token"].startswith("sdq_live_")
    row = db.query(ApiKey).one()
    assert row.secret_hash and out["token"] not in row.secret_hash
    # El listado NUNCA vuelve a exponer el token.
    assert "token" not in list_keys(db)[0]


def test_create_key_rejects_nonsense(db, user):
    with pytest.raises(ApiKeyError):
        create_key(db, user_id=user.id, name="   ")
    with pytest.raises(ApiKeyError):
        create_key(db, user_id=user.id, name="ok", rate_limit_per_minute=0)
    with pytest.raises(ApiKeyError):
        create_key(db, user_id=user.id, name="ok", quota_per_month=0)


def test_revoke_marks_inactive(db, user):
    created = create_key(db, user_id=user.id, name="temporal")
    revoked = revoke_key(db, key_id=created["id"], revoked_by=user.id)
    assert revoked["active"] is False and revoked["revoked_at"]


# ─── Cuota ────────────────────────────────────────────────────────────


def _key(db, user, **kw):
    created = create_key(db, user_id=user.id, name="k", **kw)
    return db.query(ApiKey).filter(ApiKey.id == created["id"]).one()


def test_quota_allows_until_monthly_limit(db, user):
    key = _key(db, user, quota_per_month=3, rate_limit_per_minute=1000)
    for _ in range(3):
        assert check_quota(db, key).allowed
        record_usage(db, key, resource="series", status_code=200, rows=1)
    state = check_quota(db, key)
    assert not state.allowed and state.reason == "quota_exhausted"
    assert state.remaining_this_period == 0
    assert state.retry_after_seconds > 0


def test_rate_limit_trips_within_the_minute(db, user):
    key = _key(db, user, rate_limit_per_minute=2)
    for _ in range(2):
        record_usage(db, key, resource="catalog", status_code=200)
    state = check_quota(db, key)
    assert not state.allowed and state.reason == "rate_limit"


def test_old_calls_leave_the_rate_window(db, user):
    key = _key(db, user, rate_limit_per_minute=1)
    stale = datetime.now(timezone.utc) - timedelta(minutes=5)
    record_usage(db, key, resource="catalog", status_code=200, now=stale)
    # Fuera de la ventana de 60s: no debe contar contra el límite por minuto.
    assert check_quota(db, key).allowed


def test_rejected_calls_also_consume_quota(db, user):
    """Si el rechazo no contara, un cliente mal configurado martillaría gratis."""
    key = _key(db, user, quota_per_month=2, rate_limit_per_minute=1000)
    record_usage(db, key, resource="series", status_code=404)
    record_usage(db, key, resource="series", status_code=429)
    assert not check_quota(db, key).allowed


def test_no_monthly_quota_means_unlimited(db, user):
    key = _key(db, user, quota_per_month=None, rate_limit_per_minute=1000)
    for _ in range(20):
        record_usage(db, key, resource="catalog", status_code=200)
    state = check_quota(db, key)
    assert state.allowed and state.remaining_this_period is None


def test_usage_is_stamped_with_the_current_quota_period(db, user):
    key = _key(db, user)
    row = record_usage(db, key, resource="catalog", status_code=200)
    assert row.quota_period == quota_period()
    assert key.last_used_at is not None
