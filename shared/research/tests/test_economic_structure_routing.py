"""Regresión del Hallazgo 3 del piloto P4-P6: economic_structure no se ruteaba con preguntas
naturales de crecimiento + motores sectoriales (solo con las frases técnicas exactas). Era fallo
de RUTEO (el dato ya existe en modules/sector_intel/structure_product.py), no falta de dato."""
from shared.research.resolve import context_axes, detect_axes, resolve_targets


def _resolved(question):
    """Todos los ejes que resuelve la pregunta: primarios + entidades + contexto."""
    t = resolve_targets(question, db=None)
    return set(t.axes) | set(t.context) | {e.sector_key for e in t.entities}


# ─── preguntas reales que fallaban en el piloto (2/2) ──────────────────
def test_pilot_growth_and_sectoral_drivers_routes_economic_structure():
    q = ("cuál es la perspectiva de crecimiento económico de República Dominicana para 2026 "
         "y cuáles son sus principales motores sectoriales")
    resolved = _resolved(q)
    assert "economic_structure" in resolved   # antes NO aparecía → tabla de 17 sectores no salía
    assert "macro" in resolved                 # crecimiento/PIB sigue ruteando macro


def test_pilot_variant_motores_del_crecimiento():
    # variante en lenguaje natural: "motores del crecimiento" sin frase técnica.
    resolved = _resolved("qué sectores impulsan el crecimiento de la economía dominicana")
    assert "economic_structure" in resolved


# ─── lenguaje natural detecta economic_structure como PRIMARIO (parte a) ─
def test_natural_language_lifts_economic_structure_to_primary():
    for q in ("cuáles son los motores sectoriales del crecimiento",
              "qué sector crece más en el país",
              "aporte de cada sector al PIB",
              "contribución sectorial al valor agregado"):
        assert "economic_structure" in detect_axes(q), q


# ─── las frases técnicas siguen funcionando (no-regresión) ─────────────
def test_technical_phrases_still_route():
    assert "economic_structure" in detect_axes("estructura de la economía dominicana")
    assert "economic_structure" in detect_axes("valor agregado por sector")


# ─── (parte b) contexto sectorial condicionado, no en cada macro ───────
def test_sectoral_context_added_to_macro_only_with_sectoral_intent():
    # macro + intención sectorial → economic_structure entra como contexto.
    ctx = context_axes("perspectiva macro por sector de la economía", ["macro"])
    assert "economic_structure" in ctx


def test_generic_macro_question_does_not_inflate_with_structure():
    # macro genérica SIN intención sectorial → NO se agrega economic_structure (anti-inflación).
    ctx = context_axes("cuál es la perspectiva de inflación y reservas para 2026", ["macro"])
    assert "economic_structure" not in ctx
