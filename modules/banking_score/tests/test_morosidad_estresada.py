"""La morosidad estresada llega al informe COMPUTADA: total, desglose, brecha y posición.

Feedback de un alto funcionario de Banco Múltiple Santa Cruz (2026-09-15): el motor comparó
entidades con la mora convencional, y la comparable es la ampliada o estresada, que incluye
castigos y otros componentes. Decisión del dueño: se usa la estresada OFICIAL de la SIB
(catálogo I.027), desglosada, y NO entra al score.

Lo que estos tests fijan es la doctrina aplicada a esa medida:
- las relaciones (brecha, mayor componente, posición contra el sistema) se COMPUTAN;
- la brecha se mide DENTRO del cuadro de la estresada: la mora convencional publicada sale de
  otra cartera y restarlas mezclaría denominadores;
- el sistema es el RESTO de las instituciones de crédito, sin la entidad evaluada;
- un componente ausente se DECLARA, nunca se rellena.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.models import User  # noqa: F401 — registra users para las FK
from shared.database.base import Base
from shared.narrative.sujeto import nombra_su_poblacion
from modules.banking_score.models.models import Bank, BankType, BankingData

CORTE = date(2025, 3, 31)

#: Santa Cruz al 2025-03, en % de su cartera: la fila REAL de `indicadores/morosidad-estresada`
#: dividida por su `carteraTotal` (ver `test_cartera_quality`).
_SANTA_CRUZ = dict(
    morosidad_pct=2.37,
    estresada_vencido_pct=2.1223, estresada_cobranza_pct=0.0640, estresada_tc31a60_pct=0.0,
    estresada_reestructurado_rea_pct=2.3543, estresada_reestructurado_temporal_pct=0.0525,
    castigos_pct=3.0057, estresada_adjudicado_pct=0.0134,
)
_TOTAL_SANTA_CRUZ = round(sum(v for k, v in _SANTA_CRUZ.items() if k != "morosidad_pct"), 4)


def _fila(total: float, **kw) -> dict:
    """Una entidad del resto del sistema: solo importa su total para la mediana."""
    return dict(morosidad_estresada_pct=total, **kw)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _siembra(db, santa_cruz: dict):
    sc = Bank(name="Banco Múltiple Santa Cruz", bank_type=BankType.banca_multiple)
    otros = [Bank(name=f"Banco {i}", bank_type=BankType.banca_multiple) for i in range(3)]
    cambiaria = Bank(name="Agente de Cambio", bank_type=BankType.cambiaria)
    db.add_all([sc, *otros, cambiaria])
    db.flush()
    db.add(BankingData(bank_id=sc.id, period_end=CORTE, **santa_cruz))
    for b, total in zip(otros, (4.0, 5.0, 6.0)):
        db.add(BankingData(bank_id=b.id, period_end=CORTE, **_fila(total)))
    # Una cambiaria con una estresada absurda: si entrara a la mediana, la movería.
    db.add(BankingData(bank_id=cambiaria.id, period_end=CORTE, **_fila(90.0)))
    db.commit()
    return sc


def _con_total(d: dict) -> dict:
    return {**d, "morosidad_estresada_pct": _TOTAL_SANTA_CRUZ}


def test_el_bloque_computa_total_brecha_mayor_componente_y_posicion(db):
    from modules.banking_score.reports.morosidad_estresada import morosidad_estresada_al_corte

    sc = _siembra(db, _con_total(_SANTA_CRUZ))
    b = morosidad_estresada_al_corte(db, sc, CORTE)
    assert b is not None and b["disponible"] is True
    assert b["morosidad_estresada_de_la_entidad_pct"] == pytest.approx(_TOTAL_SANTA_CRUZ)
    # La brecha es DENTRO del cuadro de la estresada: total menos su propio vencido.
    assert b["lo_que_la_mora_convencional_no_ve_pp"] == pytest.approx(
        _TOTAL_SANTA_CRUZ - _SANTA_CRUZ["estresada_vencido_pct"], abs=1e-3)
    # Superlativo COMPUTADO: fuera de la vencida, pesan más los castigos (3,01) que los
    # reestructurados REA (2,35). La fixture tiene que ejercitar esa comparación.
    assert _SANTA_CRUZ["castigos_pct"] > _SANTA_CRUZ["estresada_reestructurado_rea_pct"]
    assert "castigos" in b["mayor_componente_fuera_de_la_vencida"]
    # El desglose reconcilia con el total.
    assert sum(c["pct_de_la_cartera_de_la_entidad"]
               for c in b["componentes_de_la_estresada_de_la_entidad"]) == pytest.approx(
        _TOTAL_SANTA_CRUZ, abs=1e-3)
    # Mediana del RESTO de instituciones de crédito: 4, 5, 6 → 5. Ni Santa Cruz ni la
    # cambiaria (90 %) entran.
    assert b["mediana_estresada_del_resto_del_sistema_pct"] == pytest.approx(5.0)
    assert b["n_entidades_del_resto_del_sistema"] == 3
    assert b["excluye_a_la_entidad_evaluada"] is True
    assert b["diferencia_con_la_mediana_del_resto_pp"] == pytest.approx(
        _TOTAL_SANTA_CRUZ - 5.0, abs=1e-3)
    assert b["posicion_frente_a_la_mediana_del_resto"] == "por encima"
    assert b["puntua_en_el_score"] is False


def test_la_mora_convencional_viaja_pero_no_se_resta(db):
    """Salen de cuadros distintos de la SIB: 2,37 publicada contra 2,12 dentro de la
    estresada. El bloque las sirve a las dos y declara por qué no se restan."""
    from modules.banking_score.reports.morosidad_estresada import morosidad_estresada_al_corte

    sc = _siembra(db, _con_total(_SANTA_CRUZ))
    b = morosidad_estresada_al_corte(db, sc, CORTE)
    assert b["morosidad_convencional_publicada_de_la_entidad_pct"] == pytest.approx(2.37)
    assert "no se restan" in b["nota_de_carteras"]
    # Ninguna diferencia se computa CONTRA la publicada; la brecha legítima
    # (`lo_que_la_mora_convencional_no_ve_pp`) es interna al cuadro de la estresada.
    assert not any("publicada" in k and k.endswith("_pp") for k in b)
    assert b["lo_que_la_mora_convencional_no_ve_pp"] != pytest.approx(
        _TOTAL_SANTA_CRUZ - 2.37, abs=1e-3), "la brecha se midió contra la mora PUBLICADA"


def test_un_componente_ausente_se_declara_y_no_publica_cifra(db):
    incompleta = {**_SANTA_CRUZ, "estresada_reestructurado_rea_pct": None}
    sc = _siembra(db, {**incompleta, "morosidad_estresada_pct": None})
    from modules.banking_score.reports.morosidad_estresada import morosidad_estresada_al_corte

    b = morosidad_estresada_al_corte(db, sc, CORTE)
    assert b is not None and b["disponible"] is False
    assert b["motivo"]
    assert b.get("morosidad_estresada_de_la_entidad_pct") is None
    assert "posicion_frente_a_la_mediana_del_resto" not in b


def test_el_anio_computa_el_cambio_y_no_lo_inventa_sin_apertura(db):
    """El año por dentro recibe apertura y cierre; el cambio se COMPUTA, y sin apertura
    disponible no se publica un cambio."""
    from modules.banking_score.reports.morosidad_estresada import morosidad_estresada_del_anio

    sc = _siembra(db, _con_total(_SANTA_CRUZ))           # cierre = CORTE (2025-03-31)
    apertura = date(2024, 12, 31)
    db.add(BankingData(bank_id=sc.id, period_end=apertura,
                       **{**_con_total(_SANTA_CRUZ), "morosidad_estresada_pct": 6.0}))
    db.commit()
    anio = morosidad_estresada_del_anio(db, sc, [str(apertura), str(CORTE)])
    assert anio["cierre"]["disponible"] and anio["apertura"]["disponible"]
    assert anio["cambio_de_la_estresada_de_la_entidad_en_el_anio_pp"] == pytest.approx(
        _TOTAL_SANTA_CRUZ - 6.0, abs=1e-3)

    sin_apertura = morosidad_estresada_del_anio(db, sc, ["2023-12-31", str(CORTE)])
    assert sin_apertura["apertura"] is None
    assert "cambio_de_la_estresada_de_la_entidad_en_el_anio_pp" not in sin_apertura


def test_toda_clave_del_bloque_nombra_su_poblacion(db):
    """La regla del sujeto, sobre el bloque real y no sobre una lista escrita a mano."""
    from modules.banking_score.reports.morosidad_estresada import morosidad_estresada_al_corte

    sc = _siembra(db, _con_total(_SANTA_CRUZ))
    b = morosidad_estresada_al_corte(db, sc, CORTE)

    def _claves(x):
        if isinstance(x, dict):
            for k, v in x.items():
                yield k
                yield from _claves(v)
        elif isinstance(x, list):
            for v in x:
                yield from _claves(v)

    claves = list(_claves(b))
    assert len(claves) > 10, "el bloque no se armó: no probó nada"
    assert all(nombra_su_poblacion(k) for k in claves), [
        k for k in claves if not nombra_su_poblacion(k)]
