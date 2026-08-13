"""Dirección invertida enunciada como BRECHA — el punto ciego que dejó pasar el LTD de BPD.

**El caso.** Rating Completo BPD 2025-12-31, §5 (Liquidez), entregado a Grupo Popular:

> «…lo que sitúa este indicador 7.31 puntos porcentuales POR DEBAJO del promedio de bancos
> múltiples —señal de una estructura de fondeo relativamente conservadora».

El LTD de 92.45% está 7.31 pp POR ENCIMA del promedio de pares (85.14%). La §7 del MISMO
documento lo dice bien, y con la lectura correcta: un LTD mayor que el de los pares reduce
—no amplía— el margen para absorber retiros. Al comité le llegó la conclusión invertida.

**Por qué se escapó a las tres capas.** (1) El contexto SÍ traía la dirección resuelta
(`direccion: "por encima"`, `brecha_pp: 7.31`): el modelo copió la magnitud y redactó la
palabra. (2) El juez LLM no lo marcó. (3) El chequeo determinista exige que el VALOR de la
referencia esté citado en la oración, y esta frase nunca menciona el 85.14 — enuncia la
brecha y nombra la base. Esa forma era invisible, y es justo la que el contexto induce al
servir `brecha_pp`.

**La cura tiene dos mitades y las dos se prueban acá:** la dirección se sirve como cláusula
ya redactada (`lectura`) para que copiar sea más fácil que redactar, y el detector aprende
la forma-brecha, que reconoce la referencia por su ETIQUETA en vez de por su valor.
"""
import pytest

from shared.narrative.derived import comparaciones_vs_referencia
from shared.narrative.numeric_guard import (
    deterministic_direction_errors, deterministic_direction_gap_errors,
)

# Cifras REALES del corte 2025-12-31 de BPD y las referencias de su tabla §8.
_VALORES = {
    "ltd": 92.4512, "liquidez_inmediata": 20.682, "morosidad": 1.53, "solvencia": 15.37,
    "roe": 24.2092, "roa": 3.5415, "cost_to_income": 46.4102, "margen_financiero": 9.54,
}
_REFERENCIAS = {
    "ltd": {"promedio del sistema": 79.0, "promedio de bancos múltiples": 85.14},
    "liquidez_inmediata": {"promedio del sistema": 20.91,
                           "promedio de bancos múltiples": 30.52},
    "morosidad": {"promedio del sistema": 1.99, "promedio de bancos múltiples": 1.92},
    "solvencia": {"promedio del sistema": 17.71, "promedio de bancos múltiples": 14.92},
    "roe": {"promedio del sistema": 7.85, "promedio de bancos múltiples": 12.79},
    "roa": {"promedio del sistema": 1.4, "promedio de bancos múltiples": 1.63},
    "cost_to_income": {"promedio del sistema": 81.54, "promedio de bancos múltiples": 55.95},
    "margen_financiero": {"promedio del sistema": 9.24,
                          "promedio de bancos múltiples": 7.63},
}


@pytest.fixture
def ctx():
    return {"comparaciones": comparaciones_vs_referencia(_VALORES, _REFERENCIAS)}


# ── La mitad preventiva: la relación se sirve REDACTADA, no en piezas ──

def test_la_comparacion_trae_la_clausula_completa(ctx):
    """Servir `direccion` y `brecha_pp` por separado deja media relación en manos del
    modelo, y esa mitad es la que erra. `lectura` viaja armada."""
    ltd = next(c for c in ctx["comparaciones"]
               if c["indicador"] == "ltd" and "múltiples" in c["referencia"])
    assert ltd["lectura"] == (
        "por encima del promedio de bancos múltiples en 7.31 puntos porcentuales")
    # El signo se conserva en `brecha_pp`: el chequeo determinista lo lee.
    assert ltd["brecha_pp"] == 7.31


def test_en_linea_no_fuerza_un_lado():
    """Con brecha inmaterial la cláusula NO elige lado: forzarlo es cómo se eligió el
    equivocado en el ICAP de 16.44 vs 16.5 (bug 2026-08-06)."""
    comp = comparaciones_vs_referencia(
        {"solvencia": 16.44}, {"solvencia": {"promedio del sistema": 16.5}})[0]
    assert comp["direccion"] == "en línea"
    assert comp["lectura"].startswith("en línea con el promedio del sistema")
    assert "por encima" not in comp["lectura"] and "por debajo" not in comp["lectura"]


# ── La mitad detectora: la forma-brecha deja de ser invisible ──

def test_caza_la_frase_exacta_entregada_al_cliente(ctx):
    """SENSOR DE REGRESIÓN: la oración literal del Rating Completo BPD §5."""
    texto = (
        "El principal factor al alza es la relación préstamos-depósitos (LTD), que en 92.45% "
        "obtiene un score de 98.62: la entidad financia su cartera sin depender excesivamente "
        "del fondeo captado, lo que sitúa este indicador 7.31 puntos porcentuales por debajo "
        "del promedio de bancos múltiples —señal de una estructura de fondeo relativamente "
        "conservadora frente al grupo de pares.")
    flags = deterministic_direction_errors(ctx, texto)
    assert flags and "ltd" in flags[0] and "por encima" in flags[0]


@pytest.mark.parametrize("texto,indicador", [
    # Puntos BÁSICOS: son centésimas de pp. Sin convertir la unidad, el pareo contra
    # `brecha_pp` no casa nunca y el chequeo falla en silencio.
    ("La morosidad se ubica 46 puntos básicos por encima del promedio del sistema.",
     "morosidad"),
    # La misma base nombrada de otra manera ("grupo de" en vez de "promedio de"): frase real
    # del informe. Por eso la etiqueta se parea por su cola distintiva.
    ("La liquidez inmediata acusa 9.84 puntos porcentuales por encima del grupo de bancos "
     "múltiples.", "liquidez_inmediata"),
    ("El ICAP queda 2.34 puntos porcentuales por encima del promedio del sistema.",
     "solvencia"),
    ("El ROE de la entidad está 16.36 puntos por debajo del promedio del sistema.", "roe"),
])
def test_caza_otras_formas_invertidas(ctx, texto, indicador):
    flags = deterministic_direction_gap_errors(ctx, texto)
    assert flags and indicador in flags[0], f"no marcó: {texto}"


# ── Falsos positivos: pasajes CORRECTOS de los dos PDFs entregados ──
#
# Un guard que grita en falso se vuelve ruido que se aprende a ignorar. Estos son literales
# de los informes reales, con la dirección bien puesta.

@pytest.mark.parametrize("texto", [
    "El ICAP de 15.37% está 2.34 puntos porcentuales por debajo del promedio del sistema "
    "(17.71%) y solo 0.45 puntos por encima del promedio de bancos múltiples (14.92%), con "
    "un margen de 5.37 puntos sobre el mínimo regulatorio de 10%.",
    "La liquidez inmediata (20.7%) está en línea con el promedio del sistema aunque 9.84 "
    "puntos porcentuales por debajo del grupo de bancos múltiples.",
    "La tasa de morosidad (1.53%) se ubica 46 puntos básicos por debajo del promedio del "
    "sistema.",
    "El principal impulsor es la rentabilidad sobre activos (ROA): 3.54%, con 2.14 puntos "
    "porcentuales por encima del promedio del sistema.",
    "La rentabilidad sobre patrimonio (ROE) de 24.21% amplía esa distancia: 16.36 puntos "
    "sobre el sistema y 11.42 sobre pares.",
    "Una relación costos-ingresos de 46.41% —35 puntos por debajo del sistema y casi 10 por "
    "debajo de bancos múltiples— indica que la base de gastos absorbe menos ingreso.",
    "El margen de intermediación neto de 9.54% está por encima del promedio del sistema "
    "(9.24%) y significativamente por encima del promedio de bancos múltiples (7.63%).",
    # Umbral PROSPECTIVO: no es una comparación contra referencia.
    "Si el margen financiero neto cae por debajo de 8.5% —aproximándose al promedio de "
    "bancos múltiples de 7.63%— la lectura cambia.",
    # "N puntos sobre 100" es una escala, no una brecha contra una base.
    "El margen obtiene apenas 25.18 puntos sobre 100 en la rúbrica de calificación.",
    # Deltas temporales: no hay referencia de panel involucrada.
    "La calificación ha cedido 2.54 puntos en ocho trimestres, de 74.30 en marzo de 2024 a "
    "71.76 en diciembre de 2025.",
    "La cobertura cedió 150 puntos porcentuales en ocho trimestres, arrastrando su score de "
    "100.0 a 84.98.",
    "La suma de los tres riesgos a la baja suma -3.30 puntos en la calificación global.",
])
def test_no_marca_prosa_correcta(ctx, texto):
    assert deterministic_direction_errors(ctx, texto) == []


def test_sin_comparaciones_no_inventa_veredicto():
    """PRUEBA NEGATIVA: sin `comparaciones` el chequeo no tiene con qué decidir y debe
    devolver [] por AUSENCIA DE INSUMO, no por haber verificado. Distinguirlo importa —
    `0 flags` que en realidad significa «no miré nada» ya dejó un guard entero mudo."""
    texto = "El LTD se sitúa 7.31 puntos porcentuales por debajo del promedio de pares."
    assert deterministic_direction_gap_errors({}, texto) == []
    assert deterministic_direction_gap_errors({"comparaciones": []}, texto) == []
