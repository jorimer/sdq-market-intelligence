"""La Revisión Anual — el año de una ENTIDAD, que hasta ahora no existía.

Lo que estos tests fijan no es «la función devuelve un dict». Es cada hecho que el informe al
corte NO daba, y que fue la razón de construir el producto:

  * el CAMINO, no solo los extremos — una entidad que cayó y se recuperó cierra igual que una
    que nunca se movió, y no tuvieron el mismo año;
  * los cambios de banda DURANTE el año, no apertura contra cierre;
  * el BALANCE de apertura contra cierre, porque solvencia y liquidez son STOCKS y su valor de
    diciembre no dice nada del año sin el nivel del que partió;
  * que NO exista un score anual promediado;
  * que un año sin cerrar no se emita.
"""
import datetime

import pytest

from modules.banking_score.reports import revision_anual as _mod
from modules.banking_score.reports.revision_anual import revision_anual

_CORTES = ["2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]


class _Bank:
    id = "b1"
    name = "Entidad de Prueba"


def _traj(scores, bandas=None, indicadores=None, cortes=None):
    """`entity_trajectories` sintética: overall + indicadores, en los cortes dados."""
    cortes = cortes or _CORTES
    bandas = bandas or [None] * len(cortes)
    overall = [{"period_end": c, "score": s, "banda_resiliencia": b}
               for c, s, b in zip(cortes, scores, bandas) if s is not None]
    inds = {}
    for clave, serie in (indicadores or {}).items():
        inds[clave] = [{"period_end": c, "raw": v, "score": None}
                       for c, v in zip(cortes, serie) if v is not None]
    return {"n_periods": len(overall), "overall": overall, "sub": {}, "indicators": inds}


@pytest.fixture()
def con_trayectoria(monkeypatch):
    def _instalar(traj, percentiles=None):
        monkeypatch.setattr(
            "modules.banking_score.scoring.amplitude.entity_trajectories",
            lambda db, bank, n=8, as_of=None: traj)
        monkeypatch.setattr(
            "modules.banking_score.scoring.amplitude.period_percentiles",
            lambda db, bank, period_end: percentiles or {})
        return revision_anual(object(), _Bank(), 2025)
    return _instalar


# ── El camino, que es la razón de ser del producto ─────────────────────

def test_un_VALLE_INTERMEDIO_se_declara(con_trayectoria):
    """El hecho que la foto de diciembre no da.

    Esta entidad cierra en 70, igual que como abrió — y en el medio cayó a 55. El informe al
    corte muestra «sin cambio»; el año fue cualquier cosa menos plano.
    """
    out = con_trayectoria(_traj([70.0, 62.0, 55.0, 63.0, 70.0]))
    cam = out["camino"]
    assert cam["valle_intermedio"] is True
    assert cam["valle"]["corte"] == "2025-06-30"
    assert cam["amplitud"] == 15.0
    assert "recuperación" in cam["lectura"]


def test_una_caida_MONOTONA_no_se_llama_recuperacion(con_trayectoria):
    """El contrapeso: sin él, `valle_intermedio` podría estar siempre en verdadero."""
    out = con_trayectoria(_traj([70.0, 66.0, 62.0, 58.0, 54.0]))
    cam = out["camino"]
    assert cam["valle_intermedio"] is False
    assert cam["valle"]["corte"] == "2025-12-31"
    assert cam["trimestres_a_la_baja"] == 4 and cam["trimestres_al_alza"] == 0


def test_un_movimiento_INMATERIAL_no_cuenta_como_trimestre_al_alza(con_trayectoria):
    out = con_trayectoria(_traj([70.0, 70.2, 70.1, 70.3, 70.2]))
    assert out["camino"]["trimestres_al_alza"] == 0
    assert out["camino"]["trimestres_a_la_baja"] == 0


# ── El score del año es el del CIERRE ──────────────────────────────────

def test_NO_hay_score_anual_promediado(con_trayectoria):
    """Un promedio no coincidiría con ningún score publicado y daría dos respuestas a
    «cuál es el score de esta entidad en el año»."""
    out = con_trayectoria(_traj([70.0, 60.0, 50.0, 60.0, 80.0]))
    assert out["cierre"]["score"] == 80.0
    assert out["cambio_score"] == 10.0
    promedio = (70.0 + 60.0 + 50.0 + 60.0 + 80.0) / 5
    assert promedio not in [v for k, v in out.items() if isinstance(v, (int, float))]
    assert "no se promedian" in out["regla_del_score"]


# ── Las bandas, DURANTE el año ─────────────────────────────────────────

def test_una_banda_que_baja_y_VUELVE_deja_dos_cambios(con_trayectoria):
    """Apertura contra cierre diría «sin cambio»: es el año que un comité querría conocer."""
    out = con_trayectoria(_traj(
        [70.0, 62.0, 55.0, 63.0, 70.0],
        bandas=["Sólida", "Sólida", "Adecuada", "Adecuada", "Sólida"]))
    assert [(c["corte"][:7], c["desde"], c["hasta"]) for c in out["cambios_de_banda"]] == [
        ("2025-06", "Sólida", "Adecuada"), ("2025-12", "Adecuada", "Sólida")]


def test_sin_cambios_de_banda_la_lista_va_vacia(con_trayectoria):
    out = con_trayectoria(_traj([70.0] * 5, bandas=["Sólida"] * 5))
    assert out["cambios_de_banda"] == []


# ── El balance: apertura contra cierre ─────────────────────────────────

def test_el_balance_da_APERTURA_y_cierre_de_cada_indicador(con_trayectoria):
    """El dato que no existía en ningún informe: los stocks solo se veían al cierre."""
    out = con_trayectoria(_traj(
        [70.0] * 5,
        indicadores={"solvencia": [15.0, 14.5, 14.0, 13.8, 13.2],
                     "morosidad": [2.0, 2.2, 2.5, 2.8, 3.1]}))
    por_ind = {f["indicador"]: f for f in out["balance"]}
    assert por_ind["solvencia"]["apertura"] == 15.0
    assert por_ind["solvencia"]["cierre"] == 13.2
    assert por_ind["solvencia"]["cambio"] == -1.8
    assert por_ind["solvencia"]["subio"] is False
    assert por_ind["morosidad"]["subio"] is True


def test_un_indicador_sin_APERTURA_no_se_inventa(con_trayectoria):
    """Media comparación no es una comparación: se omite, no se rellena con el cierre."""
    out = con_trayectoria(_traj(
        [70.0] * 5, indicadores={"solvencia": [None, 14.5, 14.0, 13.8, 13.2]}))
    assert out["balance"] == []


# ── El año tiene que haber cerrado ─────────────────────────────────────

def test_un_anio_SIN_diciembre_no_se_emite(con_trayectoria):
    """Misma regla que el anuario del sistema, y por el mismo motivo: sin el cierre esto es
    un tramo con el encabezado de un año."""
    assert con_trayectoria(_traj([70.0, 71.0, 72.0, 73.0, None])) is None


def test_un_corte_INTERMEDIO_ausente_se_declara_y_no_veta(con_trayectoria):
    """El año sigue siendo resumible cierre a cierre; lo que cambia es que las anclas del
    camino son de lo que se vio."""
    out = con_trayectoria(_traj([70.0, None, 72.0, None, 74.0]))
    assert out is not None
    assert out["cortes_faltantes"] == ["2025-03-31", "2025-09-30"]


def test_solo_el_cierre_anterior_y_diciembre_no_alcanza_para_el_camino(con_trayectoria):
    """Con dos puntos hay cambio, pero no hay CAMINO: no se fabrica un pico ni un valle."""
    out = con_trayectoria(_traj([70.0, None, None, None, 74.0]))
    assert out is not None and out["cambio_score"] == 4.0
    assert out["camino"] is None


# ── El registro del tipo, que a este repo se le olvida ─────────────────

def test_la_revision_anual_esta_registrada_en_TODAS_sus_superficies():
    """Al anuario le faltaron CUATRO registros, de a uno, y ninguno falló: cada uno lo hacía
    desaparecer en una superficie distinta."""
    from modules.banking_score.models.models import ReportType
    from modules.banking_score.reports.narrative import (REPORT_SECTIONS,
                                                         _CEREBRO_TEMPLATES,
                                                         _SECTION_TO_TEMPLATE)
    from modules.banking_score.reports.pdf_generator import REPORT_TYPE_LABELS
    from shared.narrative.claude_engine import THIN_TEMPLATES

    assert ReportType.revision_anual.value == "revision_anual"
    assert REPORT_SECTIONS["revision_anual"] == ["revision_anual"]
    plantilla = _SECTION_TO_TEMPLATE["revision_anual"]
    assert plantilla in THIN_TEMPLATES, "la plantilla no existe: saldría al relleno estático"
    assert plantilla in _CEREBRO_TEMPLATES, "iría por la ruta legacy y saldría hueca"
    assert REPORT_TYPE_LABELS["revision_anual"] == "Revisión Anual"


def test_los_cortes_del_anio_son_el_cierre_anterior_mas_cuatro():
    assert _mod._cortes_del_anio(2025) == _CORTES
    assert datetime.date.fromisoformat(_CORTES[0]).year == 2024
