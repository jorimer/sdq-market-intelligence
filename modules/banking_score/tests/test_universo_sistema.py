"""El universo del "Sistema Bancario" es canónico y se DECLARA en el informe.

Dos reportes "Sistema Bancario" del mismo período (2026-03-31), generados el mismo día,
mostraban adecuación de capital 16,5% vs 18,07%, ROE 18,5% vs 6,16% y eficiencia 48-55% vs
77,85-86,93%. No cambió el cálculo: cambió la POBLACIÓN — los promedios se computaron sobre
las 89 supervisadas en vez del universo estrecho anterior.

Decisión del dueño: el universo canónico son las INSTITUCIONES DE CRÉDITO (opción B). Y el
informe debe declararlo en el cuerpo, porque elegir bien el universo no basta si el lector
no sabe cuál es.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.auth.models import User  # noqa: F401 — registra la tabla para la FK
from modules.banking_score.models.models import Bank, BankType, ModelType, RatingResult
from modules.banking_score.reports.narrative import _build_system_context
from modules.banking_score.scoring.benchmarks import (
    MIN_N, SISTEMA_TIPOS, panel_benchmarks,
)

PER = date(2026, 3, 31)


@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _seed(db, btype, n, roe, pref):
    for i in range(n):
        b = Bank(name=f"{pref}{i}", bank_type=btype)
        db.add(b)
        db.flush()
        db.add(RatingResult(
            bank_id=b.id, period_end=PER, overall_score=70.0, rating_tier="SDQ-A",
            model_type=ModelType.deterministic,
            indicator_details={"roe": {"raw": roe, "score": 50.0, "available": True}}))
    db.commit()


def test_los_agentes_de_cambio_no_entran_al_sistema(db):
    """No captan depósitos ni tienen libro de crédito: no son 'el sistema'."""
    _seed(db, BankType.banca_multiple, MIN_N, 12.0, "M")
    _seed(db, BankType.cambiaria, 40, 2.0, "X")     # 40 agentes arrastrarían la mediana
    out = panel_benchmarks(db, PER)
    assert out["sector_averages"]["roe"] == 12.0, "la mediana es la de crédito, no la del padrón"
    assert out["procedencia"]["n_sistema"] == MIN_N
    assert out["procedencia"]["n_supervisadas"] == MIN_N + 40


def test_las_instituciones_de_credito_si_entran(db):
    """AAyP y ahorro y crédito SON parte del sistema, aunque bajen la mediana: es el dato."""
    _seed(db, BankType.banca_multiple, 3, 12.0, "M")
    _seed(db, BankType.aap, 3, 6.0, "A")
    out = panel_benchmarks(db, PER)
    assert out["procedencia"]["n_sistema"] == 6
    assert set(out["procedencia"]["composicion"]) == {"banca_multiple", "aap"}


def test_el_universo_canonico_es_el_decidido():
    assert SISTEMA_TIPOS == {"banca_multiple", "aap", "banco_ahorro_credito",
                             "corporacion_credito"}


def test_los_grupos_de_pares_siguen_cubriendo_todos_los_tipos(db):
    """El agregado es de crédito, pero una cambiaria debe encontrar SU grupo."""
    _seed(db, BankType.banca_multiple, MIN_N, 12.0, "M")
    _seed(db, BankType.cambiaria, MIN_N, 2.0, "X")
    assert "cambiaria" in panel_benchmarks(db, PER)["peer_groups"]


def test_el_informe_declara_el_universo(db):
    """Sin decirlo en el CUERPO, dos lectores comparan poblaciones distintas sin saberlo."""
    _seed(db, BankType.banca_multiple, MIN_N, 12.0, "M")
    bench = panel_benchmarks(db, PER)
    ctx = _build_system_context("wire", "Sistema Bancario", "2026-03-31", bench)
    u = ctx["universo"]
    assert u["n_entidades"] == MIN_N
    assert "instituciones de crédito" in u["descripcion"]
    assert u["estadistico"] == "mediana"
    assert "DECLARÁ EL UNIVERSO" in ctx["encuadre"]
