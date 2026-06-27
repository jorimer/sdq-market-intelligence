"""Tests for the AFP estados-financieros ingest → ISA solvency activation.

The AI extractor is mocked (no network/Claude); the field mapping (reused from banking)
and the ISA wiring run for real — proving that ingesting financials turns the solvency
dimension present and graduates the AFP from a relative score to an ABSOLUTE band.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from modules.pension_intel import financials_sync
from modules.pension_intel.financials_sync import discover_ef_links, ingest_financials
from modules.pension_intel.models.models import PensionSeries
from modules.pension_intel.scoring.isa import compute_isa
from modules.pension_intel.sipen_sync import sipen_pension_sync

# A realistic extractor output (same shape AuditedPdfExtractor returns).
_STATEMENTS = {
    "company_info": {"name": "AFP Popular", "period_end": "2024-12-31", "currency": "DOP"},
    "balance_general": [
        {"original_text": "Total activos", "category": "assets", "amount_current": 5000.0, "is_total": True},
        {"original_text": "Total pasivos", "category": "liabilities", "amount_current": 1000.0, "is_total": True},
        {"original_text": "Total patrimonio", "category": "equity", "amount_current": 4000.0, "is_total": True},
    ],
    "estado_resultados": [
        {"original_text": "Resultado del ejercicio", "category": "net_income", "amount_current": 800.0, "is_total": True},
    ],
}


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autoflush=False)()
    sipen_pension_sync(s)  # base data (rentabilidad/escala/costo per AFP)
    try:
        yield s
    finally:
        s.close()


def test_ingest_financials_persists_and_activates_solvency(db, monkeypatch):
    monkeypatch.setattr(financials_sync, "extract_financials", lambda c, f: _STATEMENTS)

    # Before: Popular has no solvency → relative/partial, no band.
    before = {r["slug"]: r for r in compute_isa(db)}["afp_popular"]
    assert before["band"] is None and before["score_kind"] == "relative_partial"

    res = ingest_financials(db, "afp_popular", b"%PDF-fake", "afp_popular_2024.pdf")
    assert res["period"] == "2024-12"
    assert res["patrimonio"] == 4000.0 and res["activos_totales"] == 5000.0

    # Series persisted.
    pat = (db.query(PensionSeries)
           .filter_by(entity_slug="afp_popular", series_code="patrimonio", period="2024-12").one())
    assert pat.value == 4000.0 and pat.source == "SIPEN"

    # After: Popular's solvency dimension is present → it graduates to an ABSOLUTE band.
    after = {r["slug"]: r for r in compute_isa(db)}["afp_popular"]
    solv = next(d for d in after["dimensions"] if d["key"] == "solvencia")
    assert solv["present"] is True and solv["raw"] == pytest.approx(0.8)  # 4000/5000
    assert after["band"] is not None and after["score_kind"] == "absolute"
    assert after["coverage"] == pytest.approx(1.0)  # all four dimensions present


def test_ingest_rejects_unknown_afp(db, monkeypatch):
    monkeypatch.setattr(financials_sync, "extract_financials", lambda c, f: _STATEMENTS)
    with pytest.raises(ValueError, match="AFP desconocida"):
        ingest_financials(db, "afp_inexistente", b"x", "x.pdf")


def test_ingest_rejects_empty_extraction(db, monkeypatch):
    empty = {"company_info": {"period_end": "2024-12-31"}, "balance_general": [], "estado_resultados": []}
    monkeypatch.setattr(financials_sync, "extract_financials", lambda c, f: empty)
    with pytest.raises(ValueError, match="patrimonio ni activos"):
        ingest_financials(db, "afp_popular", b"x", "x.pdf")


def test_discover_ef_links_parses_descarga_pattern():
    html = """
      <a href="/descarga/estados-financieros-afp_2024_12_20250115101010.pdf">EF dic 2024</a>
      <a href="/descarga/estados-financieros-afp_2024_09_20241015101010.xlsx">EF sep 2024</a>
      <a href="/descarga/otra-cosa_2024_12_x.pdf">no</a>
    """
    links = discover_ef_links(html)
    periods = [p for p, _ in links]
    assert "2024-12" in periods and "2024-09" in periods
    assert all("estados-financieros" in u for _, u in links)
    assert all(u.startswith("https://www.sipen.gob.do/descarga/") for _, u in links)
