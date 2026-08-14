"""El chequeo determinista estaba MUERTO en la ruta de reportes, y ciego a dos formas.

**El caso.** Deep Dive BPD 2025-12-31, §11 (Recomendación): «una caída sostenida de fortaleza
financiera —**ocho puntos en doce meses**—». El score global cedió 2.39 en doce meses y ningún
sub-componente cae más de 6.8. La cifra no tiene referente, y estaba en la sección que el
comité lee para decidir.

**Tres fallas independientes, cada una suficiente por sí sola** (medidas antes del arreglo):

| forma                                   | ruta insight | ruta reportes |
|-----------------------------------------|--------------|---------------|
| «88.40 en marzo 2024» (cifra inventada) | la caza      | **no la ve**  |
| «88.40 en marzo DE 2024»                | **no la ve** | **no la ve**  |
| «ocho puntos en doce meses»             | **no la ve** | **no la ve**  |

1. La ruta de reportes nombra su serie `trayectoria_score`/`period_end`; el detector leía
   `tendencia_score`/`periodo`. Ningún patrón encontraba su insumo, así que los seis
   devolvían `[]` — no por haber verificado, sino por no tener qué mirar. La única capa viva
   en los informes de cliente era el juez LLM.
2. El separador entre mes y año no aceptaba la preposición, que es como se escribe en español.
3. Las cifras en PALABRAS eran invisibles: el detector busca dígitos.

Es la misma familia que el LTD del 2026-08-13: el guard atado a una FORMA DE SUPERFICIE en
vez de al hecho.
"""
import pytest

from shared.narrative.derived import resumen_de_trayectoria
from shared.narrative.numeric_guard import deterministic_unsupported, guard_coverage

# Serie REAL del score global de BPD (verificada contra producción).
SERIE = [("2024-03-31", 74.30), ("2024-06-30", 74.81), ("2024-09-30", 74.32),
         ("2024-12-31", 74.15), ("2025-03-31", 73.84), ("2025-06-30", 73.72),
         ("2025-09-30", 72.22), ("2025-12-31", 71.76)]


@pytest.fixture(params=["reportes", "insight"])
def ctx(request):
    """LAS DOS formas de contexto. Parametrizado a propósito: el defecto era que una de
    ellas no se reconocía, y un test escrito sobre una sola forma no lo habría visto."""
    if request.param == "reportes":
        return {"overall_score": 71.76,
                "sub_components": {"solidez": 69.97, "calidad": 71.99},
                "pesos_sub_componentes": {"solidez": 0.40, "calidad": 0.30},
                "trayectoria_score": [{"period_end": p, "score": s} for p, s in SERIE]}
    return {"score_global": 71.76,
            "sub_componentes": [{"score": 69.97, "peso": 0.40},
                                {"score": 71.99, "peso": 0.30}],
            "tendencia_score": [{"periodo": p, "score": s} for p, s in SERIE]}


# ── La prueba negativa: distinguir «limpio» de «no miré nada» ──

def test_el_guard_declara_que_encontro_su_insumo(ctx):
    """SIN esto, `[] hallazgos` no distingue haber verificado de no tener con qué. Es el
    modo de falla que dejó el detector mudo en los informes de cliente durante meses."""
    cov = guard_coverage(ctx)
    assert cov["score"], "el guard no encuentra el score en esta forma de contexto"
    assert cov["serie"], "el guard no encuentra la serie en esta forma de contexto"
    assert cov["sub_componentes"], "el guard no puede computar aportes en esta forma"


def test_sin_insumo_la_cobertura_lo_dice():
    """Un contexto vacío NO debe parecer verificado."""
    cov = guard_coverage({})
    assert not any(cov.values())
    assert deterministic_unsupported({}, "el score cayó 40 puntos en tres trimestres") == []


# ── Las tres formas que se escapaban ──

def test_caza_la_cifra_inventada_con_preposicion(ctx):
    """«marzo DE 2024» — la forma natural en español, y la que usan estos informes."""
    flags = deterministic_unsupported(ctx, "el score fue de 88.40 en marzo de 2024")
    assert flags and "88.40" in flags[0] and "74.3" in flags[0]


def test_caza_la_cifra_inventada_sin_preposicion(ctx):
    flags = deterministic_unsupported(ctx, "el score fue de 88.40 en marzo 2024")
    assert flags and "88.40" in flags[0]


def test_caza_la_caida_en_palabras(ctx):
    """SENSOR DE REGRESIÓN: la frase literal de la §11 entregada al cliente."""
    flags = deterministic_unsupported(
        ctx, "presenta una caída sostenida de fortaleza financiera —ocho puntos en doce "
             "meses— y ocupa el puesto 14 de 16 en liquidez")
    assert flags and "2.39" in flags[0], flags


@pytest.mark.parametrize("txt", [
    "el score cayó 8 puntos en 12 meses",
    "una caída de ocho puntos en cuatro trimestres",
    "cede nueve puntos en seis trimestres",
])
def test_caza_otras_magnitudes_falsas(ctx, txt):
    assert deterministic_unsupported(ctx, txt), f"no marcó: {txt}"


# ── Las dos anclas del informe real: ambas CORRECTAS, no se marcan ──

@pytest.mark.parametrize("txt", [
    # §1 real: ancla en el PICO (74.81 de junio-24), seis trimestres → 3.05. Correcto.
    "La trayectoria del score global (de 74.81 en junio 2024 a 71.76 al cierre de 2025) no "
    "señala deterioro agudo, pero sí un deslizamiento persistente de aproximadamente tres "
    "puntos en seis trimestres.",
    # §9 real: ancla en el INICIO DE VENTANA (74.30 de marzo-24), ocho cortes. Correcto.
    "la trayectoria descendente e ininterrumpida del score a lo largo de ocho cortes "
    "consecutivos —de 74.30 a 71.76— no es una fluctuación coyuntural.",
    # Cifras exactas con decimales.
    "el score cede 2.54 puntos en siete trimestres desde el primer corte de la ventana.",
    "la calificación ha cedido 3.05 puntos en seis trimestres desde el pico.",
])
def test_no_marca_las_anclas_correctas(ctx, txt):
    assert deterministic_unsupported(ctx, txt) == []


def test_marca_el_conteo_de_ventana_equivocado(ctx):
    """Si una sección dice «seis cortes» entre dos valores que distan ocho, se marca —
    aunque las dos cifras sean reales. Es el chequeo que faltaba para que las dos anclas
    del informe no puedan divergir en silencio."""
    flags = deterministic_unsupported(
        ctx, "a lo largo de seis cortes consecutivos —de 74.30 a 71.76— el deterioro")
    assert flags and "8 cortes" in flags[0], flags


# ── El resumen que evita que cada sección elija su propia ancla ──

def test_el_resumen_nombra_LAS_DOS_anclas():
    r = resumen_de_trayectoria([{"period_end": p, "score": s} for p, s in SERIE])
    assert r["n_cortes"] == 8 and r["n_trimestres"] == 7
    assert r["primer_corte"] == {"periodo": "2024-03-31", "score": 74.3}
    assert r["pico"] == {"periodo": "2024-06-30", "score": 74.81}
    assert r["ultimo_corte"] == {"periodo": "2025-12-31", "score": 71.76}
    assert r["delta_desde_el_inicio"] == -2.54
    assert r["delta_desde_el_pico"] == -3.05
    # La frase servida obliga a decir CUÁL ancla se usa: es lo que faltaba en el informe.
    assert "PRIMER corte" in r["lectura"] and "PICO" in r["lectura"]
    assert "decí cuál ancla usás" in r["lectura"]


def test_el_resumen_no_inventa_con_un_solo_punto():
    assert resumen_de_trayectoria([{"period_end": "2025-12-31", "score": 71.76}]) is None
    assert resumen_de_trayectoria([]) is None


# ── Falsos positivos: el informe discute SEIS series a la vez ──
#
# Al conectar el detector a la ruta de reportes aparecieron tres marcas sobre prosa
# CORRECTA, todas del mismo origen: los patrones asumían que cada cifra era del score
# GLOBAL, cuando el informe también narra las cinco dimensiones. Un guard que grita en
# falso se vuelve ruido que se aprende a ignorar, así que la regla es: sin respaldo solo
# si NINGUNA serie conocida lo sostiene.

_SUB = {  # trayectorias reales de las cinco dimensiones, mismos ocho cortes
    "solidez": [73.5, 73.39, 73.0, 72.0, 71.0, 72.1, 70.6, 69.97],
    "calidad": [77.5, 77.8, 77.1, 78.78, 77.0, 77.0, 73.3, 71.99],
    "eficiencia": [76.5, 76.6, 76.8, 76.7, 78.5, 78.6, 78.0, 78.09],
    "liquidez": [71.0, 71.2, 71.6, 69.1, 74.3, 68.0, 70.1, 71.49],
    "diversificacion": [65.5, 65.7, 65.9, 66.4, 63.0, 64.2, 65.5, 66.23],
}


@pytest.fixture
def ctx_completo():
    return {
        "overall_score": 71.76,
        "sub_components": {k: v[-1] for k, v in _SUB.items()},
        "pesos_sub_componentes": {"solidez": .40, "calidad": .30, "eficiencia": .15,
                                  "liquidez": .10, "diversificacion": .05},
        "trayectoria_score": [{"period_end": p, "score": s} for p, s in SERIE],
        "trayectoria_sub": {k: [{"period_end": SERIE[i][0], "score": v}
                                for i, v in enumerate(vals)] for k, vals in _SUB.items()},
    }


@pytest.mark.parametrize("txt", [
    # Valores de SUB-COMPONENTE atados a su período: correctos, no son el score global.
    "una tendencia descendente desde 73.39 en junio de 2024 hasta 69.97 al cierre de 2025 "
    "en el sub-componente de solidez.",
    "la calidad de activos: desde 78.78 en diciembre de 2024 hasta 71.99 doce meses después.",
    # Caída de una DIMENSIÓN, no del global.
    "la calidad de activos —que ya cedió 6.79 puntos en score durante 2025— continúa.",
    "una pérdida de 6.79 puntos en cuatro cortes.",
    # "corte" y "trimestre" se usan como sinónimos: el off-by-one de un sinónimo no es un
    # hallazgo, es ruido.
    "el score cede 3.05 puntos en seis cortes desde el pico.",
])
def test_no_marca_prosa_de_sub_componente(ctx_completo, txt):
    assert deterministic_unsupported(ctx_completo, txt) == []


def test_sigue_marcando_la_cifra_sin_referente(ctx_completo):
    """Con las seis series a la vista, 'ocho puntos' no lo sostiene ninguna: ni el global
    (2.39) ni la dimensión que más cae (calidad, 6.79)."""
    flags = deterministic_unsupported(
        ctx_completo, "presenta una caída sostenida de fortaleza financiera —ocho puntos "
                      "en doce meses— y ocupa el puesto 14 de 16 en liquidez")
    assert len(flags) == 1 and "ninguna serie" in flags[0] and "6.79" in flags[0]
