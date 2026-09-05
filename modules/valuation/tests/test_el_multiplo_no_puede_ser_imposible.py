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


def test_lo_que_ACOTA_el_terminal_es_la_PERSISTENCIA(db):
    """Este test cambió de premisa, y el cambio es el hallazgo.

    Cuando se escribió, medía que el techo de crecimiento contuviera la explosión: sin él, el
    caso del BHD daba 12,23x. Pero el techo solo tapaba el lado de arriba — con la
    perpetuidad creciente intacta, una asociación con ROE por debajo de su Ke seguía dando
    0,16x, que es igual de indefendible.

    Ahora el terminal erosiona el exceso con la persistencia medida, y eso acota los DOS
    lados por construcción: el denominador `1 + Ke − ω` es siempre positivo y mayor que `Ke`.
    El techo de crecimiento sigue valiendo, pero para otra cosa — que el PATRIMONIO no crezca
    más rápido que la economía durante el horizonte explícito.
    """
    from modules.valuation.engine.excess_return import valuar
    bv0, roe = float(BHD[-1][1]), 22.57
    # El caso que antes explotaba: retención vieja de 0,60 y Ke en el extremo bajo.
    v = valuar(bv_inicial=bv0, ke_pct=14.28, roe_por_periodo=[roe] * 5, retencion=0.60,
               persistencia=0.902)
    pb = v.valor / bv0
    assert pb < 4.0, f"P/B = {pb:.2f}x: el terminal volvió a explotar"

    # Y el límite: llevando ω a casi uno el terminal NO se dispara, se convierte en una
    # perpetuidad PLANA. El denominador `1 + Ke − ω` tiende a `Ke`, nunca a cero, que es
    # exactamente la propiedad que hace imposible la explosión — la vieja `(Ke − g)` sí
    # tendía a cero, y de ahí salía el 12,23x.
    v_casi_uno = valuar(bv_inicial=bv0, ke_pct=14.28, roe_por_periodo=[roe] * 5,
                        retencion=0.60, persistencia=0.999)
    pb_limite = v_casi_uno.valor / bv0
    assert pb_limite > pb, "ω tiene que mover el resultado: más persistencia, más valor"
    assert pb_limite < 4.0, (
        f"P/B = {pb_limite:.2f}x con ω = 0,999. Ni en el límite puede explotar: el "
        "denominador tiende a Ke, no a cero")
