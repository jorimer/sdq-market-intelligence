"""Banca legacy (SDQ Rating / full_rating): la narrativa degradada NO produce un reporte
entregable.

Superficie distinta al framework ``shared/products``: es la ÚNICA que marca
``ReportStatus.completed`` en la DB. El endpoint ``generate_report`` es una función async
plana (recibe ``db``/``current_user`` por parámetro), así que se maneja directo con una DB
en memoria y mocks — sin levantar la app.
"""
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.narrative.claude_engine import STATIC_FALLBACK_GENERIC
from modules.banking_score.api import router_reports as rr
from modules.banking_score.models.models import (
    Bank,
    BankType,
    RatingResult,
    Report,
    ReportStatus,
)
from modules.banking_score.reports.narrative import REPORT_SECTIONS


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(
        engine, tables=[Bank.__table__, RatingResult.__table__, Report.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


class _User:
    id = "user-1"


def _seed(db):
    pe = date(2025, 3, 31)
    bank = Bank(name="Banco Prueba", bank_type=BankType.banca_multiple)
    db.add(bank)
    db.flush()
    db.add(RatingResult(bank_id=bank.id, period_end=pe, overall_score=72.5,
                        rating_tier="A"))
    db.commit()
    return bank.id, pe


def _patch_common(monkeypatch):
    """sib benchmarks vacíos; el render se marca para detectar si se invocó indebidamente."""
    import modules.banking_score.external.sib_client as sc

    monkeypatch.setattr(sc.sib_client, "get_sector_benchmarks", lambda: {}, raising=False)


def test_full_rating_with_degraded_narrative_is_not_completed(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(
        engine, tables=[Bank.__table__, RatingResult.__table__, Report.__table__])
    db = sessionmaker(bind=engine)()
    bank_id, pe = _seed(db)
    _patch_common(monkeypatch)

    async def _degraded_narratives(**kwargs):
        return {s: STATIC_FALLBACK_GENERIC for s in REPORT_SECTIONS["full_rating"]}

    # El render NO debe llamarse: el gate aborta antes. Si se llama, el test falla.
    import modules.banking_score.reports.pdf_generator as pg

    async def _boom_pdf(**kwargs):
        raise AssertionError("generate_pdf_report no debe invocarse con narrativa degradada")

    monkeypatch.setattr(
        "modules.banking_score.reports.narrative.generate_report_narratives",
        _degraded_narratives)
    monkeypatch.setattr(pg, "generate_pdf_report", _boom_pdf)

    import asyncio
    with pytest.raises(HTTPException) as ei:
        asyncio.run(rr.generate_report(
            bank_id=bank_id, period_end=str(pe), report_type="full_rating",
            db=db, current_user=_User()))
    assert ei.value.status_code == 503

    report = db.query(Report).filter_by(bank_id=bank_id).one()
    assert report.status == ReportStatus.error            # NO completed
    assert report.status != ReportStatus.completed
    assert report.completed_at is None
    assert report.narrative_model == "static_fallback"
    db.close()


def test_full_rating_with_healthy_narrative_completes(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(
        engine, tables=[Bank.__table__, RatingResult.__table__, Report.__table__])
    db = sessionmaker(bind=engine)()
    bank_id, pe = _seed(db)
    _patch_common(monkeypatch)

    async def _healthy(**kwargs):
        return {s: f"Análisis real y sustantivo de {s}." for s in REPORT_SECTIONS["full_rating"]}

    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(b"%PDF-1.4 contenido real")

    async def _ok_pdf(**kwargs):
        return str(pdf)

    monkeypatch.setattr(
        "modules.banking_score.reports.narrative.generate_report_narratives", _healthy)
    monkeypatch.setattr(
        "modules.banking_score.reports.pdf_generator.generate_pdf_report", _ok_pdf)

    import asyncio
    out = asyncio.run(rr.generate_report(
        bank_id=bank_id, period_end=str(pe), report_type="full_rating",
        db=db, current_user=_User()))
    assert out["status"] == ReportStatus.completed.value

    report = db.query(Report).filter_by(bank_id=bank_id).one()
    assert report.status == ReportStatus.completed
    assert report.narrative_model == "claude"
    db.close()
