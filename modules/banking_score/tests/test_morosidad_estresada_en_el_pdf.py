"""La tabla de las DOS moras en el PDF: la superficie que el comité lee, además del texto.

La doctrina lo pide explícito: el contexto de IA y la tabla renderizada son superficies
distintas, y arreglar una sola deja el documento contradiciéndose. La estresada ya llega al
texto; estos tests piden la tabla.
"""
from reportlab.platypus import Paragraph, Table

from modules.banking_score.reports.pdf_generator import _build_estresada_table, _get_styles

_BLOQUE = {
    "corte": "2025-12-31", "disponible": True,
    "definicion": "Morosidad estresada según la Superintendencia de Bancos (I.027).",
    "nota_de_carteras": "Salen de dos cuadros distintos de la SIB y no se restan entre sí.",
    "morosidad_convencional_publicada_de_la_entidad_pct": 2.97,
    "morosidad_estresada_de_la_entidad_pct": 7.61,
    "componentes_de_la_estresada_de_la_entidad": [
        {"componente": "cartera vencida", "pct_de_la_cartera_de_la_entidad": 2.12},
        {"componente": "castigos de los últimos 12 meses", "pct_de_la_cartera_de_la_entidad": 3.01},
    ],
    "lo_que_la_mora_convencional_no_ve_pp": 5.49,
    "mediana_estresada_del_resto_del_sistema_pct": 5.0,
    "diferencia_con_la_mediana_del_resto_pp": 2.61,
    "n_entidades_del_resto_del_sistema": 30,
    "universo_del_resto_del_sistema": "instituciones de crédito supervisadas por la SIB",
}


def _texto(elementos) -> str:
    partes = []
    for e in elementos:
        if isinstance(e, Paragraph):
            partes.append(e.getPlainText())
        elif isinstance(e, Table):
            for fila in e._cellvalues:
                for celda in fila:
                    partes.append(celda.getPlainText() if isinstance(celda, Paragraph)
                                  else str(celda))
    return " | ".join(partes)


def test_la_tabla_trae_las_dos_moras_el_desglose_y_la_referencia():
    els = _build_estresada_table(_BLOQUE, _get_styles())
    assert any(isinstance(e, Table) for e in els), "no se dibujó ninguna tabla"
    t = _texto(els)
    for esperado in ("Mora convencional publicada", "2.97", "Morosidad estresada (SIB)", "7.61",
                     "castigos de los últimos 12 meses", "3.01", "+5.49", "5.00", "+2.61",
                     "no entra al score", "no se restan"):
        assert esperado in t, esperado


def test_sin_estresada_se_declara_el_motivo_y_no_hay_tabla():
    motivo = "La SIB no publicó todos los componentes."
    els = _build_estresada_table({"corte": "2025-12-31", "disponible": False,
                                  "motivo": motivo}, _get_styles())
    assert els, "la ausencia tiene que declararse, no desaparecer"
    assert not any(isinstance(e, Table) for e in els)
    assert motivo in _texto(els)


def test_sin_bloque_no_se_dibuja_nada():
    assert _build_estresada_table(None, _get_styles()) == []
