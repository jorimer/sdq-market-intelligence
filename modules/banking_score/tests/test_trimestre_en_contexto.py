"""Un trimestre se destaca solo si es distinto a SU historia o al SISTEMA en ese corte.

Feedback de un alto funcionario de Banco Múltiple Santa Cruz (2026-09-15) sobre «el segundo
trimestre concentró el 51 % del movimiento del año»: si siempre es así, el motor debió decirlo
o decir por qué importa; los informes a la junta ya cubren la variación trimestral. El valor
está en señalar cuándo la entidad se desempeña distinto a su historia o al resto del mercado.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.models import User  # noqa: F401 — registra users para las FK
from shared.database.base import Base
from modules.banking_score.models.models import Bank, BankType, ModelType, RatingResult
from modules.banking_score.reports import trimestre_en_contexto as tc

ANIO = 2025


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _serie(db, bank, puntos):
    for pe, score in puntos.items():
        db.add(RatingResult(bank_id=bank.id, period_end=pe, overall_score=score,
                            rating_tier="SDQ-A", model_type=ModelType.deterministic,
                            model_version="1.0"))


def _anios(scores_por_anio):
    """{anio: (dic_anterior, mar, jun, sep, dic)} → {fecha: score}."""
    out = {}
    for a, (d0, m, j, s, d) in scores_por_anio.items():
        out.update({date(a - 1, 12, 31): d0, date(a, 3, 31): m, date(a, 6, 30): j,
                    date(a, 9, 30): s, date(a, 12, 31): d})
    return out


def _siembra(db, n_anios_previos=4, cambio_sistema_q2=-3.5):
    ent = Bank(name="Banco Múltiple Santa Cruz", bank_type=BankType.banca_multiple)
    db.add(ent)
    db.flush()
    # Años previos: Q1 sube ~+3 TODOS los años (patrón propio); Q2 se mueve poco (±0,5).
    previos = {a: (60.0, 63.0, 63.4, 63.2, 63.0)
               for a in range(ANIO - n_anios_previos, ANIO)}
    # El año: Q1 +2.95 (como siempre) y Q2 −3.45 (nunca antes).
    _serie(db, ent, {**_anios(previos), **_anios({ANIO: (64.36, 67.31, 63.86, 63.65, 63.81)})})
    # El resto del sistema en el Q2 del año: seis instituciones de crédito que caen parecido.
    for i in range(6):
        b = Bank(name=f"Banco Resto {i}", bank_type=BankType.banca_multiple)
        db.add(b)
        db.flush()
        _serie(db, b, {date(ANIO, 3, 31): 70.0, date(ANIO, 6, 30): 70.0 + cambio_sistema_q2 + i * 0.1})
    # Una cambiaria que se desploma: si entrara al sistema, movería la referencia.
    c = Bank(name="Agente de Cambio", bank_type=BankType.cambiaria)
    db.add(c)
    db.flush()
    _serie(db, c, {date(ANIO, 3, 31): 90.0, date(ANIO, 6, 30): 40.0})
    db.commit()
    return ent


_TRAMOS = [
    {"tramo": "primer trimestre", "desde": "2024-12-31", "hasta": "2025-03-31", "cambio": 2.95},
    {"tramo": "segundo trimestre", "desde": "2025-03-31", "hasta": "2025-06-30", "cambio": -3.45},
]


def _por_tramo(filas):
    return {f["tramo"]: f for f in filas}


def test_el_q1_que_sube_todos_los_anios_es_ordinario_y_no_se_destaca(db):
    ent = _siembra(db)
    q1 = _por_tramo(tc.contexto_de_los_tramos(db, ent, ANIO, _TRAMOS))["primer trimestre"]
    assert q1["rango_historico_del_mismo_trimestre"]["n_anios"] == 4
    assert q1["frente_a_su_historia"] == tc.ORDINARIO
    assert q1["se_destaca"] is False


def test_el_q2_sin_precedente_propio_pero_igual_al_sistema(db):
    ent = _siembra(db, cambio_sistema_q2=-3.5)
    q2 = _por_tramo(tc.contexto_de_los_tramos(db, ent, ANIO, _TRAMOS))["segundo trimestre"]
    assert q2["frente_a_su_historia"] == tc.ATIPICO
    # Mediana del RESTO: seis bancos de −3,5 a −3,0 → −3,25. La cambiaria (−50) no entra.
    ref = q2["sistema_en_el_mismo_trimestre"]
    assert ref["n_entidades_del_resto"] == 6
    assert ref["mediana_del_cambio_del_resto"] == pytest.approx(-3.25, abs=0.01)
    assert q2["frente_al_sistema"] == tc.ORDINARIO
    assert q2["rotulo"] == "atípico frente a su historia"
    assert q2["se_destaca"] is True


def test_si_el_sistema_no_cayo_el_q2_es_atipico_tambien_frente_al_sistema(db):
    ent = _siembra(db, cambio_sistema_q2=0.0)
    q2 = _por_tramo(tc.contexto_de_los_tramos(db, ent, ANIO, _TRAMOS))["segundo trimestre"]
    assert q2["frente_al_sistema"] == tc.ATIPICO
    assert q2["rotulo"] == "atípico frente a su historia y frente al sistema"


def test_con_poca_historia_no_se_afirma_patron_propio(db):
    ent = _siembra(db, n_anios_previos=2)
    q1 = _por_tramo(tc.contexto_de_los_tramos(db, ent, ANIO, _TRAMOS))["primer trimestre"]
    assert q1["rango_historico_del_mismo_trimestre"]["n_anios"] == 2
    assert q1["frente_a_su_historia"] == tc.HISTORIA_INSUFICIENTE
