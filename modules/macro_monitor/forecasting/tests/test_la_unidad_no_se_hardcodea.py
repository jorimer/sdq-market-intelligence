"""Ninguna superficie decide por su cuenta en qué unidad está el punto de una proyección.

El ledger ya lo declara (`ForecastLog.measure`) y `ProjectionMeta` lo transporta. Lo que
falta vigilar es que las superficies lo LEAN en vez de suponerlo — y suponían:

* `products_forecast._md_trayectoria` escribía ``f"{d['punto']:.2f} %"``, con el «%»
  **hardcodeado**. Acertaba por casualidad: acierta mientras la única medida sea `dlog_pct`,
  y el día que entre una proyección en nivel publica un índice de 133 como «133 %».
* `_md_escenarios`, lo mismo.
* El titular del informe (`f"{punto:.2f}%"`), lo mismo.
* La etiqueta de la señal proyectada nombraba la serie —un ÍNDICE de volumen— al lado de un
  valor que es una VARIACIÓN.
* Y la muestra curada, que es la vidriera del producto, enseñaba ``"serie": "pib_real"``: el
  identificador que no existe y que dejaba las filas sin poder puntuarse nunca.

Un literal vuelve. Por eso hay un test estructural al final: la lección escrita ya falló
siete veces en este repo.
"""
import pytest

from modules.macro_monitor import products_forecast as pf
from shared.data import medida_de_pronostico as med

SERIE = "bcrd.xls.pib_2018.serie_original_indice"


def _payload(medida=med.DLOG_PCT):
    return {
        "proyecciones": [
            {"serie": SERIE, "horizonte": "2026-Q3", "punto": 3.41, "medida": medida,
             "intervalos": [[0.80, 2.11, 4.71]], "modelo": "bvar_minnesota.5v.v1",
             "as_of": "2026-08-20", "ancla": True, "motivo": "", "n_oos": 14},
        ],
        "escenarios": [
            {"horizonte": "2027-Q1", "punto": 2.94, "medida": medida,
             "intervalos": [[0.80, 0.71, 5.17]]},
        ],
    }


# ── Las tablas del producto ─────────────────────────────────────────────────────────


def test_la_trayectoria_declara_la_unidad_del_punto():
    md = pf._md_trayectoria(_payload())
    assert med.COMO_SE_LEE[med.DLOG_PCT] in md, (
        f"la tabla publica un punto sin decir en qué unidad está:\n{md}")


def test_la_trayectoria_de_un_NIVEL_no_lo_publica_como_porcentaje():
    """El caso que el «%» hardcodeado rompe: un índice de volumen servido como «3,41 %»."""
    md = pf._md_trayectoria(_payload(med.LEVEL))
    assert "3.41 %" not in md, (
        f"publicó un nivel con el sufijo de porcentaje:\n{md}")
    assert med.COMO_SE_LEE[med.LEVEL] in md


def test_los_escenarios_declaran_la_unidad():
    md = pf._md_escenarios(_payload())
    assert med.COMO_SE_LEE[med.DLOG_PCT] in md, md


def test_los_escenarios_de_un_NIVEL_no_lo_publican_como_porcentaje():
    assert "2.94 %" not in pf._md_escenarios(_payload(med.LEVEL))


# ── La vidriera ─────────────────────────────────────────────────────────────────────


def test_la_muestra_curada_declara_la_medida_de_cada_punto():
    faltan = [d for d in pf._SAMPLE_PAYLOAD["proyecciones"] + pf._SAMPLE_PAYLOAD["escenarios"]
              if d.get("medida") not in med.MEDIDAS]
    assert not faltan, f"la muestra publica puntos sin medida declarada: {faltan}"


def test_la_muestra_curada_no_ensena_un_identificador_ROTO():
    """`pib_real` es el nombre de la variable en el bloque del BVAR, no un `series_code`. La
    vidriera del producto no puede enseñar el identificador que dejaba las filas sin poder
    puntuarse nunca."""
    series = {d["serie"] for d in pf._SAMPLE_PAYLOAD["proyecciones"]}
    series |= {d["serie"] for d in pf._SAMPLE_PAYLOAD["desempeno"]}
    assert "pib_real" not in series, (
        "la muestra curada enseña «pib_real» como si fuera una serie observable")


# ── El literal vuelve ───────────────────────────────────────────────────────────────


def _porcentajes_pegados_al_punto(fuente: str):
    """El `%` literal que sigue INMEDIATAMENTE a un `punto` interpolado, leído con `ast`.

    Con `ast` y no con regex por línea: el archivo está lleno de porcentajes legítimos
    —pesos, incidencias, coberturas, «banda 80 %»— y una regex de línea los marca a todos o,
    afinada para esquivarlos, deja de ver el que importa. Lo que se busca es un hecho
    sintáctico preciso: una interpolación del punto seguida de un texto que arranca en «%».
    """
    import ast
    import textwrap

    culpables = []
    for nodo in ast.walk(ast.parse(textwrap.dedent(fuente))):
        if not isinstance(nodo, ast.JoinedStr):
            continue
        for i, pieza in enumerate(nodo.values):
            if not isinstance(pieza, ast.FormattedValue):
                continue
            if "punto" not in ast.unparse(pieza.value):
                continue
            siguiente = nodo.values[i + 1] if i + 1 < len(nodo.values) else None
            texto = siguiente.value if isinstance(siguiente, ast.Constant) else ""
            if str(texto).lstrip().startswith("%"):
                culpables.append(ast.unparse(pieza) + str(texto)[:4])
    return culpables


@pytest.mark.parametrize("funcion", ["_md_trayectoria", "_md_escenarios", "_titular_de"])
def test_ninguna_superficie_escribe_el_signo_de_porcentaje_del_PUNTO(funcion):
    """El «%» del punto se computa de la medida y no se escribe. Un literal vuelve."""
    import inspect

    culpables = _porcentajes_pegados_al_punto(inspect.getsource(getattr(pf, funcion)))
    assert not culpables, (
        f"«{funcion}» decide por su cuenta la unidad del punto: {culpables}")


def test_el_lector_estructural_VE_el_defecto_cuando_ESTA():
    """El mismo lector, contra el código como estaba. Un barrido que no encuentra nada es
    indistinguible de uno que no sabe mirar, y en este repo ya se truncó la lista de un guard
    sin que nada avisara."""
    como_estaba = (
        'def _md_trayectoria(p):\n'
        '    for d in p["proyecciones"]:\n'
        '        lineas.append(f"| {d[\'serie\']} | {d[\'punto\']:.2f} % | fin |")\n'
    )
    assert _porcentajes_pegados_al_punto(como_estaba), (
        "el lector no vio el «%» pegado al punto en el código que SÍ lo tenía: su silencio "
        "sobre el código de hoy no prueba nada")


def test_el_lector_estructural_NO_marca_un_porcentaje_LEGITIMO():
    """«banda 80 %» y los pesos son porcentajes que sí van escritos. Un guard que los marca
    se desactiva a la semana."""
    legitimo = (
        'def _md(p):\n'
        '    return f"| {d[\'punto\']:.2f}{_sufijo_de(d)} | banda 80 % | {s[\'peso\']:.2f} % |"\n'
    )
    assert not _porcentajes_pegados_al_punto(legitimo)
