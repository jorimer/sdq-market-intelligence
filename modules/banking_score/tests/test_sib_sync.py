"""Tests for the SIB backfill/sync service (no network — stubbed client)."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from modules.banking_score import sib_sync
from modules.banking_score.models.models import (
    Bank,
    BankingData,
    BankType,
    DataSource,
    PeriodType,
    RatingResult,
)


@pytest.fixture()
def Session(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    # Make the service use this engine.
    monkeypatch.setattr(sib_sync, "SessionLocal", SessionLocal)
    # Hermetic by default: stub the SIMBAD fallback (it hits the live network).
    # The dedicated test below overrides it to exercise the fallback.
    monkeypatch.setattr(sib_sync, "extract_cambiaria_bulk", lambda **_: {"_entity_meta": {}})
    return SessionLocal


def _seed_popular(db):
    """One real bank (matches SIB short 'Popular') with synthetic data."""
    bank = Bank(name="Banco Popular Dominicano", bank_type=BankType.banca_multiple)
    db.add(bank)
    db.flush()
    db.add(BankingData(
        bank_id=bank.id, period_end=date(2024, 12, 31),
        source=DataSource.manual, activos_totales=100,
    ))
    db.commit()
    return bank


class _StubClient:
    def __init__(self):
        self.use_proxy = False

    def check_connectivity(self):
        return {"reachable": True, "status_code": 200}

    def get_working_tipos(self):
        return ["BM"]

    def extract_one_tipo(self, tipo, period_start="2021-01", on_progress=None, skip_carteras=False):
        if on_progress:  # exercise the heartbeat callback path
            on_progress("carteras 2024-12 (1/1)")
        return self.extract_all_entities_bulk(period_start=period_start)

    def extract_all_entities_bulk(self, period_start="2021-01"):
        return {
            "Popular": [
                {"period_end": date(2024, 12, 31), "period_type": "quarterly",
                 "source": "sib_api", "activos_totales": 999.0, "patrimonio_tecnico": 50.0},
                # Non-quarter-end → must be skipped.
                {"period_end": date(2024, 11, 30), "period_type": "monthly",
                 "source": "sib_api", "activos_totales": 5.0},
            ],
            "_unmatched": [],
            "_entity_names": [],
        }


def test_needs_backfill(Session):
    db = Session()
    _seed_popular(db)
    assert sib_sync.needs_backfill(db) is True


def test_stats(Session):
    db = Session()
    _seed_popular(db)
    s = sib_sync.bank_data_stats(db)
    assert s["entities"] == 1
    assert s["records"] == 1
    assert s["sib_records"] == 0
    assert s["period_end"] == "2024-12-31"


def test_backfill_replaces_with_real_data(Session, monkeypatch):
    db = Session()
    _seed_popular(db)
    monkeypatch.setattr(sib_sync, "get_sib_data_client", lambda force_new=False: _StubClient())

    result = sib_sync.run_backfill(force=True)
    assert result["status"] == "completed"
    assert result["entities_matched"] == 1
    assert result["periods_skipped_non_quarterly"] == 1  # the Nov row

    db2 = Session()
    row = db2.query(BankingData).filter_by(period_end=date(2024, 12, 31)).first()
    assert row.source == DataSource.sib_api
    assert float(row.activos_totales) == 999.0  # overwritten with real value
    bank = db2.query(Bank).filter_by(name="Banco Popular Dominicano").first()
    assert bank.sib_code == "BPD"  # populated from the SIB catalog


def test_backfill_auto_registers_catalogued_entity(Session, monkeypatch):
    """A SIB entity in the catalog but not in the DB is auto-created."""
    db = Session()
    other = Bank(name="Otro Banco", bank_type=BankType.banca_multiple)
    db.add(other)
    db.flush()
    db.add(BankingData(bank_id=other.id, period_end=date(2024, 12, 31), source=DataSource.manual))
    db.commit()
    monkeypatch.setattr(sib_sync, "get_sib_data_client", lambda force_new=False: _StubClient())

    result = sib_sync.run_backfill(force=True)
    assert result["status"] == "completed"
    assert result["entities_created"] >= 1  # Popular wasn't in the DB → created

    db2 = Session()
    popular = db2.query(Bank).filter_by(name="Banco Popular Dominicano").first()
    assert popular is not None
    assert popular.sib_code == "BPD"
    assert popular.bank_type == BankType.banca_multiple


def test_backfill_recalculates_ratings(Session, monkeypatch):
    """After ingesting SIB data, the backfill must compute and persist ratings
    (closes the gap where data landed but ratings stayed empty/stale)."""
    db = Session()
    _seed_popular(db)
    monkeypatch.setattr(sib_sync, "get_sib_data_client", lambda force_new=False: _StubClient())

    assert db.query(RatingResult).count() == 0  # no ratings before
    result = sib_sync.run_backfill(force=True)

    assert result["status"] == "completed"
    assert result["periods_scored"] == 1  # the 2024-12-31 quarter-end
    assert result["ratings_written"] == 1
    assert result["ratings_total"] == 1

    db2 = Session()
    rr = db2.query(RatingResult).filter_by(period_end=date(2024, 12, 31)).first()
    assert rr is not None
    assert 0 <= float(rr.overall_score) <= 100
    assert rr.ejecucion_score is not None and rr.resiliencia_score is not None


class _FutureQuarterClient(_StubClient):
    """SIB returns a closed quarter plus the in-progress (future) one."""

    def extract_all_entities_bulk(self, period_start="2021-01"):
        from datetime import timedelta
        future = date.today() + timedelta(days=200)
        # Normalize to a quarter-end month so it isn't skipped as non-quarterly.
        fq = date(future.year, ((future.month - 1) // 3) * 3 + 3, 1)
        # Move to a real quarter-end day (30/31) safely beyond today.
        fq = date(fq.year + (1 if fq <= date.today() else 0), 12, 31)
        return {
            "Popular": [
                {"period_end": date(2024, 12, 31), "period_type": "quarterly",
                 "source": "sib_api", "activos_totales": 999.0, "patrimonio_tecnico": 50.0},
                {"period_end": fq, "period_type": "quarterly",
                 "source": "sib_api", "activos_totales": 1.0},
            ],
            "_unmatched": [], "_entity_names": [],
        }


def test_backfill_skips_future_quarter(Session, monkeypatch):
    """The in-progress/future quarter must not be ingested or scored."""
    db = Session()
    _seed_popular(db)
    monkeypatch.setattr(sib_sync, "get_sib_data_client", lambda force_new=False: _FutureQuarterClient())

    result = sib_sync.run_backfill(force=True)
    assert result["status"] == "completed"
    assert result["periods_skipped_future"] >= 1

    db2 = Session()
    # No banking_data nor ratings for any future-dated period.
    fut = db2.query(BankingData).filter(BankingData.period_end > date.today()).count()
    fut_r = db2.query(RatingResult).filter(RatingResult.period_end > date.today()).count()
    assert fut == 0
    assert fut_r == 0


def test_prune_future_periods(Session):
    """prune_future_periods removes only future-dated rows."""
    from datetime import timedelta
    db = Session()
    bank = _seed_popular(db)
    future = date.today() + timedelta(days=120)
    db.add(BankingData(bank_id=bank.id, period_end=future, source=DataSource.sib_api))
    db.commit()
    assert db.query(BankingData).filter(BankingData.period_end > date.today()).count() == 1

    res = sib_sync.prune_future_periods(db)
    assert res["data_deleted"] == 1
    assert db.query(BankingData).filter(BankingData.period_end > date.today()).count() == 0
    # The closed-period row survives.
    assert db.query(BankingData).filter_by(period_end=date(2024, 12, 31)).count() == 1


def test_catalogued_entities_match_by_sib_code():
    """The 6 newly-catalogued SIB codes resolve to their catalog entry."""
    from modules.banking_score.external.sib_data_client import SIBDataClient
    for code in ("ATLANTICO", "COFACI", "OPTIMA", "EMPIRE", "ACTIVO", "REIDCO"):
        assert SIBDataClient._match_entity_name(code) is not None, code


def test_short_code_substring_does_not_misroute():
    """Regression: a short sib_code fragment must NOT substring-match an unrelated
    entity. Bonanza's code 'BON' once grabbed 'BONAO' (an AAP), routing Bonao's
    balance onto Bonanza. Substring matching is now restricted to full names."""
    from modules.banking_score.external.sib_data_client import SIBDataClient as C
    # Bonao resolves to its own catalog entry (added alongside the fix).
    assert C._match_entity_name("ASOC. BONAO DE AHORROS Y PRESTAMOS") == "Bonao"
    assert C._match_entity_name("BONAO") == "Bonao"
    # Real Bonanza still resolves to Bonanza via its full name.
    assert C._match_entity_name("BANCO DE AHORRO Y CREDITO BONANZA") == "Bonanza"
    # An unrelated name containing the fragment 'BON' must not be grabbed.
    assert C._match_entity_name("BONAVENTURA SRL") is None
    # The 'BON' code is still a valid EXACT key (just not a substring key).
    assert C._match_entity_name("BON") == "Bonanza"


def test_single_token_alias_does_not_swallow_longer_entity():
    """Regression: a bare single-token API alias (e.g. 'POPULAR' → Banco Popular)
    must NOT substring-match a longer, distinct entity whose full name merely
    contains that word. APAP's name 'ASOC. POPULAR DE AHORROS Y PRESTAMOS' embeds
    'POPULAR'; if APAP's exact match ever failed (SIB rename / feed variant), the
    old first-match substring loop would have misrouted APAP → Popular. Same class
    of defect as the historical Bonao→Bonanza bug (fix #148)."""
    from modules.banking_score.external.sib_data_client import SIBDataClient as C
    # Exact names still resolve correctly (baseline: matching is intact).
    assert C._match_entity_name("ASOC. POPULAR DE AHORROS Y PRESTAMOS") == "APAP"
    assert C._match_entity_name("BANCO POPULAR DOMINICANO") == "Popular"
    assert C._match_entity_name("POPULAR") == "Popular"
    # An APAP-like variant that does NOT hit the exact map must never fall through
    # to "Popular" via the bare 'POPULAR' fragment — a wrong route is worse than
    # None, so it resolves to APAP (its own full name) or to nothing, never Popular.
    for variant in (
        "ASOCIACION POPULAR DE AHORROS Y PRESTAMOS",   # 'ASOC.' spelled out
        "ASOC. POPULAR DE AHORROS Y PRESTAMOS, S.A.",  # trailing suffix
        "POPULAR DE AHORROS Y PRESTAMOS",              # abbreviated
    ):
        assert C._match_entity_name(variant) != "Popular", variant
    # The bare word is deliberately absent from the substring set (exact-only).
    assert "POPULAR" not in C._SUBSTRING_NAMES
    # BACC ('DEL CARIBE') must not be swallowed by the 'CARIBE' bank alias either.
    assert C._match_entity_name("BANCO DE AHORRO Y CREDITO DEL CARIBE") == "BACC"


def test_match_or_create_respects_active_flag(Session):
    """Exited entities are catalogued inactive; active ones stay active."""
    db = Session()
    active, created = sib_sync._match_or_create_bank(db, "Atlántico")
    assert created and active.is_active is True
    assert active.bank_type == BankType.banco_ahorro_credito

    defunct, created2 = sib_sync._match_or_create_bank(db, "Activo")
    assert created2 and defunct.is_active is False
    assert defunct.bank_type == BankType.banca_multiple


def test_cambiaria_auto_registers_via_meta(Session):
    """A cambiaria from the EIC feed (not in the static catalog) is auto-created
    with bank_type cambiaria using the per-run _entity_meta side-channel."""
    db = Session()
    meta = {"CARIBEEXPRESS": {"sib_code": "CARIBEEXPRESS", "tipo_entidad": "ARC",
                              "nombre": "Caribe Express (Remesas y Cambio)"}}
    bank, created = sib_sync._match_or_create_bank(db, "CARIBEEXPRESS", extra_codes=meta)
    assert created
    assert bank.bank_type == BankType.cambiaria
    assert bank.name == "Caribe Express (Remesas y Cambio)"
    assert bank.sib_code == "CARIBEEXPRESS"


def test_backfill_skipped_when_already_real(Session, monkeypatch):
    db = Session()
    bank = _seed_popular(db)
    # Mark existing data as already-SIB.
    db.query(BankingData).update({BankingData.source: DataSource.sib_api})
    db.commit()
    monkeypatch.setattr(sib_sync, "get_sib_data_client", lambda force_new=False: _StubClient())
    result = sib_sync.run_backfill(force=False)
    assert result["status"] == "skipped"


def test_backfill_errors_without_key(Session, monkeypatch):
    db = Session()
    _seed_popular(db)
    monkeypatch.setattr(sib_sync, "get_sib_data_client", lambda force_new=False: None)
    result = sib_sync.run_backfill(force=True)
    assert result["status"] == "error"
    assert "clave" in result["message"].lower() or "configur" in result["message"].lower()


def test_backfill_skips_duplicate_when_recent(Session):
    """A Celery re-delivery (acks_late) after a long run must NOT re-ingest:
    if a routine (force=False) backfill completed within the dedup window, the
    duplicate is skipped. An explicit admin force=True overrides the guard."""
    from datetime import datetime, timezone

    db = Session()
    sib_sync._write_status(
        db, is_running=False, backfill_done=True,
        last_sync=datetime.now(timezone.utc).isoformat(),
    )
    db.close()
    # Routine re-delivery (the real acks_late case) is force=False → skipped.
    result = sib_sync.run_backfill(force=False)
    assert result["status"] == "skipped_duplicate"


def test_backfill_force_overrides_dedup(Session, monkeypatch):
    """An explicit admin force=True must bypass the dedup guard and re-ingest."""
    from datetime import datetime, timezone
    db = Session()
    _seed_popular(db)
    sib_sync._write_status(db, is_running=False, backfill_done=True,
                           last_sync=datetime.now(timezone.utc).isoformat())
    db.close()
    monkeypatch.setattr(sib_sync, "get_sib_data_client", lambda force_new=False: _StubClient())
    result = sib_sync.run_backfill(force=True)
    assert result["status"] == "completed"  # not skipped_duplicate


def test_simbad_fallback_fills_gaps_and_respects_api_primary(Session, monkeypatch):
    """The SIMBAD fallback writes cambiaria (entity × quarter-end) the API didn't,
    tagged source=sib_simbad, and NEVER overwrites an existing (API) row."""
    db = Session()
    camb = Bank(name="Agc Existing (Agente de Cambio)", sib_code="AGCEXIST",
                bank_type=BankType.cambiaria)
    db.add(camb)
    db.flush()
    db.add(BankingData(bank_id=camb.id, period_end=date(2025, 9, 30),
                       source=DataSource.sib_api, period_type=PeriodType.quarterly,
                       activos_totales=999))
    db.commit()
    camb_id = camb.id

    # The SIMBAD cambiaria fallback only runs when the backfill includes a
    # cambiaria type (ARC/AC) — as a real full backfill always does.
    stub = _StubClient()
    monkeypatch.setattr(stub, "get_working_tipos", lambda: ["AC"])
    monkeypatch.setattr(sib_sync, "get_sib_data_client", lambda force_new=False: stub)
    monkeypatch.setattr(sib_sync, "extract_cambiaria_bulk", lambda **_: {
        "AGCEXIST": [
            {"period_end": date(2025, 9, 30), "activos_totales": 111},   # exists (API) → keep
            {"period_end": date(2025, 12, 31), "activos_totales": 222},  # new → fill from SIMBAD
        ],
        "_entity_meta": {"AGCEXIST": {"sib_code": "AGCEXIST", "tipo_entidad": "AC",
                                      "nombre": "Agc Existing (Agente de Cambio)"}},
    })
    sib_sync.run_backfill(force=True)

    db2 = Session()
    sep = db2.query(BankingData).filter_by(bank_id=camb_id, period_end=date(2025, 9, 30)).first()
    dec = db2.query(BankingData).filter_by(bank_id=camb_id, period_end=date(2025, 12, 31)).first()
    assert sep is not None and sep.source == DataSource.sib_api and float(sep.activos_totales) == 999
    assert dec is not None and dec.source == DataSource.sib_simbad and float(dec.activos_totales) == 222


def test_only_tipos_targeted_reingest_skips_simbad(Session, monkeypatch):
    """A targeted re-ingest (only_tipos without a cambiaria type) ingests the
    requested type and does NOT invoke the SIMBAD cambiaria fallback."""
    db = Session()

    class _MultiTipoStub(_StubClient):
        seen: list = []

        def get_working_tipos(self):
            return ["BM", "BAC", "AAP", "AC"]

        def extract_one_tipo(self, tipo, period_start="2021-01", on_progress=None, skip_carteras=False):
            _MultiTipoStub.seen.append(tipo)
            return self.extract_all_entities_bulk(period_start=period_start)

    _MultiTipoStub.seen = []
    monkeypatch.setattr(sib_sync, "get_sib_data_client", lambda force_new=False: _MultiTipoStub())

    def _boom(**_):
        raise AssertionError("SIMBAD fallback must not run for a non-cambiaria targeted re-ingest")
    monkeypatch.setattr(sib_sync, "extract_cambiaria_bulk", _boom)

    res = sib_sync.run_backfill(force=True, only_tipos=["AAP"])
    assert res["status"] == "completed"
    # Only the requested type was extracted (BM/BAC/AC skipped).
    assert _MultiTipoStub.seen == ["AAP"]


def test_prune_partial_latest_quarter_drops_incomplete_quarter(Session):
    """A just-closed quarter the SIB has only partially published (few filers) is
    pruned; the prior complete quarter is kept."""
    db = Session()
    complete, partial = date(2026, 3, 31), date(2026, 6, 30)
    banks = [Bank(name=f"Banco {i}", bank_type=BankType.banca_multiple) for i in range(4)]
    for b in banks:
        db.add(b)
    db.flush()
    for b in banks:  # complete quarter: all 4 entities
        db.add(BankingData(bank_id=b.id, period_end=complete, source=DataSource.sib_api))
    db.add(BankingData(bank_id=banks[0].id, period_end=partial,  # partial: 1 of 4 (< 50%)
                       source=DataSource.sib_api))
    db.commit()

    res = sib_sync.prune_partial_latest_quarter(db)

    assert str(partial) in res["periods"]
    assert res["data_deleted"] == 1
    remaining = {d.period_end for d in db.query(BankingData).all()}
    assert partial not in remaining and complete in remaining


def test_prune_partial_latest_quarter_keeps_complete_quarter(Session):
    """A latest quarter with full coverage is never pruned."""
    db = Session()
    banks = [Bank(name=f"B{i}", bank_type=BankType.banca_multiple) for i in range(4)]
    for b in banks:
        db.add(b)
    db.flush()
    for pe in (date(2026, 3, 31), date(2026, 6, 30)):
        for b in banks:
            db.add(BankingData(bank_id=b.id, period_end=pe, source=DataSource.sib_api))
    db.commit()

    res = sib_sync.prune_partial_latest_quarter(db)

    assert res["periods"] == []
    assert db.query(BankingData).filter(BankingData.period_end == date(2026, 6, 30)).count() == 4
