"""Tests del retorno real (Fase 5): deflactación por inflación BCRD, neutral al ISA."""
import pytest

from modules.pension_intel.scoring.real_return import (
    deflate_trend, fisher_real, inflation_at)
from modules.pension_intel.products import _apply_real_return


def test_fisher_real():
    # (1+0.094)/(1+0.0535)-1 = 0.03843... → 3.84%
    assert fisher_real(9.4, 5.35) == pytest.approx(3.84, abs=0.01)
    # inflación == nominal → real ≈ 0
    assert fisher_real(5.0, 5.0) == pytest.approx(0.0, abs=0.001)
    # nominal < inflación → real negativo
    assert fisher_real(3.0, 6.0) < 0


def test_inflation_at_exact_and_carry_forward():
    infl = {"2024-12": 3.5, "2025-03": 4.1, "2025-06": 5.35}
    assert inflation_at(infl, "2025-06") == 5.35            # exacto
    assert inflation_at(infl, "2025-05") == 4.1             # carry-forward al previo
    assert inflation_at(infl, "2025-01") == 3.5
    assert inflation_at(infl, "2023-01") is None            # nada anterior
    assert inflation_at({}, "2025-06") is None


def test_inflation_at_quarterly_period():
    infl = {"2025-03": 4.1, "2025-06": 5.0}
    # Q1 termina en mes 3 → toma 2025-03
    assert inflation_at(infl, "2025-Q1") == 4.1
    assert inflation_at(infl, "2025-Q2") == 5.0


def test_deflate_trend_skips_missing_inflation():
    trend = [("2025-04", 9.0), ("2025-05", 9.2), ("2025-06", 9.4)]
    infl = {"2025-05": 5.0, "2025-06": 5.35}  # falta 2025-04 y nada anterior
    out = deflate_trend(trend, infl)
    # 2025-04 se omite (sin inflación aplicable); 05 y 06 sí
    assert [p for p, _, _ in out] == ["2025-05", "2025-06"]
    assert out[-1][1] == 9.4 and out[-1][2] == pytest.approx(fisher_real(9.4, 5.35))
    assert deflate_trend(trend, {}) == []


def test_apply_real_return_enriches_without_touching_score():
    rating = {
        "period": "2025-06",
        "dimensions": [
            {"key": "rentabilidad", "label": "Rentabilidad", "raw": 9.4, "score": 51.6,
             "weight": 0.30, "present": True, "direction": "higher", "provenance": "real"},
            {"key": "costo", "label": "Costo", "raw": 0.65, "score": 68.0,
             "weight": 0.15, "present": True, "direction": "lower", "provenance": "real"},
        ],
    }
    trend = [("2025-05", 9.2), ("2025-06", 9.4)]
    infl = {"2025-05": 5.0, "2025-06": 5.35}
    extra = _apply_real_return(rating, trend, infl)
    rdim = rating["dimensions"][0]
    # score INTACTO (deflactar es neutral al min-max)
    assert rdim["score"] == 51.6
    # dimensión enriquecida con real + inflación
    assert rdim["raw_real"] == pytest.approx(fisher_real(9.4, 5.35), abs=0.01)
    assert rdim["inflacion"] == 5.35
    assert extra["inflacion_actual"] == 5.35
    assert len(extra["trend_real"]) == 2
    assert extra["trend_real"][-1][2] == pytest.approx(fisher_real(9.4, 5.35), abs=0.01)


def test_apply_real_return_no_inflation_leaves_nominal():
    rating = {"period": "2025-06", "dimensions": [
        {"key": "rentabilidad", "raw": 9.4, "score": 51.6}]}
    extra = _apply_real_return(rating, [("2025-06", 9.4)], {})
    assert "raw_real" not in rating["dimensions"][0]
    assert extra == {}


def test_inflation_series_producer_to_consumer_roundtrip():
    """macro_monitor persiste la serie; pension_intel la lee vía shared.contracts —
    sin importar el módulo productor ni tocar mm_series."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from shared.database.base import Base
    from shared.settings.models import AppSetting
    from shared.contracts import INFLATION_SERIES_CODE, load_inflation_series
    from modules.macro_monitor.service import _persist_inflation_series

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[AppSetting.__table__])
    db = sessionmaker(bind=engine)()

    grouped = {INFLATION_SERIES_CODE: [("2025-05", 5.0), ("2025-06", 5.35), ("2025-07", None)]}
    _persist_inflation_series(db, grouped)
    loaded = load_inflation_series(db)
    assert loaded == {"2025-05": 5.0, "2025-06": 5.35}  # null dropped
    # ausencia de serie → no escribe payload vacío (no-op), loader devuelve {}
    _persist_inflation_series(db, {})  # sin la serie
    assert load_inflation_series(db) == {"2025-05": 5.0, "2025-06": 5.35}  # intacto
