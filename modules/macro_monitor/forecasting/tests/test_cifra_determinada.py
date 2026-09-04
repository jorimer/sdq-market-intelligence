"""Con los tres meses del IMAE, el PIB no se estima: se CALCULA.

Medido sobre los 77 trimestres del corpus: el promedio trimestral del índice del IMAE es el
índice de volumen del PIB, con una diferencia máxima de **0,0015** puntos y exactamente 0,0
en casi todos. No es una casualidad de esta muestra — el BCRD construye el IMAE así, como
indicador mensual calibrado sobre el PIB trimestral.

Por eso `m = 3` sale de las variantes del modelo. Presentarlo como un nowcast con banda de
error y «+100% de mejora sobre un random walk» sería de lo más engañoso que esta plataforma
podría publicar: el número no lo produce un modelo, lo produce una identidad.

Lo que sí tiene, y es real: **la cifra queda determinada ~15 días antes** de que el BCRD
publique el PIB (45 días de rezago del IMAE contra 60 del PIB). Eso es ventaja de
oportunidad, y se vende como aritmética, no como pronóstico.

Y como la identidad es un hecho EMPÍRICO sobre la fuente y no un teorema, lleva sensor: si el
BCRD cambia cómo construye el IMAE, la «cifra determinada» pasa a ser una mentira y hay que
enterarse por un test y no por un cliente.
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
    yield s
    s.close()


def _sembrar(db, *, cumple_identidad=True, hasta=(2026, 7)):
    nivel, por_trim = 50.0, {}
    for a in range(2007, hasta[0] + 1):
        for m in range(1, 13):
            if (a, m) > hasta:
                break
            nivel *= math.exp(0.004 + 0.002 * math.sin(m + a))
            db.add(MacroSeries(series_code=pm.IMAE_INDEX_CODE, period=f"{a}-{m:02d}",
                               value=nivel))
            por_trim.setdefault(f"{a}-Q{(m - 1) // 3 + 1}", []).append(nivel)
    for t, meses in sorted(por_trim.items()):
        if len(meses) < 3:
            continue
        prom = sum(meses) / 3
        db.add(MacroSeries(series_code=pm.PIB_CODE, period=t,
                           value=prom if cumple_identidad else prom * 1.03))
    db.commit()


def test_la_identidad_se_verifica_contra_el_dato_y_no_se_supone(db):
    _sembrar(db)
    v = nc.verificar_identidad(db)
    assert v["n"] > 40
    assert v["se_cumple"] is True
    assert v["diferencia_maxima"] < nc.TOLERANCIA_IDENTIDAD


def test_si_la_identidad_deja_de_valer_el_sensor_lo_dice(db):
    """El día que el BCRD cambie cómo construye el IMAE, la «cifra determinada» sería una
    mentira. Hay que enterarse por acá y no por un cliente."""
    _sembrar(db, cumple_identidad=False)
    v = nc.verificar_identidad(db)
    assert v["se_cumple"] is False
    assert v["diferencia_maxima"] > nc.TOLERANCIA_IDENTIDAD


#: La ventana donde la cifra vale: el trimestre cierra el 30 de junio, el tercer mes del
#: IMAE se publica ~45 días después (14 de agosto) y el PIB ~60 (29 de agosto). Entre esas
#: dos fechas la cifra está determinada y todavía no publicada — que es TODO el valor del
#: producto. Fuera de la ventana no hay nada que anticipar, y el código lo dice bien.
DENTRO_DE_LA_VENTANA = date(2026, 8, 20)


def test_con_tres_meses_devuelve_la_cifra_SIN_intervalo(db):
    _sembrar(db)
    c = nc.cifra_determinada(db, DENTRO_DE_LA_VENTANA)
    assert c is not None
    assert c.es_identidad is True
    assert not hasattr(c, "intervals"), (
        "la cifra determinada trae banda de error: eso la disfraza de pronóstico")


def test_la_cifra_determinada_coincide_con_el_promedio_de_los_tres_meses(db):
    _sembrar(db)
    c = nc.cifra_determinada(db, DENTRO_DE_LA_VENTANA)
    meses = [v for p, v in pm.observaciones(db, pm.IMAE_INDEX_CODE)
             if pm.trimestre_de(p) == c.horizon]
    assert c.indice == pytest.approx(sum(meses) / len(meses))


def test_sin_los_tres_meses_no_hay_cifra_determinada(db):
    """Con dos meses el trimestre NO está determinado: ahí es donde vive el modelo."""
    _sembrar(db, hasta=(2026, 5))
    assert nc.cifra_determinada(db, date(2026, 7, 25)) is None


def test_si_la_identidad_no_se_cumple_no_se_publica_cifra_determinada(db):
    _sembrar(db, cumple_identidad=False)
    assert nc.cifra_determinada(db, DENTRO_DE_LA_VENTANA) is None


def test_la_variante_m3_ya_no_existe_como_modelo(db):
    _sembrar(db)
    with pytest.raises(ValueError, match="identidad"):
        nc.estimar(db, DENTRO_DE_LA_VENTANA, variante=3)


def test_fuera_de_la_ventana_no_hay_nada_que_anticipar(db):
    """Pasados los 60 días el BCRD ya publicó el PIB: la cifra determinada pierde sentido."""
    _sembrar(db)
    assert nc.cifra_determinada(db, date(2026, 9, 30)) is None
