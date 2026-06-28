"""Tests for the pension cartera (Cuadro 6.1) extractor + persistence."""
import json
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from modules.pension_intel.external.cartera_extractor import (
    CarteraExtractionError,
    cartera_period,
    issuer_slug,
    parse_cartera_words,
)
from modules.pension_intel.cartera_sync import persist_cartera
from modules.pension_intel.models.models import PensionHolding

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "cartera_p31_words.json")


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()


def _real_words():
    with open(_FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


def test_issuer_slug_normalizes():
    assert issuer_slug("Banco de Reservas de la República Dominicana") == \
        "banco_de_reservas_de_la_republica_dominicana"
    assert issuer_slug("Ministerio de Hacienda") == "ministerio_de_hacienda"


def test_cartera_period_from_cutoff():
    assert cartera_period("... Al 31 de marzo de 2026 ...") == "2026-Q1"
    assert cartera_period("Al 30 de junio de 2025") == "2025-Q2"
    assert cartera_period("sin fecha") is None


def test_parse_real_cuadro_61_reconciles_and_maps_cross_keys():
    """The committed real Cuadro 6.1 (Q1-2026) parses, reconciles to TOTAL, and stamps
    the Macro cross-keys + structural sub-sectors — the headline cross-module figures."""
    holdings = parse_cartera_words(_real_words())
    by = {h.issuer_slug: h for h in holdings}

    # Public debt + BCRD: the Macro/BCRD gem, with deterministic cross-keys.
    hac = by["ministerio_de_hacienda"]
    assert hac.amount == pytest.approx(728_220_623_962.93, rel=1e-9)
    assert hac.pct == 56.04 and hac.macro_class == "deuda_publica"
    assert by["banco_central_de_la_republica_dominicana"].macro_class == "bcrd"

    # A group header is flagged subtotal; its child inherits the sub-sector and is a leaf.
    bm = by["bancos_multiples"]
    assert bm.is_subtotal is True
    res = by["banco_de_reservas_de_la_republica_dominicana"]
    assert res.is_subtotal is False and res.sub_sector == "Bancos Múltiples"
    # The split-digit amount ("3 2,027,…") is healed.
    assert res.amount == pytest.approx(32_027_246_695.76, rel=1e-9)

    # Sub-sectors are discovered structurally (incl. ones we never hardcoded).
    headers = {h.issuer for h in holdings if h.is_subtotal}
    assert {"Bancos Múltiples", "Fondos de Inversión",
            "Fideicomisos de Oferta Pública"} <= headers


def test_reconciliation_fails_closed():
    """If the leaves don't sum to TOTAL, extraction raises (never persists garbage)."""
    def row(top, name, amount_txt):
        return [
            {"text": name, "x0": 38.0, "x1": 120.0, "top": top},
            {"text": amount_txt, "x0": 250.0, "x1": 286.0, "top": top},
            {"text": "10.00%", "x0": 300.0, "x1": 315.0, "top": top},
        ]
    words = (row(10, "Emisor Uno", "100.00")
             + row(20, "Emisor Dos", "100.00")
             + row(30, "TOTAL", "999.00"))  # leaves=200 ≠ 999
    with pytest.raises(CarteraExtractionError):
        parse_cartera_words(words)


def test_persist_cartera_upserts_idempotently(db):
    holdings = parse_cartera_words(_real_words())
    n = persist_cartera(db, "2026-Q1", holdings)
    db.commit()
    assert n == len(holdings)
    assert db.query(PensionHolding).count() == len(holdings)

    # Second run: same rows, no duplicates.
    persist_cartera(db, "2026-Q1", holdings)
    db.commit()
    assert db.query(PensionHolding).count() == len(holdings)

    hac = (db.query(PensionHolding)
           .filter_by(period="2026-Q1", fund="cci", issuer_slug="ministerio_de_hacienda").one())
    assert hac.amount == pytest.approx(728_220_623_962.93, rel=1e-9)
    assert hac.macro_class == "deuda_publica" and hac.source == "SIPEN"
