"""Hasta dónde el BVAR es un PRONÓSTICO, y desde dónde es un escenario.

El backtest sobre la muestra completa dice que le gana al random walk en los ocho horizontes
(+18% a +37%). Recortando la pandemia, la película es otra:

    h=1  +66,3%      h=2  +1,4%      h=3  +60,5%      h=4  −43,5%

A cuatro trimestres el random walk GANA, y la alternancia +66 / +1 / +60 / −43 con n≈20 no es
una estructura: es ruido. Lo único que sobrevive a las dos muestras es el horizonte corto.

Decisión: **1-2 trimestres se publican como pronóstico**, entran al ledger y pueden anclar
una pregunta. **De 3 en adelante son ESCENARIO**: se muestran con su banda, pero no llevan
track record ni pueden anclar nada.

La distinción es estructural y no un comentario: un escenario no tiene `backtest_id`, así que
no hay forma de construirle un `ProjectionMeta` — y sin `ProjectionMeta` el gate de admisión
lo rechaza. Publicar «le gana al random walk en los 8 horizontes» sería cierto y engañoso.
"""
import numpy as np
import pytest

from modules.macro_monitor.forecasting import bvar
from shared.data import medida_de_pronostico as med


def _Y(n=90, k=3, semilla=5):
    rng = np.random.default_rng(semilla)
    A = np.array([[0.5, 0.1, 0.0], [0.0, 0.6, 0.1], [0.1, 0.0, 0.4]])
    Y = np.zeros((n, k))
    for t in range(1, n):
        Y[t] = A @ Y[t - 1] + rng.normal(0, 1, k)
    return Y


_NOMBRES = ("pib_real", "b", "c")


#: El `series_code` OBSERVABLE del objetivo. `"pib_real"` es el nombre de la variable EN EL
#: BLOQUE y no una serie: una proyección que solo declara eso no puede producir pronósticos,
#: porque sus filas no se podrían puntuar contra nada.
_SERIE = "bcrd.xls.pib_2018.serie_original_indice"


def _proyeccion(serie=_SERIE, medida=med.DLOG_PCT):
    return bvar.proyectar_bloque(_Y(), _NOMBRES, "2025-Q4", pasos=8,
                                 serie_objetivo=serie, medida=medida)


def test_el_corte_esta_declarado_y_es_dos():
    assert bvar.HORIZONTES_CON_TRACK_RECORD == 2


def test_los_dos_primeros_son_pronostico_y_el_resto_escenario():
    pr = _proyeccion()
    assert [p.h for p in pr.pronosticos()] == [1, 2]
    assert [e.h for e in pr.escenarios()] == [3, 4, 5, 6, 7, 8]


def test_un_pronostico_trae_backtest_id_y_un_escenario_NO():
    """Es el corte estructural: sin `backtest_id` no se puede armar un `ProjectionMeta`, y
    sin `ProjectionMeta` el gate de admisión rechaza. Un escenario no puede anclar nada
    aunque alguien lo intente."""
    pr = _proyeccion()
    assert all(p.backtest_id for p in pr.pronosticos())
    assert all(not hasattr(e, "backtest_id") for e in pr.escenarios())


def test_un_escenario_igual_trae_su_banda():
    """No se publica un número pelado: un escenario sin incertidumbre se lee como certeza."""
    for e in _proyeccion().escenarios():
        niveles = {i[0] for i in e.intervalos}
        assert niveles == {0.80, 0.90}


def test_el_escenario_se_nombra_a_si_mismo():
    """Quien reciba la estructura tiene que poder distinguirla sin leer documentación."""
    for e in _proyeccion().escenarios():
        assert e.es_escenario is True
        assert "escenario" in e.advertencia.lower()
        assert "track record" in e.advertencia.lower()


def test_no_se_puede_mandar_un_escenario_al_ledger():
    pr = _proyeccion()
    esc = pr.escenarios()[0]
    with pytest.raises((AttributeError, TypeError, ValueError)):
        bvar.a_ledger(esc)


def test_un_pronostico_si_se_puede_mandar():
    campos = bvar.a_ledger(_proyeccion().pronosticos()[0])
    for k in ("model_id", "target_series", "measure", "horizon", "point", "intervals"):
        assert k in campos
    assert campos["target_series"] == _SERIE, (
        "el pronóstico viajó al ledger con el nombre de la variable del bloque en vez del "
        "`series_code`; esa fila queda `pending` para siempre")


def test_sin_serie_observable_NO_HAY_pronostico():
    """El corte que faltaba. `"pib_real"` no es una serie, y una proyección que no sabe
    contra qué código se va a puntuar no puede emitir un horizonte con track record — antes
    lo emitía igual y la fila no cerraba nunca."""
    with pytest.raises(ValueError, match="serie observable|series_code"):
        _proyeccion(serie=None).pronosticos()


def test_sin_medida_declarada_NO_HAY_pronostico():
    """El bloque entrega el PIB en variación logarítmica ×100. Puntuar esa tasa contra el
    índice de volumen da un error del tamaño del índice."""
    with pytest.raises(ValueError, match="medida"):
        _proyeccion(medida=None).pronosticos()
