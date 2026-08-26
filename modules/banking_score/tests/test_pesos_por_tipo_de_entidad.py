"""REGLA ESTRUCTURAL: el peso de un sub-componente sale del TIPO de entidad, no de la
constante base — salvo excepción declarada.

`SUB_COMPONENT_WEIGHTS` es el perfil de **Banca Múltiple**. Cinco de los seis tipos tienen el
suyo, así que usarla como si fuera universal produce el número equivocado en 75 de las 92
entidades calificadas.

El defecto llegó a un informe entregado (Insight de Asociación Bonao, 2025-12-31): la tabla de
sub-componentes decía 40/30/15/10/5 —que dan un score global de 60.07— mientras la portada del
MISMO documento mostraba 61.24, que es lo que dan los pesos reales de una AAP (38/34/13/10/5).
La narrativa, que sí recibe los pesos del tipo, escribió «38%» y «34%»: el texto tenía razón y
la tabla mentía. Lo delató la aritmética, no una revisión de estilo.

El motor de scoring NUNCA estuvo mal (`run_scoring` usa `get_sub_component_weights`). El
defecto vivía en las superficies que lo muestran —y en una que lo COMPUTA: la simulación
what-if recibía `bank_id` y jamás consultaba el tipo, así que devolvía un score calculado con
los pesos de otra clase de entidad.
"""
import ast
import pathlib

import pytest

from modules.banking_score.models.models import BankType
from modules.banking_score.scoring.engine import simulate_from_scores
from modules.banking_score.scoring.weights import (SUB_COMPONENT_WEIGHTS,
                                                   get_sub_component_weights)

_MODULO = pathlib.Path(__file__).resolve().parents[1]

#: Usos LEGÍTIMOS de la constante base, con su motivo. Cualquier otro rompe el test.
_EXCEPCIONES = {
    # Es donde se define y donde se arman los perfiles por tipo.
    "scoring/weights.py": "define la constante y los perfiles",
    # `_weighted_overall(sub_scores, weights=None)`: el `or` es el default de una función que
    # recibe los pesos ya resueltos; `run_scoring` le pasa los del tipo.
    "scoring/engine.py": "default de una función que recibe los pesos ya resueltos",
    # El documento de CRITERIOS describe la metodología general y DECLARA que son los pesos
    # base de Banca Múltiple, con su propia sección «Recalibración por tipo de entidad».
    "reports/criteria_doc.py": "metodología general; declara que son los pesos base",
    # Solo usa las CLAVES (el orden de los ejes del radar), que son iguales en todos los tipos.
    "reports/pdf_generator.py": "solo las claves, para el orden del radar",
}


def _archivos_que_la_usan():
    out = {}
    for f in _MODULO.rglob("*.py"):
        if "/tests/" in str(f):
            continue
        texto = f.read_text()
        if "SUB_COMPONENT_WEIGHTS" not in texto:
            continue
        # Solo usos REALES: una mención en un comentario o docstring no cuenta.
        arbol = ast.parse(texto, filename=str(f))
        usos = sum(1 for n in ast.walk(arbol)
                   if isinstance(n, ast.Name) and n.id == "SUB_COMPONENT_WEIGHTS")
        if usos:
            out[str(f.relative_to(_MODULO))] = usos
    return out


# ── Prueba NEGATIVA ────────────────────────────────────────────────────

def test_hay_perfiles_de_peso_que_difieren_de_la_base():
    """Si todos los tipos tuvieran los mismos pesos, este test entero no probaría nada."""
    distintos = [t.value for t in BankType
                 if get_sub_component_weights(t.value) != dict(SUB_COMPONENT_WEIGHTS)]
    assert len(distintos) >= 4, f"se esperaban varios perfiles propios; hay {distintos}"


# ── La regla ───────────────────────────────────────────────────────────

def test_nadie_usa_la_constante_base_sin_excepcion_declarada():
    intrusos = {f: n for f, n in _archivos_que_la_usan().items() if f not in _EXCEPCIONES}
    assert not intrusos, (
        "Estos archivos usan el perfil de Banca Múltiple como si fuera universal. Usá "
        f"get_sub_component_weights(entity_type), o declará la excepción con su motivo: {intrusos}")


def test_la_lista_de_excepciones_no_crece_sola():
    """Una lista de excepciones que se llena sola vuelve inútil al test de arriba."""
    assert set(_EXCEPCIONES) == {
        "scoring/weights.py", "scoring/engine.py",
        "reports/criteria_doc.py", "reports/pdf_generator.py"}


# ── Las tres superficies que fallaban ──────────────────────────────────

def test_LA_TABLA_del_pdf_usa_los_pesos_del_tipo():
    """El caso literal de Bonao."""
    from modules.banking_score.reports.pdf_generator import (_build_sub_scores_table,
                                                             _get_styles)

    def celdas(entity_type):
        els = _build_sub_scores_table({"solidez": 74.64, "calidad": 72.15}, _get_styles(),
                                      entity_type)
        tabla = next(e for e in els if hasattr(e, "_cellvalues"))
        return [c.getPlainText() if hasattr(c, "getPlainText") else str(c)
                for c in (fila[1] for fila in tabla._cellvalues[1:])]

    assert celdas("aap")[:2] == ["38%", "34%"], celdas("aap")
    assert celdas("banca_multiple")[:2] == ["40%", "30%"]


def test_la_SIMULACION_computa_con_los_pesos_del_tipo():
    """Acá el peso no se muestra: computa el score que devuelve la ruta what-if."""
    # Scores de INDICADOR (no de sub-componente): son la entrada real de la ruta what-if.
    # Con nombres de sub-componente todo sale 0 y el test pasaría sin probar nada.
    scores = {"solvencia": 80.0, "tier1_ratio": 80.0, "leverage": 80.0,
              "cobertura_provisiones": 50.0, "patrimonio_activos": 60.0,
              "morosidad": 80.0, "pct_cartera_a": 80.0, "concentracion_top10": 80.0,
              "hhi_sectorial": 0.0, "castigos_pct": 80.0, "exposicion_re": 95.0,
              "migracion": 86.0, "roa": 13.0, "roe": 15.0, "margen_financiero": 17.0,
              "cost_to_income": 0.0, "liquidez_inmediata": 41.0, "ltd": 97.0,
              "liquidez_ajustada": 34.0, "hhi_ingresos": 23.0}
    base = simulate_from_scores(dict(scores))["overall_score"]
    aap = simulate_from_scores(dict(scores), "aap")["overall_score"]
    assert base > 0, "la simulación no computó nada; el test no probaría el peso"
    assert base != aap, "la simulación ignora el tipo de entidad"


@pytest.mark.parametrize("tipo,esperado", [("aap", 0.38), ("cambiaria", 0.35),
                                           ("banca_multiple", 0.40)])
def test_el_panel_in_app_declara_el_peso_del_tipo(tipo, esperado):
    """`build_entity_insight` sirve el peso que el frontend renderiza junto a cada dimensión."""
    assert get_sub_component_weights(tipo)["solidez"] == pytest.approx(esperado)
