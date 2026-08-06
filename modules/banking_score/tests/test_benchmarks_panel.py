"""Benchmarks MEDIDOS del panel, del MISMO corte del informe.

Hallazgo 2026-08-06, verificado en prod sobre los 16 bancos múltiples: BPD al Q1-2026 tiene
ROE 10.2%. Contra la constante ANUAL de banca grande (20.1%) el informe concluía "rezago
material en rentabilidad" (−9.9 pp) y lo presentaba como su debilidad principal. Contra la
mediana Q1 de su propio grupo (3.85%) BPD es el MÁS RENTABLE de los 16 (+6.35 pp).

La misma cifra, dos bases, conclusiones opuestas. No se suprime el indicador por dar un
número desfavorable —eso habría borrado la señal Y dejado el error—: se compara el mismo
corte a ambos lados, con lo que la estacionalidad se cancela y además queda visible.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.auth.models import User  # noqa: F401 — registra la tabla para la FK
from modules.banking_score.models.models import Bank, BankType, ModelType, RatingResult
from modules.banking_score.scoring.benchmarks import MIN_N, panel_benchmarks


@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _bank(db, name, btype, period, roe, mora=2.0):
    b = Bank(name=name, bank_type=btype)
    db.add(b)
    db.flush()
    db.add(RatingResult(
        bank_id=b.id, period_end=period, overall_score=70.0, rating_tier="SDQ-A",
        model_type=ModelType.deterministic,
        indicator_details={"roe": {"raw": roe, "score": 50.0, "available": True},
                           "morosidad": {"raw": mora, "score": 50.0, "available": True}},
    ))
    db.commit()
    return b


def _panel(db, period, roes, btype=BankType.banca_multiple, pref="B"):
    for i, r in enumerate(roes):
        _bank(db, f"{pref}{i}", btype, period, r)


def test_mide_el_panel_del_periodo_pedido(db):
    """Q1 se compara contra Q1: si el sistema entero cae en Q1, la caída se cancela."""
    _panel(db, date(2026, 3, 31), [10.2, 9.9, 9.5, 7.6, 6.9, 6.5])      # Q1: todos bajos
    _panel(db, date(2025, 12, 31), [24.2, 42.7, 21.4, 16.4, 16.7, 16.4], pref="C")

    q1 = panel_benchmarks(db, date(2026, 3, 31))
    q4 = panel_benchmarks(db, date(2025, 12, 31))
    assert q1["sector_averages"]["roe"] == pytest.approx(8.55, abs=0.05)
    assert q4["sector_averages"]["roe"] == pytest.approx(19.05, abs=0.2)
    assert q1["procedencia"]["medido"] is True
    assert q1["procedencia"]["period"] == "2026-03-31"


def test_la_conclusion_se_invierte_segun_la_base(db):
    """El caso real: contra su grupo en el MISMO corte, la entidad lidera."""
    _panel(db, date(2026, 3, 31), [10.2, 9.9, 9.5, 7.6, 6.9, 3.4, 3.0, 0.1])
    med = panel_benchmarks(db, date(2026, 3, 31))["sector_averages"]["roe"]
    bpd = 10.2
    assert bpd > med, "contra el corte propio, la entidad está POR ENCIMA"
    assert bpd < 20.1, "contra la constante ANUAL parecía muy por debajo"


def test_usa_mediana_no_media(db):
    """Un extremo real (sucursal extranjera con ROE 42%) no debe mandar el benchmark."""
    _panel(db, date(2026, 3, 31), [5.0, 5.0, 5.0, 5.0, 5.0, 100.0])
    assert panel_benchmarks(db, date(2026, 3, 31))["sector_averages"]["roe"] == 5.0


def test_grupos_de_pares_derivados_del_catalogo(db):
    _panel(db, date(2026, 3, 31), [10.0] * MIN_N, BankType.banca_multiple, "M")
    _panel(db, date(2026, 3, 31), [2.0] * MIN_N, BankType.cambiaria, "X")
    g = panel_benchmarks(db, date(2026, 3, 31))["peer_groups"]
    assert g["banca_multiple"]["roe_avg"] == 10.0
    assert g["cambiaria"]["roe_avg"] == 2.0
    assert g["banca_multiple"]["label"] == "bancos múltiples"
    assert g["banca_multiple"]["n"] == MIN_N


def test_sin_observaciones_suficientes_no_se_publica(db):
    """Nunca fabrica: bajo el mínimo, ese promedio no sale."""
    _panel(db, date(2026, 3, 31), [10.0] * (MIN_N - 1))
    out = panel_benchmarks(db, date(2026, 3, 31))
    assert out["procedencia"]["medido"] is False


def test_sin_panel_declara_la_procedencia(db):
    out = panel_benchmarks(db, date(2020, 12, 31))
    assert out["procedencia"]["medido"] is False
    assert "DECLARADA" in out["procedencia"]["nota"]
    assert out["sector_averages"]["roe"] == 18.5   # cae a la constante, pero DECLARADA


def test_los_limites_regulatorios_siguen_declarados(db):
    """Son mínimos normativos del regulador, no un promedio observable del panel."""
    _panel(db, date(2026, 3, 31), [10.0] * MIN_N)
    out = panel_benchmarks(db, date(2026, 3, 31))
    assert out["regulatory_limits"]["car_minimum"] == 10.0


def test_sin_periodo_no_revienta(db):
    assert panel_benchmarks(db, None)["procedencia"]["medido"] is False
