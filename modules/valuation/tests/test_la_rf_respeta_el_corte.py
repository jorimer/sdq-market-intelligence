"""La tasa libre de riesgo se toma AL CORTE del informe, y la ventana declara sus fechas.

**El defecto, en un informe real.** El Deep Dive de Banco Popular «al 2026-06-30» (emitido el
2026-09-06) tomó las últimas ocho observaciones vivas de la curva sin mirar el corte: entró
una de julio 2026 —posterior al corte— y la ventana arrancaba en enero 2025, veinte meses
antes. §11 decía «dato: 8 observación(es)» sin decir de cuándo. El corte manda: un informe a una
fecha no puede usar una tasa publicada después, y el lector tiene que saber qué meses arman el
rango que abre el Ke 5,7 pp.
"""
from __future__ import annotations

from datetime import date

import pytest

from modules.valuation.engine import cost_of_capital as cc
from modules.valuation.tests.test_el_entorno_llega_al_informe import CURVA, _db, _por_http
from shared.products.tiers import ProductTier


@pytest.fixture()
def db():
    s = _db()
    yield s
    s.close()


def test_el_motor_excluye_las_observaciones_POSTERIORES_al_corte(db) -> None:
    ke = cc.calcular(db, hasta=date(2025, 12, 31))
    vivas = [(p, v) for p, v in CURVA if p <= "2025-12"]
    assert ke.n_observaciones_rf == len(vivas), "entraron observaciones posteriores al corte"
    assert ke.ventana_rf == (vivas[0][0], vivas[-1][0])
    # Y sin corte, la ventana es la de siempre (las últimas ocho): el motor no cambia de
    # resultado para quien no lo pide.
    assert cc.calcular(db).n_observaciones_rf == 8


def test_la_LECTURA_usa_la_Rf_al_corte_y_la_ventana_viaja_en_el_payload(db) -> None:
    from modules.valuation.products import ValuationProduct
    snap = ValuationProduct(db).snapshot(ProductTier.deep_dive, "2025-12-31", scope="aap1")
    pr = snap.payload["procedencia"]
    vivas = [v for p, v in CURVA if p <= "2025-12"]
    assert pr["n_observaciones_rf"] == len(vivas)
    assert pr["rf_pct"] == [min(vivas), max(vivas)]
    assert pr["rf_ventana"] == ["2025-01", "2025-10"]


def test_SUPUESTOS_declara_las_FECHAS_de_la_ventana_de_la_Rf(db) -> None:
    from modules.valuation.products import SECCION_SUPUESTOS
    sup = _por_http(db)["narratives"][SECCION_SUPUESTOS]
    fila = next(linea for linea in sup.splitlines() if linea.startswith("| Rf"))
    assert "2025-01" in fila and "2025-10" in fila, fila
    assert "2026" not in fila, "la ventana cita una observación posterior al corte"
