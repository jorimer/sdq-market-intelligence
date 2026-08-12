"""La tabla del PDF tiene que aplicar la MISMA regla de comparabilidad que el contexto de IA.

El 2026-08-12 se arregló el rank en `ai_context` y NO la tabla renderizada, que es otra ruta
de código. El PDF salió contradiciéndose: el texto decía «27 comparables» y la tabla de al lado
listaba a Reaseguradora Santo Domingo (74,6, tres dimensiones de cinco) en el segundo puesto,
sin marca. Es el patrón que este repo repite —el guard en un motor y no en el otro— cometido
dentro del PR que venía a cerrarlo.
"""
import inspect

from modules.insurance_intel.products import _PEER_DIVISOR, _peer_table


def _peer(slug, isf, cov, **dims):
    return {"slug": slug, "name": slug.title(), "overall_score": isf, "coverage": cov,
            "dimensions": [{"key": k, "score": v} for k, v in dims.items()]}


_COMPLETO = dict(solvencia=71.0, siniestralidad=59.0, liquidez=43.0,
                 escala=96.0, resultado_tecnico=92.0)
_PARCIAL = dict(solvencia=91.0, siniestralidad=None, liquidez=66.0,
                escala=45.0, resultado_tecnico=None)

_PANEL = [
    _peer("cuna", 82.4, 1.0, **_COMPLETO),
    _peer("reasanto", 74.6, 0.65, **_PARCIAL),      # parcial, ISF alto
    _peer("mapfre", 71.1, 1.0, **_COMPLETO),
    _peer("crecer", 70.4, 0.65, **_PARCIAL),
]


def test_las_parciales_no_se_ordenan_entre_las_completas():
    _, rows = _peer_table(_PANEL)
    nombres = [r[0] for r in rows[1:]]
    assert nombres.index("Cuna") < nombres.index(_PEER_DIVISOR)
    assert nombres.index("Mapfre") < nombres.index(_PEER_DIVISOR)
    # Reasanto tiene el 2º ISF del panel y aun así va DESPUÉS del divisor.
    assert nombres.index("Reasanto") > nombres.index(_PEER_DIVISOR)
    assert nombres.index("Crecer") > nombres.index(_PEER_DIVISOR)


def test_las_parciales_no_se_ocultan():
    """Omitirlas las haría desaparecer sin aviso, que es peor que mostrarlas mal."""
    _, rows = _peer_table(_PANEL)
    assert "Reasanto" in [r[0] for r in rows]


def test_el_titulo_declara_el_criterio_y_los_dos_universos():
    titulo, _ = _peer_table(_PANEL)
    assert "2 con las cinco dimensiones medidas" in titulo
    assert "2 de cobertura parcial" in titulo


def test_un_panel_sin_parciales_no_muestra_divisor():
    titulo, rows = _peer_table([_peer("a", 80.0, 1.0, **_COMPLETO),
                                _peer("b", 70.0, 1.0, **_COMPLETO)])
    assert _PEER_DIVISOR not in [r[0] for r in rows]
    assert "cobertura parcial" not in titulo


def test_el_recorte_no_es_silencioso():
    """Un top-N sin avisar se lee como si fuera el panel entero."""
    panel = [_peer(f"e{i}", 90.0 - i, 1.0, **_COMPLETO) for i in range(14)]
    titulo, rows = _peer_table(panel)
    assert "no listadas" in titulo
    assert len(rows) - 1 < len(panel)


def test_usa_LA_MISMA_funcion_que_el_contexto_de_ia():
    """Dos implementaciones del mismo criterio divergen; este test exige una sola."""
    src = inspect.getsource(_peer_table)
    assert "universo_comparable" in src, (
        "la tabla debe consultar el helper compartido, no reimplementar el filtro")
    assert "overall_score\") is not None" not in src, (
        "quedó el filtro viejo: ordena scores de cobertura distinta")
