"""La trayectoria dice cuántos horizontes se esperan y por qué falta el que falta.

El BVAR declara dos horizontes con track record (`HORIZONTES_CON_TRACK_RECORD`), y la sección
de escenarios se toma tres párrafos en sostener que del tercero en adelante NO son
pronósticos. Así que el lector cuenta dos y encuentra uno.

La causa existía y estaba escrita en el lugar equivocado: `emision` la registra en sus
`motivos` —«el período ya había cerrado al corte; el bloque va atrasado respecto de la fecha
de emisión»— y eso vive en el resultado de la operación, que no llega a ningún informe. El
motor sabía por qué faltaba y la superficie no se enteraba. Es la misma forma que el mapa
sectorial que desaparecía del Deep Dive prometiendo diecisiete secciones y entregando
dieciséis.

No hace falta persistir nada: la causa se reconstruye del propio ledger. Si +2T apunta a
2026-Q3, el bloque terminaba en 2026-Q1 y +1T apuntaba a 2026-Q2; y estaba vencido si su
cierre es anterior al `as_of` de la fila, que es la condición de `_es_hacia_adelante`
reproducida, no copiada de un texto.
"""
from modules.macro_monitor import products_forecast as pf
from modules.macro_monitor.forecasting import bvar
from shared.data import medida_de_pronostico as med

SERIE = "bcrd.xls.pib_2018.serie_original_indice"


def _fila(*, horizonte, h, as_of="2026-09-06", punto=5.5672, ancla=False):
    return {"serie": SERIE, "horizonte": horizonte, "h": h, "punto": punto,
            "medida": med.YOY_PCT, "intervalos": [[0.80, punto - 2, punto + 2]],
            "modelo": "bvar_minnesota.5v.v1", "as_of": as_of, "ancla": ancla,
            "motivo": "" if ancla else "0 observaciones fuera de muestra", "n_oos": 0}


# ── El caso real de producción ──────────────────────────────────────────────────────


def test_declara_el_horizonte_que_falta_y_POR_QUE(fixture=None):
    """Sólo +2T, y el trimestre de +1T ya había cerrado al corte."""
    md = pf._md_trayectoria({"proyecciones": [_fila(horizonte="2026-Q3", h=2)]})
    assert "+1T" in md, f"no nombra el horizonte que falta:\n{md}"
    assert "2026-Q2" in md, f"no nombra el trimestre al que apuntaba:\n{md}"
    assert "2026-Q1" in md, f"no dice dónde terminaba el bloque:\n{md}"
    assert "cerrado" in md.lower() or "cerró" in md.lower(), (
        f"no dice que el período ya había cerrado:\n{md}")


def test_dice_que_NO_es_una_falla_sino_un_pronostico_evitado():
    """La distinción que decide cómo se lee: un pronóstico de un período cerrado se evaluaría
    contra un dato que ya existía cuando se escribió. No falta uno — se evitó uno que habría
    inflado el track record con retrospectiva."""
    md = pf._md_trayectoria({"proyecciones": [_fila(horizonte="2026-Q3", h=2)]})
    assert "retrospectiva" in md.lower() or "ya existía" in md.lower(), md


def test_dice_CUANDO_vuelve():
    """Una ausencia sin fecha de vuelta se lee como permanente."""
    md = pf._md_trayectoria({"proyecciones": [_fila(horizonte="2026-Q3", h=2)]})
    assert "BCRD" in md and "2026-Q2" in md, md


def test_cuenta_cuantos_se_ESPERAN():
    """El lector cuenta. Si el informe no cuenta primero, la diferencia parece una errata.

    Se compara contra la frase RENDERIZADA de la constante y no contra `str(2)`: «2» aparece
    dentro de «2026-Q3» y la primera versión de este test pasaba en verde contra el código
    que no declaraba nada.
    """
    md = pf._md_trayectoria({"proyecciones": [_fila(horizonte="2026-Q3", h=2)]})
    esperada = pf._TRAYECTORIA_INCOMPLETA.format(
        presentes=1, esperados=bvar.HORIZONTES_CON_TRACK_RECORD, fin_bloque="2026-Q1")
    assert esperada in md, f"no cuenta los horizontes:\n{md}"


# ── El contraejemplo, que es lo que impide que el aviso sea ruido ───────────────────


def test_con_LOS_DOS_horizontes_no_declara_NADA():
    """Sin esto, un aviso impreso siempre pasaría todos los tests de arriba y la sección
    avisaría de una ausencia que no existe."""
    md = pf._md_trayectoria({"proyecciones": [
        _fila(horizonte="2026-Q3", h=1, as_of="2026-06-06"),
        _fila(horizonte="2026-Q4", h=2, as_of="2026-06-06"),
    ]})
    assert "+1T" not in md and "falta" not in md.lower(), (
        f"declaró una ausencia con los dos horizontes presentes:\n{md}")


# ── Lo que NO se inventa ────────────────────────────────────────────────────────────


def test_un_horizonte_ausente_SIN_vencer_no_se_le_atribuye_el_rezago():
    """El corte es anterior al cierre de 2026-Q2, así que ese horizonte no faltó por vencido.
    Se declara la ausencia y no se le inventa una causa."""
    md = pf._md_trayectoria({"proyecciones": [_fila(horizonte="2026-Q3", h=2,
                                                    as_of="2026-04-15")]})
    assert "+1T" in md, f"no declaró la ausencia:\n{md}"
    assert "retrospectiva" not in md.lower(), (
        f"le atribuyó el rezago del bloque a un horizonte que no estaba vencido:\n{md}")


def test_sin_h_no_se_declara_nada():
    """Sin la distancia no se puede computar el trimestre objetivo. Callar es correcto;
    inventar el horizonte que falta, no."""
    fila = _fila(horizonte="2026-Q3", h=2)
    fila.pop("h")
    md = pf._md_trayectoria({"proyecciones": [fila]})
    assert "+1T" not in md, md


# ── Y el payload lo tiene que llevar ────────────────────────────────────────────────


def test_el_payload_lleva_la_DISTANCIA_de_cada_proyeccion():
    """Es lo único que faltaba para reconstruir la causa desde el ledger."""
    import pytest
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from modules.macro_monitor.forecasting import ledger
    from shared.database.base import Base

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    try:
        ledger.registrar(db, model_id="bvar_minnesota.5v.v1", target_series=SERIE,
                         horizon="2099-Q4", as_of="2026-09-06", point=5.5, h=2,
                         measure=med.YOY_PCT, intervals=[[0.80, 3.5, 7.5]])
        payload = pf.MacroForecastProduct(db)._payload(db)
        assert payload["proyecciones"][0]["h"] == 2
        assert pytest  # el import existe para el fixture de sesión, no se usa aparte
    finally:
        db.close()
