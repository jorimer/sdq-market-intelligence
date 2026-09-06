"""El ROE de la historia es de DOCE MESES, sobre el patrimonio de doce meses antes.

**El defecto, medido.** La SIB publica `utilidad_neta` ACUMULADA del ejercicio (Q1 = 3 meses,
Q2 = 6, …) y `historia_de` la dividía por el patrimonio del corte ANTERIOR en cada corte con
patrimonio. Con cortes trimestrales —que en producción existen: `/valuation/periods` los
lista— la serie salía `2.91, 5.77, 8.56, 11.30, 2.80, …` para una entidad de ~11,3 % anual, y
`_roe_proyectado` (mediana de los últimos cuatro) publicaba **6,88 %**: con Ke de 14–20 el eje
decía «destruye valor en todo el rango» cuando el spread real cambia de signo.

Banking ya había medido y resuelto lo mismo (`banking_score/scoring/ttm.py`: el primer
trimestre concentra 9,9 % de la utilidad anual; ventana móvil de doce meses). Valuación
reescribió el ROE desde cero sin mirar ese guard — instancia 10 de «un guard existe en un
motor y falta en el otro». Y ninguna de las catorce fixtures del eje tenía un corte que no
fuera diciembre, donde el acumulado ya es anual y el defecto no se ve.
"""
from __future__ import annotations

import pathlib
import re
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.auth.models  # noqa: F401
import shared.products.models  # noqa: F401
from modules.banking_score.models.models import Bank, BankType
from modules.macro_monitor.models.models import MacroSeries
from modules.valuation.engine import crecimiento as cr
from modules.valuation.engine.cost_of_capital import SERIE_RF
from modules.valuation.service import historia_de, valuar_entidad
from modules.valuation.tests._siembra import sembrar_trimestres
from shared.database.base import Base

AQUI = pathlib.Path(__file__).resolve().parent
#: 18 %: cae DENTRO del rango de Ke de la fixture (14–20), así que la lectura honesta es «cambia de
#: signo». Con el ROE roto (~9,7 %) salía «destruye valor en todo el rango».
ROE = 18.0


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    for i, v in enumerate((11.96, 9.71, 9.61, 9.93, 9.94, 9.61, 10.02, 9.78)):
        s.add(MacroSeries(series_code=SERIE_RF, period=f"2025-{i + 1:02d}", value=v))
    for i in range(29):
        s.add(MacroSeries(series_code=cr.SERIE_PIB_NOMINAL,
                          period=f"{2019 + i // 4}-Q{i % 4 + 1}", value=9.03))
    s.add(Bank(id="bm", name="Banco Trimestral", bank_type=BankType.banca_multiple))
    s.commit()
    yield s
    s.close()


def _sembrar(db, **kw):
    sembrar_trimestres(db, "bm", patrimonio_diciembre=[100e6, 104e6, 108e6, 112e6],
                       anios=(2022, 2023, 2024, 2025), roe_anual_pct=ROE, **kw)
    db.commit()


def test_con_cortes_TRIMESTRALES_el_ROE_es_el_ANUAL_en_cada_corte(db) -> None:
    _sembrar(db)
    h = historia_de(db, "bm")
    assert h.roe_pct, "no se computó ningún ROE"
    # Cada corte con doce meses de historia trae el ROE de DOCE meses: ni 3, ni 6, ni 9.
    for periodo, roe in zip(h.periodos_con_roe, h.roe_pct):
        # ±0,2 pp: el patrimonio interpola geométricamente entre diciembres, así que el ROE
        # de doce meses sobre la apertura de doce meses antes no es EXACTAMENTE el anual en
        # los cortes intermedios; lo que se veta es 3, 6 o 9 meses (≈4,5 / 9 / 13,5 %).
        assert roe == pytest.approx(ROE, abs=0.2), (
            f"{periodo}: ROE {roe:.2f} % — es el acumulado del ejercicio sobre el patrimonio "
            "del trimestre anterior, no el de doce meses")


def test_el_ROE_PROYECTADO_no_se_hunde_por_los_cortes_intermedios(db) -> None:
    _sembrar(db)
    lec = valuar_entidad(db, bank_id="bm", nombre="Banco Trimestral")
    assert lec is not None
    assert lec.roe_proyectado_pct == pytest.approx(ROE, abs=0.2), (
        f"ROE proyectado {lec.roe_proyectado_pct:.2f} % para una entidad de {ROE} % anual: la "
        "mediana mezcla acumulados de 3, 6 y 9 meses")
    assert lec.ke_bajo_pct < ROE < lec.ke_alto_pct, "la fixture ya no cruza el rango de Ke"
    assert lec.cambia_de_signo and not lec.destruye_valor, (
        "el veredicto de destrucción de valor sale de un ROE a medias")


def test_un_corte_SIN_utilidad_no_vale_CERO_ni_produce_ROE(db) -> None:
    """`None` no es 0,0: un corte sin utilidad publicada no tiene ROE y se declara con un
    punto menos, no con un ROE de cero que hunde la mediana."""
    _sembrar(db, sin_utilidad_en=[date(2025, 6, 30)])
    h = historia_de(db, "bm")
    assert "2025-06-30" not in h.periodos_con_roe
    assert all(r > 0 for r in h.roe_pct), "un corte sin utilidad entró como ROE 0"
    # Y el corte SIGUIENTE tampoco puede fingir: su ventana de doce meses necesita el mismo
    # corte del año anterior, que sí está, así que él sí tiene ROE.
    assert "2025-09-30" in h.periodos_con_roe


def test_sin_el_MISMO_corte_del_anio_anterior_no_hay_ventana_de_doce_meses(db) -> None:
    """El primer año solo tiene ROE en diciembre... y ni eso: no tiene apertura. Los cortes
    intermedios del segundo año necesitan el mismo corte del primero — que está."""
    _sembrar(db)
    h = historia_de(db, "bm")
    assert not any(p.startswith("2022") for p in h.periodos_con_roe), "2022 no tiene apertura"
    assert "2023-03-31" in h.periodos_con_roe and "2023-12-31" in h.periodos_con_roe


def test_con_solo_CIERRES_ANUALES_sigue_funcionando_igual(db) -> None:
    """La forma anual (la de todas las fixtures viejas) no cambia de resultado."""
    from modules.banking_score.models.models import BankingData, DataSource
    pats = [100e6, 106e6, 112.36e6, 119.1e6]
    for i, (anio, p) in enumerate(zip((2022, 2023, 2024, 2025), pats)):
        util = pats[i - 1] * ROE / 100.0 if i else 0.0
        db.add(BankingData(bank_id="bm", period_end=date(anio, 12, 31), patrimonio_tecnico=p,
                           utilidad_neta=util, source=DataSource.sib_api))
    db.commit()
    h = historia_de(db, "bm")
    assert len(h.roe_pct) == 3 and all(r == pytest.approx(ROE, abs=1e-6) for r in h.roe_pct)


def test_la_serie_del_informe_es_la_de_DOCE_meses(db) -> None:
    _sembrar(db)
    lec = valuar_entidad(db, bank_id="bm", nombre="Banco Trimestral")
    assert lec is not None
    assert len(lec.serie_spread) == len(historia_de(db, "bm").roe_pct)
    assert all(r == pytest.approx(ROE, abs=0.2) for _p, r in lec.serie_spread)


# ── Las fixtures del eje llevan cortes intermedios ────────────────────────────────


_INTERMEDIO = re.compile(r"date\(\d{4}, *(3|6|9), *\d{1,2}\)|sembrar_trimestres\(")


@pytest.mark.parametrize("archivo", sorted(
    p.name for p in AQUI.glob("test_*.py") if "BankingData(" in p.read_text("utf-8")))
def test_toda_fixture_que_siembra_balances_trae_CORTES_INTERMEDIOS(archivo: str) -> None:
    """Catorce fixtures con solo diciembre pasaron en verde contra el ROE roto. Un archivo que
    siembra `BankingData` y no siembra un corte de marzo, junio o septiembre no ejercita la
    ventana de doce meses; puede eximirse declarando `# solo-diciembre: <motivo>`."""
    fuente = (AQUI / archivo).read_text("utf-8")
    if "# solo-diciembre:" in fuente:
        return
    assert _INTERMEDIO.search(fuente), (
        f"{archivo} siembra balances solo de diciembre: el defecto del ROE acumulado no se ve")


def test_el_barrido_encontro_fixtures() -> None:
    assert sum(1 for p in AQUI.glob("test_*.py") if "BankingData(" in p.read_text("utf-8")) >= 5


# ── El selector ofrece solo lo que se puede valuar ────────────────────────────────


def test_con_DOS_cortes_trimestrales_la_entidad_NO_se_ofrece_y_con_cinco_SI(db) -> None:
    """`scope_options` contaba filas: dos cortes trimestrales son seis meses, no hay ventana
    de doce, y la entidad se ofrecía y fallaba al elegirla."""
    from modules.banking_score.models.models import BankingData, DataSource
    from modules.valuation.products import ValuationProduct
    for m, d, ytd in ((9, 30, 7e6), (12, 31, 12e6)):
        db.add(BankingData(bank_id="bm", period_end=date(2025, m, d), patrimonio_tecnico=100e6,
                           utilidad_neta=ytd, source=DataSource.sib_api))
    db.commit()
    assert ValuationProduct(db).scope_options() == [], "dos cortes de un mismo año no son doce meses"
    assert ValuationProduct(db).available_periods() == []
    for m, d, ytd in ((3, 31, 1.2e6), (6, 30, 4.8e6), (9, 30, 8.4e6), (12, 31, 12e6)):
        db.add(BankingData(bank_id="bm", period_end=date(2024, m, d), patrimonio_tecnico=96e6,
                           utilidad_neta=ytd, source=DataSource.sib_api))
    db.commit()
    assert [o["value"] for o in ValuationProduct(db).scope_options()] == ["bm"]
    periodos = ValuationProduct(db).available_periods()
    assert periodos == ["2025-12-31", "2025-09-30"], periodos
