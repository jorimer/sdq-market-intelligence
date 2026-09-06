"""Una fila `scored` sin error no vale cero: se VETA del conjunto y se lista.

`track_record` hacía `sq_error or 0.0` y `abs_error or 0.0`: una fila puntuada a la que le
faltara el error entraba al RMSE como un acierto perfecto y sumaba al `n_oos`. Hoy ninguna
fila puntuada llega sin error —`puntuar_pendientes` escribe los dos— pero el `or 0.0` es
rellenar la brecha, que es lo que la doctrina prohíbe: un dato ausente es `None`, y lo vetado
se LISTA para que la ausencia se vea.
"""
import pytest

from modules.macro_monitor.forecasting import ledger
from modules.macro_monitor.forecasting.models import ForecastLog
from modules.macro_monitor.forecasting.tests.test_ledger import (  # noqa: F401
    MODELO, SERIE, _observado, _registrar, db)
from shared.data import medida_de_pronostico as med

BT = f"{MODELO}|{SERIE}|{med.LEVEL}|+1T"


def test_una_fila_scored_sin_error_no_entra_al_conjunto_y_se_lista(db):
    _registrar(db, horizon="2026-Q1", as_of="2025-11-15", point=100.0)
    _registrar(db, horizon="2026-Q2", as_of="2026-02-15", point=100.0)
    _observado(db, "2026-Q1", 99.0)
    assert ledger.puntuar_pendientes(db) == 1
    # La segunda queda puntuada SIN error — una fila rota, como la que un backfill o una
    # migración a medias podrían dejar.
    rota = db.query(ForecastLog).filter_by(horizon="2026-Q2").one()
    rota.status = "scored"
    rota.sq_error = None
    rota.abs_error = None
    db.commit()
    tr = ledger.track_record(db, BT)
    assert tr["n_oos"] == 1, "la fila sin error contó como evidencia"
    assert tr["rmse"] == pytest.approx(1.0) and tr["mae"] == pytest.approx(1.0), (
        "la fila sin error entró al promedio como error cero")
    assert tr["sin_error"] == ["2026-Q2"], "lo vetado no se lista"


def test_con_TODAS_las_filas_sin_error_el_conjunto_esta_vacio_y_lo_dice(db):
    _registrar(db, horizon="2026-Q1", as_of="2025-11-15", point=100.0)
    f = db.query(ForecastLog).one()
    f.status = "scored"
    db.commit()
    tr = ledger.track_record(db, BT)
    assert tr["n_oos"] == 0 and tr["rmse"] is None
    assert tr["sin_error"] == ["2026-Q1"]
