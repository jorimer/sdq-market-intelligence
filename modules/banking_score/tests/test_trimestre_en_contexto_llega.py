"""El rótulo de cada trimestre llega a las DOS superficies: la instrucción del texto y la tabla.

Un rótulo bien computado que ni el modelo ni el lector ven es el defecto de «servir el dato no
alcanza»: el informe seguiría destacando el trimestre que más movió, sea o no un hallazgo.
"""
from reportlab.platypus import Paragraph, Table

from modules.banking_score.reports.pdf_generator import (
    _build_anio_por_trimestres_tables, _get_styles)


def test_la_plantilla_del_anio_lleva_la_instruccion_de_los_trimestres():
    from shared.narrative.claude_engine import THIN_TEMPLATES, TRAMOS_EN_CONTEXTO_EN_EL_TEXTO

    assert "se_destaca" in TRAMOS_EN_CONTEXTO_EN_EL_TEXTO
    assert "estacionalidad" in TRAMOS_EN_CONTEXTO_EN_EL_TEXTO
    assert TRAMOS_EN_CONTEXTO_EN_EL_TEXTO in THIN_TEMPLATES["anio_por_trimestres"]
    # «El 75 % de las instituciones» salió en el PDF regenerado de Santa Cruz: la mitad
    # central contiene la MITAD, y la instrucción lo nombra.
    assert "MITAD" in TRAMOS_EN_CONTEXTO_EN_EL_TEXTO
    assert "no el 75" in TRAMOS_EN_CONTEXTO_EN_EL_TEXTO


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
            {"tramo": "primer trimestre", "score_desde": 64.36, "score_hasta": 67.31,
             "cambio": 2.95, "direccion": "al alza"},
            {"tramo": "segundo trimestre", "score_desde": 67.31, "score_hasta": 63.86,
             "cambio": -3.45, "direccion": "a la baja"},
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
        {"tramo": "primer trimestre", "score_desde": 1.0, "score_hasta": 2.0,
         "cambio": 1.0, "direccion": "al alza"}]}
    texto = " | ".join(_celdas(_build_anio_por_trimestres_tables(dentro, _get_styles())))
    assert "atípico" not in texto and "ordinario" not in texto
