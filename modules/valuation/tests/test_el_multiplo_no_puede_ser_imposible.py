"""Una entidad muy rentable ya no hace explotar la perpetuidad.

Es el test de integración del techo de crecimiento, y usa el caso REAL que lo destapó: el
BHD, cierre 2025, con las cifras que publica la Superintendencia. Antes daba un P/B de
**1,40× a 12,23×**; el panel de ocho transacciones de esta misma plataforma dice que lo que
se paga por un banco del Caribe es **0,77× a 2,73×**.

**Por qué el panel sirve acá aunque no valide el modelo.** No es un backtest —para eso habría
que valuar cada adquirida a la fecha de su operación— pero sí es una cota de sanidad sobre el
rango de SALIDA: un modelo que devuelve un múltiplo que nadie pagó nunca está diciendo algo
sobre sí mismo, no sobre la entidad.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.auth.models  # noqa: F401 — la FK de banking_data apunta a `users`
from modules.banking_score.models.models import Bank, BankingData, BankType, DataSource
from modules.macro_monitor.models.models import MacroSeries
from modules.valuation.engine import crecimiento as cr
from modules.valuation.engine.cost_of_capital import SERIE_RF
from modules.valuation.service import valuar_entidad
from shared.database.base import Base

#: Patrimonio y utilidad del BHD publicados por la SIB, cierres de diciembre.
BHD = [(2020, 37_758_700_314, 6_257_067_437), (2021, 46_181_915_190, 8_685_523_730),
       (2022, 51_549_213_127, 9_832_739_229), (2023, 59_454_436_719, 13_044_609_705),
       (2024, 65_950_356_726, 13_224_358_486), (2025, 68_175_298_511, 15_101_608_199)]
#: La curva soberana en pesos, tramo reciente, tal como la sirve producción.
CURVA = [("2025-01", 11.96), ("2025-04", 9.71), ("2025-07", 9.61), ("2025-10", 9.93),
         ("2026-01", 9.94), ("2026-03", 9.61), ("2026-05", 10.02), ("2026-07", 9.78)]
#: Rango observado en el panel de transacciones. Es la cota de sanidad.
PANEL_MINIMO, PANEL_MAXIMO = 0.77, 2.73


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    s.add(Bank(id="bhd", name="Banco Múltiple BHD", bank_type=BankType.banca_multiple))
    for anio, patr, util in BHD:
        s.add(BankingData(bank_id="bhd", period_end=date(anio, 12, 31),
                          patrimonio_tecnico=float(patr), utilidad_neta=float(util),
                          source=DataSource.sib_api))
    for p, v in CURVA:
        s.add(MacroSeries(series_code=SERIE_RF, period=p, value=v))
    # PIB nominal con mediana 9,03 %, el crecimiento de largo plazo medido en la serie real.
    # Constante a propósito: lo que este test ejercita es el TECHO, no cómo se calcula la
    # mediana —eso lo cubre `test_techo_de_crecimiento`— y una serie alternada la corría.
    for i in range(29):
        s.add(MacroSeries(series_code=cr.SERIE_PIB_NOMINAL,
                          period=f"{2019 + i // 4}-Q{i % 4 + 1}", value=9.03))
    s.commit()
    yield s
    s.close()


def test_el_multiplo_de_una_entidad_MUY_rentable_queda_en_el_orden_del_panel(db):
    lec = valuar_entidad(db, bank_id="bhd", nombre="Banco Múltiple BHD")
    assert lec is not None
    assert lec.roe_proyectado_pct > 20, "la fixture dejó de ser una entidad muy rentable"
    assert lec.pb_alto < 4.0, (
        f"P/B alto = {lec.pb_alto:.2f}x. El panel observado llega a {PANEL_MAXIMO}x: un "
        "múltiplo muy por encima dice algo del modelo, no de la entidad")
    assert lec.pb_bajo > 1.0, (
        f"P/B bajo = {lec.pb_bajo:.2f}x: una entidad con ROE del 22 % y spread positivo en "
        "todo el rango no puede valer menos que su libro")


def test_el_techo_MORDIO_y_la_lectura_lo_declara(db):
    """El supuesto que cambia el valor de 12,23× a ~3× no puede viajar callado."""
    lec = valuar_entidad(db, bank_id="bhd", nombre="Banco Múltiple BHD")
    assert lec.g_terminal_pct == pytest.approx(9.03, abs=0.01)
    unidos = " ".join(lec.advertencias)
    assert "supera el crecimiento nominal de la economía" in unidos
    assert "más grande que el país" in unidos


def test_los_parametros_del_TIPO_viajan_con_la_lectura(db):
    """Dos valuaciones con distinto tipo de entidad no son comparables sin saberlo."""
    lec = valuar_entidad(db, bank_id="bhd", nombre="Banco Múltiple BHD")
    assert lec.tipo_de_entidad == "banca_multiple"
    assert lec.retencion == pytest.approx(0.75), "no usó la retención MEDIDA de su tipo"
    assert "cotizados latinoamericanos" in lec.evidencia_del_tipo


def test_SIN_el_techo_el_mismo_caso_explota(db):
    """El contraejemplo que fija de qué tamaño era el defecto.

    Se reproduce EXACTAMENTE el caso medido en producción: retención 0,60 —la rúbrica vieja—
    y `Ke` en el extremo bajo de 14,28 %. Ahí `g = 13,54 %` y la perpetuidad converge por
    0,74 pp: el terminal se dispara y el P/B da 12,23×, contra un panel observado que llega a
    2,73×.

    El extremo ALTO de `Ke` no sirve para esto: ahí el defecto también existe pero es de un
    40 %, y un test que lo midiera ahí no mostraría de qué tamaño era.
    """
    from modules.valuation.engine.excess_return import valuar
    bv0, roe, b_viejo = float(BHD[-1][1]), 22.57, 0.60
    sin_techo = valuar(bv_inicial=bv0, ke_pct=14.28, roe_por_periodo=[roe] * 5,
                       retencion=b_viejo, g_terminal_pct=None)
    con_techo = valuar(bv_inicial=bv0, ke_pct=14.28, roe_por_periodo=[roe] * 5,
                       retencion=b_viejo, g_terminal_pct=9.03)
    pb_sin, pb_con = sin_techo.valor / bv0, con_techo.valor / bv0
    assert pb_sin > 10.0, f"el caso dejó de explotar: P/B sin techo = {pb_sin:.2f}x"
    assert pb_con < PANEL_MAXIMO + 0.5, f"el techo no lo contuvo: {pb_con:.2f}x"
    assert pb_sin > pb_con * 3, (
        f"{pb_sin:.2f}x contra {pb_con:.2f}x: el techo dejó de tener el efecto que se midió")
