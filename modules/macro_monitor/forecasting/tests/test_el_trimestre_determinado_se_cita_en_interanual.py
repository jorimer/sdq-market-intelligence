"""El trimestre DETERMINADO se cita en variación INTERANUAL, que es la medida citable.

**El defecto, en un informe real.** El Deep Dive de proyecciones del 2026-09-06 titulaba
«2026-Q2 determinado · índice 133.133» y resumía «una variación de 0,38 % contra el trimestre
anterior». Esa variación trimestral es la de la serie ORIGINAL sin desestacionalizar —
exactamente la medida que #1117 sacó del bloque porque depende de en qué trimestre cae el
horizonte (−1,13 % de media en los Q3, +4,67 % en los Q4)—. El trimestre está determinado, así
que su interanual es COMPUTABLE contra el índice publicado del mismo trimestre del año
anterior, y es la cifra que la entrada canónica del PIB declara citable. No se publicaba.

La trimestral no desaparece: se sirve al lado, rotulada por lo que es.
"""
from __future__ import annotations

from datetime import date

import pytest

from modules.macro_monitor import products_forecast as pf
from modules.macro_monitor.forecasting import nowcast as nc
from modules.macro_monitor.forecasting import panel as pm
from modules.macro_monitor.forecasting.tests.test_cifra_determinada import _sembrar, db  # noqa: F401


def _esperado(db, c) -> float:
    pib = dict(pm.observaciones(db, pm.PIB_CODE))
    previo = pib[f"{int(c.horizon[:4]) - 1}{c.horizon[4:]}"]
    return round((c.indice / previo - 1) * 100, 4)


def test_la_cifra_determinada_trae_su_INTERANUAL_contra_el_mismo_trimestre_del_anio_anterior(db):
    _sembrar(db)
    c = nc.cifra_determinada(db, date(2026, 8, 15))
    assert c is not None
    assert c.interanual_pct == pytest.approx(_esperado(db, c), abs=1e-4)
    assert c.dlog_pct is not None, "la trimestral sigue viajando, rotulada"


def test_sin_el_mismo_trimestre_del_anio_anterior_la_interanual_es_None_y_no_cero(db):
    _sembrar(db, hasta=(2007, 9))
    c = nc.cifra_determinada(db, date(2007, 11, 15))
    assert c is not None and c.interanual_pct is None


def _payload(db):
    c = nc.cifra_determinada(db, date(2026, 8, 15))
    return {"cifra_determinada": {"trimestre": c.horizon, "indice": c.indice,
                                  "dlog_pct": c.dlog_pct, "interanual_pct": c.interanual_pct,
                                  "diferencia_maxima_historica": 0.0015},
            "proyecciones": [], "escenarios": []}, c


def test_el_TITULAR_el_resumen_y_el_nowcast_citan_la_INTERANUAL(db):
    _sembrar(db)
    p, c = _payload(db)
    titular = pf._titular_de(p["cifra_determinada"], p["proyecciones"])
    assert f"{c.interanual_pct:.2f} %" in titular and "interanual" in titular, titular
    assert "índice" not in titular
    # El resumen redondea a dos decimales; el nowcast, que es la sección técnica, a cuatro.
    for nombre, texto, dec in (("resumen", pf._md_resumen_ejecutivo(p), 2),
                               ("nowcast", pf._md_nowcast(p), 4)):
        yoy = f"{c.interanual_pct:.{dec}f} %"
        assert yoy in texto and "interanual" in texto, f"{nombre}: no cita la interanual"
        # La trimestral sigue, rotulada como lo que es: serie original, depende del calendario.
        assert f"{c.dlog_pct:.2f} %" in texto or f"{c.dlog_pct:.4f} %" in texto, nombre
        assert "calendario" in texto or "desestacionaliz" in texto, (
            f"{nombre}: publica la trimestral sin decir que depende del calendario")


def test_sin_interanual_el_texto_no_la_inventa(db):
    _sembrar(db)
    p, _c = _payload(db)
    p["cifra_determinada"]["interanual_pct"] = None
    for texto in (pf._md_resumen_ejecutivo(p), pf._md_nowcast(p)):
        assert "interanual" not in texto or "no se puede" in texto or "sin" in texto
    assert "None" not in pf._titular_de(p["cifra_determinada"], [])
