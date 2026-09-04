"""El nowcast y su corte point-in-time — y el criterio que decide si se publica.

Lo que este archivo fija:

* **El corte point-in-time no es opcional.** Si el panel de una fecha incluye algo que en esa
  fecha no estaba publicado, el backtest se evalúa a sí mismo con información del futuro y el
  track record que salga es inventado.
* **Las DOS variantes son dos modelos.** `m = 1` y `m = 2` difieren en cuánto imputa el paso
  1; promediar su error entre ellas es engañar al lector. `m = 3` no está: con los tres meses
  publicados el índice del PIB queda determinado por identidad — ver
  `test_cifra_determinada.py`.
* **Un solo regresor agregado.** Tres betas mensuales son otro diseño (MIDAS sin restricción)
  y con ~77 trimestres gastan grados de libertad sin ganancia demostrada.
"""
import math
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor.forecasting import nowcast as nc
from modules.macro_monitor.forecasting import panel as pm
from modules.macro_monitor.models.models import MacroSeries
from shared.database.base import Base


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    _sembrar(s)
    yield s
    s.close()


def _sembrar(db, anios=range(2007, 2026)):
    """Un IMAE mensual que crece con ruido determinista y un PIB trimestral que lo sigue."""
    nivel = 50.0
    imae_por_trim = {}
    for a in anios:
        for m in range(1, 13):
            nivel *= math.exp(0.004 + 0.002 * math.sin(m + a))
            db.add(MacroSeries(series_code=pm.IMAE_INDEX_CODE, period=f"{a}-{m:02d}",
                               value=round(nivel, 6)))
            imae_por_trim.setdefault(f"{a}-Q{(m - 1) // 3 + 1}", []).append(nivel)
    pib = 100.0
    for t, meses in sorted(imae_por_trim.items()):
        prom = sum(meses) / len(meses)
        pib = 100.0 * (prom / 50.0) ** 0.9
        db.add(MacroSeries(series_code=pm.PIB_CODE, period=t, value=round(pib, 6)))
    db.commit()


# ── El corte point-in-time ──────────────────────────────────────────────────────────
def test_el_panel_no_ve_lo_que_todavia_no_estaba_publicado(db):
    """El IMAE de un mes se publica 45 días después de cerrar el mes."""
    p = pm.construir(db, date(2020, 3, 1))
    assert "2020-01" not in {m for m in p.dlog_imae}
    vistos = [t for t in p.dlog_imae]
    assert all(t <= "2020-Q1" for t in vistos)


def test_el_panel_de_hoy_ve_mas_que_el_de_hace_un_ano(db):
    a = pm.construir(db, date(2019, 6, 1))
    b = pm.construir(db, date(2020, 6, 1))
    assert len(b.dlog_pib) > len(a.dlog_pib)


def test_el_pib_tambien_respeta_su_rezago(db):
    """60 días tras cerrar el trimestre. Sin esto el bridge se entrenaría con el dato que
    justamente está tratando de anticipar."""
    p = pm.construir(db, date(2020, 4, 15))
    assert "2020-Q1" not in p.dlog_pib


# ── La imputación del paso 1 ────────────────────────────────────────────────────────
def test_con_tres_meses_no_se_imputa_nada():
    assert nc.imputar_meses([1.0, 2.0, 3.0], 0) == []


def test_imputar_devuelve_tantos_meses_como_faltan():
    serie = [50.0 * math.exp(0.004 * i) for i in range(40)]
    assert len(nc.imputar_meses(serie, 2)) == 2


def test_sin_muestra_para_el_AR_se_repite_el_ultimo_y_no_se_finge_un_modelo():
    assert nc.imputar_meses([10.0, 11.0], 2) == [11.0, 11.0]


def test_la_imputacion_sigue_la_tendencia_y_no_se_dispara():
    serie = [50.0 * math.exp(0.004 * i) for i in range(60)]
    fuera = nc.imputar_meses(serie, 3)
    assert all(serie[-1] * 0.9 < v < serie[-1] * 1.1 for v in fuera), fuera


def _algun_nowcast(db):
    """El primer nowcast que salga, barriendo fechas. Fijar UNA fecha ata el test al
    calendario de publicación: el 20 de mayo el trimestre en curso tiene cero meses de IMAE
    y ninguna variante aplica — que el código diga `None` ahí es correcto, no un fallo."""
    for dia in (20, 25):
        for mes in (6, 7, 8, 9, 10, 11):
            for v in (1, 2):
                r = nc.estimar(db, date(2024, mes, dia), variante=v)
                if r is not None:
                    return r
    raise AssertionError("ninguna fecha del barrido produjo un nowcast")


# ── Las dos variantes ──────────────────────────────────────────────────────────────
def test_cada_variante_lleva_su_propio_model_id(db):
    vistos = set()
    for corte in (date(2024, 3, 20), date(2024, 4, 20), date(2024, 5, 20)):
        for v in (1, 2):
            r = nc.estimar(db, corte, variante=v)
            if r:
                vistos.add(r.model_id)
    assert vistos, "ninguna variante produjo nowcast en las fechas de prueba"
    assert all(mid.startswith("bridge_imae_pib.m") for mid in vistos)


def test_una_variante_que_no_corresponde_a_la_fecha_devuelve_None(db):
    """El corte determina cuántos meses hay; pedir otra variante no se fuerza."""
    corte = date(2024, 3, 20)
    resultados = [nc.estimar(db, corte, variante=v) for v in (1, 2)]
    assert sum(1 for r in resultados if r is not None) <= 1


def test_el_nowcast_trae_los_dos_niveles_de_intervalo_y_contienen_al_punto(db):
    r = _algun_nowcast(db)
    niveles = {i[0] for i in r.intervals}
    assert niveles == {0.80, 0.90}
    for _niv, lo, hi in r.intervals:
        assert lo <= r.point <= hi


def test_el_intervalo_de_90_contiene_al_de_80(db):
    r = _algun_nowcast(db)
    i80 = next(i for i in r.intervals if i[0] == 0.80)
    i90 = next(i for i in r.intervals if i[0] == 0.90)
    assert i90[1] <= i80[1] and i90[2] >= i80[2]


def test_sin_historia_suficiente_no_estima(db):
    """No se estima a medias: con pocos trimestres el coeficiente lo fija el ruido."""
    assert all(nc.estimar(db, date(2008, 6, 20), variante=v) is None for v in (1, 2))
