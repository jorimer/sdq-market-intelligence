"""El rótulo de cada trimestre llega a las DOS superficies: la instrucción del texto y la tabla.

Un rótulo bien computado que ni el modelo ni el lector ven es el defecto de «servir el dato no
alcanza»: el informe seguiría destacando el trimestre que más movió, sea o no un hallazgo.
"""
from reportlab.platypus import Paragraph, Table

from modules.banking_score.reports.pdf_generator import (
    _build_anio_por_trimestres_tables, _get_styles)


def test_la_plantilla_del_anio_lleva_la_instruccion_de_los_trimestres():
    """Desde «hechos y lectura» (2026-09-15) la mitad central y sus cifras las escribe el código
    (`test_hechos_y_lectura`); la plantilla solo pide destacar lo que el rótulo marca como
    hallazgo, y sin cifras."""
    from shared.narrative.claude_engine import LECTURA_SIN_CIFRAS_EN_EL_TEXTO, THIN_TEMPLATES

    plantilla = THIN_TEMPLATES["anio_por_trimestres"]
    assert LECTURA_SIN_CIFRAS_EN_EL_TEXTO in plantilla
    assert "'es_hallazgo'" in plantilla and "'rotulo'" in plantilla


def _celdas(elementos):
    for e in elementos:
        if isinstance(e, Table):
            for fila in e._cellvalues:
                for c in fila:
                    yield c.getPlainText() if isinstance(c, Paragraph) else str(c)
        elif isinstance(e, Paragraph):
            yield e.getPlainText()


def test_la_tabla_de_tramos_muestra_la_lectura_de_cada_trimestre():
    dentro = {
        "anio": 2025,
        "tramos": [
            {"tramo": "primer trimestre", "score_global_desde": 64.36,
             "score_global_hasta": 67.31, "cambio": 2.95, "direccion": "al alza"},
            {"tramo": "segundo trimestre", "score_global_desde": 67.31,
             "score_global_hasta": 63.86, "cambio": -3.45, "direccion": "a la baja"},
        ],
        "contexto_de_los_tramos": [
            {"tramo": "primer trimestre", "rotulo": "ordinario"},
            {"tramo": "segundo trimestre", "rotulo": "atípico frente a su historia"},
        ],
    }
    texto = " | ".join(_celdas(_build_anio_por_trimestres_tables(dentro, _get_styles())))
    assert "Lectura" in texto
    assert "atípico frente a su historia" in texto
    assert "Solo un trimestre atípico es un hallazgo" in texto


def test_sin_contexto_la_tabla_no_inventa_una_lectura():
    dentro = {"anio": 2025, "tramos": [
        {"tramo": "primer trimestre", "score_global_desde": 1.0, "score_global_hasta": 2.0,
         "cambio": 1.0, "direccion": "al alza"}]}
    texto = " | ".join(_celdas(_build_anio_por_trimestres_tables(dentro, _get_styles())))
    assert "atípico" not in texto and "ordinario" not in texto
