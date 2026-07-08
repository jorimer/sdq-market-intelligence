"""Tests del track record EN VIVO (ledger): snapshot, puntuación y métricas acumuladas."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor.comunicados.models import ComunicadoTPM
from modules.macro_monitor.tpm_modeling import ledger
from modules.macro_monitor.tpm_modeling import service as tpm_service
from modules.macro_monitor.tpm_modeling.models import TpmForecastLog


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    from shared.database.base import Base
    Base.metadata.create_all(engine, tables=[TpmForecastLog.__table__, ComunicadoTPM.__table__])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _decision(db, article_id, date, action, level, status="ok"):
    db.add(ComunicadoTPM(article_id=article_id, decision_date=date, action=action,
                         tpm_level=level, status=status, title="t", source_url="u"))
    db.commit()


def _pending(db, as_of, probs, predicted, implied=None, tpm_vigente=None):
    row = TpmForecastLog(as_of=as_of, status="pending", model_version="v1",
                         prob_cut=probs.get("cut"), prob_hold=probs.get("hold"),
                         prob_hike=probs.get("hike"), predicted_action=predicted,
                         implied_rate=implied, tpm_vigente=tpm_vigente)
    db.add(row)
    db.commit()
    return row


# ── Brier ─────────────────────────────────────────────────────────
def test_brier_score():
    assert ledger._brier({"cut": 0.0, "hold": 1.0, "hike": 0.0}, "hold") == pytest.approx(0.0)
    # {cut .6, hold .4} realizado cut → (.6-1)²+.4²+0² = .16+.16 = .32
    assert ledger._brier({"cut": 0.6, "hold": 0.4, "hike": 0.0}, "cut") == pytest.approx(0.32)
    assert ledger._brier(None, "hold") is None


# ── score_pending ─────────────────────────────────────────────────
def test_score_pending_matches_next_decision_and_scores(db):
    _pending(db, "2026-05-01", {"cut": 0.1, "hold": 0.2, "hike": 0.7}, "hike",
             implied=5.30, tpm_vigente=5.00)
    _decision(db, 100, "2026-05-30", "hike", 5.25)  # decisión posterior al pronóstico

    res = ledger.score_pending(db)
    assert res["scored"] == 1
    row = db.query(TpmForecastLog).one()
    assert row.status == "scored"
    assert row.realized_action == "hike" and row.matched_article_id == 100
    assert row.correct is True
    assert row.brier == pytest.approx(0.1**2 + 0.2**2 + (0.7 - 1) ** 2)
    assert row.level_abs_error == pytest.approx(abs(5.30 - 5.25))


def test_score_pending_ignores_decision_before_forecast(db):
    _pending(db, "2026-05-15", {"cut": 0.1, "hold": 0.8, "hike": 0.1}, "hold")
    _decision(db, 101, "2026-05-01", "cut", 5.00)  # anterior al pronóstico → no casa
    assert ledger.score_pending(db)["scored"] == 0
    assert db.query(TpmForecastLog).one().status == "pending"


def test_score_pending_no_double_count(db):
    # Dos pendientes previos a la MISMA (única) decisión → solo uno la puede reclamar.
    _pending(db, "2026-04-01", {"cut": 0.1, "hold": 0.8, "hike": 0.1}, "hold")
    _pending(db, "2026-04-20", {"cut": 0.1, "hold": 0.1, "hike": 0.8}, "hike")
    _decision(db, 102, "2026-05-01", "hold", 5.00)
    res = ledger.score_pending(db)
    assert res["scored"] == 1
    scored = db.query(TpmForecastLog).filter_by(status="scored").all()
    assert len(scored) == 1 and scored[0].matched_article_id == 102


def test_score_pending_correct_false_on_miss(db):
    _pending(db, "2026-05-01", {"cut": 0.7, "hold": 0.2, "hike": 0.1}, "cut")
    _decision(db, 103, "2026-05-30", "hold", 5.00)
    ledger.score_pending(db)
    assert db.query(TpmForecastLog).one().correct is False


# ── snapshot_forecast ─────────────────────────────────────────────
def _fake_forecast(has_model=True):
    return {
        "has_model": has_model, "version": "v9", "as_of": "2026-07-08", "tpm_vigente": 5.25,
        "clasificador": {"probabilidades": {"cut": 0.01, "hold": 0.64, "hike": 0.35},
                         "decision_mas_probable": "hold"},
        "regla_taylor": {"tasa_implicita": 5.30, "sesgo_pp": 0.05},
        "features_point_in_time": {"inflation_gap": 1.35},
    }


def test_snapshot_creates_and_refreshes_single_pending(db, monkeypatch):
    monkeypatch.setattr(tpm_service, "get_forecast", lambda _db: _fake_forecast())
    r1 = ledger.snapshot_forecast(db)
    assert r1["snapshotted"] is True and r1["refreshed"] is False
    assert db.query(TpmForecastLog).filter_by(status="pending").count() == 1

    # Segundo snapshot: refresca el mismo pendiente (sigue habiendo uno solo).
    r2 = ledger.snapshot_forecast(db)
    assert r2["refreshed"] is True
    assert db.query(TpmForecastLog).filter_by(status="pending").count() == 1
    row = db.query(TpmForecastLog).one()
    assert row.predicted_action == "hold" and row.prob_hold == pytest.approx(0.64)


def test_snapshot_skips_when_model_untrained(db, monkeypatch):
    monkeypatch.setattr(tpm_service, "get_forecast", lambda _db: _fake_forecast(has_model=False))
    assert ledger.snapshot_forecast(db)["snapshotted"] is False
    assert db.query(TpmForecastLog).count() == 0


# ── track_record ──────────────────────────────────────────────────
def test_track_record_aggregates(db, monkeypatch):
    monkeypatch.setattr(tpm_service, "get_backtest", lambda _db: {"has_backtest": False})
    # Dos aciertos y un fallo.
    _pending(db, "2026-01-01", {"cut": 0.1, "hold": 0.8, "hike": 0.1}, "hold")
    _decision(db, 200, "2026-01-30", "hold", 5.0)
    _pending(db, "2026-02-01", {"cut": 0.1, "hold": 0.1, "hike": 0.8}, "hike")
    _decision(db, 201, "2026-02-28", "hike", 5.25)
    _pending(db, "2026-03-01", {"cut": 0.7, "hold": 0.2, "hike": 0.1}, "cut")
    _decision(db, 202, "2026-03-30", "hold", 5.25)
    ledger.score_pending(db)
    # Un pendiente vigente sin decisión aún.
    _pending(db, "2026-04-01", {"cut": 0.2, "hold": 0.7, "hike": 0.1}, "hold")

    tr = ledger.track_record(db)
    assert tr["has_data"] is True
    assert tr["n_scored"] == 3
    assert tr["hit_rate"] == pytest.approx(2 / 3)
    assert tr["brier_medio"] is not None
    assert tr["per_class"]["hike"]["recall"] == pytest.approx(1.0)
    assert tr["per_class"]["hold"]["support"] == 2
    assert tr["confusion_matrix"]["labels"] == ["cut", "hold", "hike"]
    assert tr["pronostico_vigente"]["decision_pronosticada"] == "hold"
    assert len(tr["caveats"]) >= 1


def test_track_record_empty(db, monkeypatch):
    monkeypatch.setattr(tpm_service, "get_backtest", lambda _db: {"has_backtest": False})
    tr = ledger.track_record(db)
    assert tr["has_data"] is False
    assert tr["n_scored"] == 0
    assert tr["hit_rate"] is None
