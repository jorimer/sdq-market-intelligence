"""El indicador `leverage` NO es el ratio de apalancamiento de Basilea, y el rótulo lo dice.

**El hallazgo.** El denominador que sirve el SIB (`exposicion_total`) son los «ACTIVOS Y
CONTINGENTES PONDERADOS POR RIESGO CREDITICIO Y RIESGO DE MERCADO»: está **ponderado por
riesgo**. El ratio de Basilea es, por definición, NO ponderado — ése es su propósito entero,
ser el contrapeso no-sensible-al-riesgo de los índices de solvencia. Llamarlo «Apalancamiento
(Basilea)» en un documento de rating es un error que nota cualquier analista.

**La consecuencia medible.** Comparte numerador con `tier1_ratio` y denominador con
`solvencia`, así que cuando el capital primario iguala al patrimonio técnico —entidad sin
capital secundario— COINCIDE exactamente con la solvencia. Medido en producción: **9 de 43**
entidades calificadas al corte más reciente; Asociación Bonao lo cumple en 2025-03 y 2025-12.

**Lo que NO se encontró**, y queda escrito porque era mi hipótesis: no infla el score. Los
tres indicadores discriminan parecido (score medio 78,4 con σ 13,0, contra 73,4 de solvencia
y 75,8 de tier1), porque el techo `hi=30.2` se calibró sobre los valores reales.

**Lo que queda abierto y NO se toca acá:** tres de los cinco indicadores de Solidez miden
capital sobre activos ponderados. Recomponer la dimensión movería el score de TODAS las
entidades y de todos los informes ya publicados — es una decisión de metodología con su
changelog, no una nota al pie. Mientras tanto, el informe lo DECLARA.
"""
from modules.banking_score.reports.pdf_generator import _nota_de_capital_redundante
from modules.banking_score.scoring.indicator_detail import INDICATOR_META
from modules.banking_score.scoring.weights import SOLIDEZ_INDICATORS


def test_el_rotulo_no_invoca_a_BASILEA():
    label = INDICATOR_META["leverage"]["label"]
    assert "asilea" not in label, (
        f"«{label}» invoca a Basilea para un ratio PONDERADO por riesgo. El de Basilea es "
        "deliberadamente no ponderado.")
    assert "ponderad" in label.lower(), f"el rótulo debe decir qué mide: «{label}»"


def test_la_glosa_declara_que_COMPARTE_con_los_otros_dos():
    """Un rótulo correcto no basta: el lector tiene que saber que no es evidencia nueva."""
    que = INDICATOR_META["leverage"]["que"].lower()
    assert "coincide" in que or "comparte" in que


def test_los_tres_ratios_de_capital_siguen_en_SOLIDEZ():
    """Fija el hecho que motiva la nota: si algún día se recompone la dimensión, este test
    falla y obliga a revisar la nota y el changelog de metodología."""
    assert {"solvencia", "tier1_ratio", "leverage"} <= set(SOLIDEZ_INDICATORS)
    assert len(SOLIDEZ_INDICATORS) == 5


def test_la_nota_aparece_cuando_los_valores_COINCIDEN():
    inds = {"solvencia": {"raw": 26.8415}, "leverage": {"raw": 26.8415}}
    nota = _nota_de_capital_redundante(inds)
    assert nota and "mismo hecho" in nota


def test_la_nota_NO_aparece_cuando_difieren():
    """El contrapeso: una nota permanente se vuelve ruido y se deja de leer."""
    assert _nota_de_capital_redundante(
        {"solvencia": {"raw": 22.87}, "leverage": {"raw": 23.62}}) is None
    assert _nota_de_capital_redundante({}) is None
    assert _nota_de_capital_redundante({"solvencia": {"raw": None}, "leverage": {}}) is None
