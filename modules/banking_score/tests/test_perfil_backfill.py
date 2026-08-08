"""Recálculo de Perfil SDQ sobre el histórico (Fase 4, §9)."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.database.base import Base
import modules.banking_score.models.models as m
from modules.banking_score.scoring.perfil_backfill import backfill_perfil_sdq


@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:")
    import shared.auth.models  # noqa: F401 — la FK created_by apunta a users
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _sembrar(db, n_bancos=4, periodos=("2025-12-31", "2026-03-31")):
    for i in range(n_bancos):
        db.add(m.Bank(id=f"b{i}", name=f"Banco {i}", bank_type=m.BankType.banca_multiple))
    for p in periodos:
        for i in range(n_bancos):
            db.add(m.RatingResult(
                bank_id=f"b{i}", period_end=date.fromisoformat(p),
                overall_score=70 + i, rating_tier="SDQ-A",
                solidez_score=80 + i, calidad_score=70, eficiencia_score=40 + i * 15,
                liquidez_score=60, diversificacion_score=50,
                model_type=m.ModelType.deterministic))
    db.commit()


def test_recomputa_todos_los_periodos(db):
    """El histórico se RECOMPUTA desde los sub-componentes, no se traduce.

    No existe un mapeo de `SDQ-AA+` a dos ejes: un símbolo único no contiene la información
    que los ejes separan. Traducirlo inventaría una lectura que nadie calculó.
    """
    _sembrar(db)
    r = backfill_perfil_sdq(db)
    assert r["periodos"] == 2 and r["ratings"] == 8
    for row in db.query(m.RatingResult).all():
        assert row.ejecucion_score is not None
        assert row.resiliencia_score is not None
        assert row.banda_ejecucion and row.banda_resiliencia


def test_los_cortes_son_del_periodo_no_globales(db):
    """Comparar la eficiencia de 2021 contra los cuartiles de 2026 mediría el paso del
    tiempo, no el desempeño. Cada período se puntúa contra su propio panel."""
    for i in range(4):
        db.add(m.Bank(id=f"b{i}", name=f"Banco {i}", bank_type=m.BankType.banca_multiple))
    # Período viejo: todo el panel eficiente. Período nuevo: todo el panel ineficiente.
    for p, base in (("2025-12-31", 80), ("2026-03-31", 20)):
        for i in range(4):
            db.add(m.RatingResult(
                bank_id=f"b{i}", period_end=date.fromisoformat(p),
                overall_score=70, rating_tier="SDQ-A", solidez_score=80, calidad_score=70,
                eficiencia_score=base + i * 3, liquidez_score=60, diversificacion_score=50,
                model_type=m.ModelType.deterministic))
    db.commit()
    backfill_perfil_sdq(db)
    filas = {(r.bank_id, str(r.period_end)): r for r in db.query(m.RatingResult).all()}
    # El MEJOR de cada período es "Sobresaliente" en SU período, aunque sus niveles
    # absolutos (89 vs 29 de eficiencia) no tengan nada que ver entre sí.
    assert filas[("b3", "2025-12-31")].banda_ejecucion == "Sobresaliente"
    assert filas[("b3", "2026-03-31")].banda_ejecucion == "Sobresaliente"


def test_es_idempotente(db):
    _sembrar(db)
    backfill_perfil_sdq(db)
    antes = {r.bank_id: (r.ejecucion_score, r.resiliencia_score)
             for r in db.query(m.RatingResult).all()}
    backfill_perfil_sdq(db)
    despues = {r.bank_id: (r.ejecucion_score, r.resiliencia_score)
               for r in db.query(m.RatingResult).all()}
    assert antes == despues


def test_no_genera_acciones_de_rating(db):
    """Recalcular el histórico con `rescore` produciría movimientos de tier entre períodos
    que nunca ocurrieron. El backfill solo reagrega."""
    _sembrar(db)
    backfill_perfil_sdq(db)
    assert db.query(m.RatingAction).count() == 0


def test_sin_ratings_no_revienta(db):
    r = backfill_perfil_sdq(db)
    assert r["ratings"] == 0 and r["periodos"] == 0
