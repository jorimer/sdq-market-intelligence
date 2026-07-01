"""Tests del valor cuota (NAV): extractor del boletín (Cuadro 6.4) + persistencia."""
import io
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from modules.pension_intel.models.models import PensionSeries
from modules.pension_intel.external.nav_extractor import parse_valor_cuota_text
from modules.pension_intel.nav_sync import VALOR_CUOTA_CODE, persist_valor_cuota

_FIX = Path(__file__).parent / "fixtures"
_ALL7 = {f"afp_{x}" for x in
         ["atlantico", "crecer", "jmmb_bdi", "popular", "reservas", "romana", "siembra"]}


def _text(num: int) -> str:
    return io.open(_FIX / f"boletin_{num}_valorcuota.txt", encoding="utf-8").read()


def test_parse_covers_seven_afps_with_periods():
    r = parse_valor_cuota_text(_text(91))
    assert set(r) == _ALL7
    # Q1 2026 → three monthly NAV points per AFP.
    assert [p for p, _ in r["afp_reservas"]] == ["2026-01", "2026-02", "2026-03"]


def test_parse_reservas_is_the_afp_not_banco_de_reservas():
    # The grid also lists "Banco de Reservas" (a non-AFP fund ~1,220); the AFP Reservas
    # (~1,300) must win — first-match ordering + skipping non-AFP labels.
    r = parse_valor_cuota_text(_text(91))
    navs = [v for _, v in r["afp_reservas"]]
    assert all(1250 < v < 1320 for v in navs), navs


def test_parse_disambiguates_nav_grid_from_return_grid():
    # The fixture tail includes the following %-return grid (values <10); the magnitude
    # guard must pick the NAV grid (hundreds-to-thousands), not the returns.
    r = parse_valor_cuota_text(_text(90))
    assert r["afp_crecer"][0][1] > 1000     # NAV level, not a 4% figure
    assert [p for p, _ in r["afp_atlantico"]] == ["2025-10", "2025-11", "2025-12"]


def test_parse_year_from_caption_not_base_footnote():
    # The "base 100 al 1 de octubre de 2003" footnote must NOT set the year.
    r = parse_valor_cuota_text(_text(91))
    assert all(p.startswith("2026-") for p, _ in r["afp_popular"])


def test_parse_empty_or_no_grid_is_empty():
    assert parse_valor_cuota_text("") == {}
    assert parse_valor_cuota_text("Trimestre enero - marzo de 2026 sin tabla") == {}


def test_persist_valor_cuota_upserts_monthly_series():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[PensionSeries.__table__])
    db = sessionmaker(bind=engine)()
    # ingest two consecutive bulletins → 6 monthly NAV points per AFP, no duplicates.
    for num in (90, 91):
        persist_valor_cuota(db, parse_valor_cuota_text(_text(num)))
    db.commit()
    reservas = (db.query(PensionSeries)
                .filter(PensionSeries.series_code == VALOR_CUOTA_CODE,
                        PensionSeries.entity_slug == "afp_reservas")
                .all())
    periods = sorted(r.period for r in reservas)
    assert periods == ["2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03"]
    assert all(r.frequency == "monthly" for r in reservas)
    # idempotent: re-ingesting the same bulletin doesn't duplicate rows.
    persist_valor_cuota(db, parse_valor_cuota_text(_text(91)))
    db.commit()
    assert (db.query(PensionSeries)
            .filter(PensionSeries.entity_slug == "afp_reservas").count()) == 6
    db.close()
