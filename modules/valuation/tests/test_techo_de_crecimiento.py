"""Una entidad no puede crecer más que su economía, y el terminal tiene que saberlo.

**El defecto que esto cierra, medido en producción.** Valuando el BHD con el cierre de 2025
el modelo devolvía un P/B implícito de **1,40× a 12,23×**, contra un panel de ocho
transacciones que dice que lo que se paga es **0,77× a 2,73×**. Un 12,23× no es un valor
alto: es un modelo roto.

La causa es aritmética: `g = b × ROE` daba 13,54 % contra un `Ke` de 14,28 %, y la
perpetuidad convergía por 0,74 pp. **El guard que ya existía solo atrapa `g >= Ke`** — el
caso que NO converge—; el que converge y es imposible pasaba, y ése es peor porque devuelve
un número.

Con el techo, el mismo caso da **1,31× a 3,15×**.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor.models.models import MacroSeries
from modules.valuation.engine import crecimiento as cr
from shared.database.base import Base


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _sembrar_pib(db, valores) -> None:
    for i, v in enumerate(valores):
        db.add(MacroSeries(series_code=cr.SERIE_PIB_NOMINAL,
                           period=f"{2015 + i // 4}-Q{i % 4 + 1}", value=v))
    db.commit()


def test_el_techo_se_MIDE_de_la_serie_y_no_se_escribe():
    """Una constante copiada envejece sin avisar."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    _sembrar_pib(s, [7.0] * 8 + [11.0] * 8)      # mediana = 9,0
    t = cr.techo_nominal(s)
    assert t.es_medido and t.n_observaciones == 16
    assert t.valor_pct == pytest.approx(9.0)
    s.close()


def test_es_la_MEDIANA_y_no_la_media(db):
    """La serie trae la caída de 2020 y el rebote de 2021. Una media los arrastra a los dos;
    una perpetuidad necesita el centro de la serie larga, no el promedio de sus extremos."""
    _sembrar_pib(db, [8.0] * 13 + [-20.0, 40.0, 8.0])   # media ≈ 8,9 · mediana = 8,0
    t = cr.techo_nominal(db)
    assert t.valor_pct == pytest.approx(8.0), (
        f"el techo dio {t.valor_pct}: con la caída y el rebote adentro, la media miente")


def test_con_POCAS_observaciones_usa_el_respaldo_Y_LO_DECLARA(db):
    """Un techo apoyado en tres trimestres queda a merced de un par de datos. El respaldo se
    usa y se dice — un valor de respaldo silencioso es una constante escrita a mano con otro
    nombre."""
    _sembrar_pib(db, [8.0, 9.0, 10.0])
    t = cr.techo_nominal(db)
    assert not t.es_medido
    assert t.valor_pct == cr.TECHO_DE_RESPALDO
    assert "RESPALDO" in t.evidencia and "envejece" in t.evidencia


def test_el_techo_MUERDE_cuando_el_crecimiento_sostenible_lo_supera():
    """El caso del BHD: retención 0,75 × ROE 22,57 % = 16,93 %, muy por encima del 9 %."""
    techo = cr.TechoDeCrecimiento(9.03, 29, True, "medido")
    g, aviso = cr.g_terminal(roe_pct=22.57, retencion=0.75, techo=techo)
    assert g == pytest.approx(9.03)
    assert aviso is not None
    assert "16.93" in aviso and "9.03" in aviso, "el aviso no dice de cuánto a cuánto"
    assert "más grande que el país" in aviso


def test_NO_muerde_ni_avisa_cuando_el_crecimiento_ya_era_sostenible():
    """El caso normal. Un aviso que aparece siempre no informa: se vuelve ruido y se ignora
    justo cuando importa."""
    techo = cr.TechoDeCrecimiento(9.03, 29, True, "medido")
    g, aviso = cr.g_terminal(roe_pct=7.20, retencion=0.99, techo=techo)
    assert g == pytest.approx(7.128, abs=1e-3)
    assert aviso is None


def test_el_techo_NO_es_un_piso():
    """Solo acota hacia arriba. Una entidad que crece poco crece poco — subirla al techo
    sería inventarle crecimiento."""
    techo = cr.TechoDeCrecimiento(9.03, 29, True, "medido")
    g, _ = cr.g_terminal(roe_pct=2.0, retencion=0.5, techo=techo)
    assert g == pytest.approx(1.0)
