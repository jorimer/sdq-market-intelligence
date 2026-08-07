"""Perfil SDQ en seguros — Ejecución y Resiliencia sobre el panel del ISF (Fase 2).

Implementa el mapeo del spec §5.9. No sustituye al ISF: es una lectura distinta del mismo
motor, con dos diferencias de fondo respecto de la agregación única.

**Ejecución mide el CICLO, no el último año.** El combined ratio se promedia sobre 3-5
ejercicios porque con un solo año una catástrofe puntual reclasifica a una aseguradora bien
manejada. Medido sobre el panel 2018-2024: la mediana de |último año − promedio 5 años| es
**5.9 puntos**, con casos de 21 — Aseguradora Agropecuaria da 71.5% en 2024 y 92.5% en el
promedio, o sea "excelente" o "mediocre" según qué corte se mire.

**Resiliencia cambia de composición respecto del ISF:**

* Entra la **volatilidad del loss ratio**. El ISF mide el NIVEL de siniestralidad; el nivel y
  su estabilidad son cosas distintas, y para aguantar un shock importa la segunda.
* Entra el **reaseguro** — cuánto riesgo transfiere y cuánto recupera.
* **Sale Escala.** Lo que convierte tamaño en resiliencia real no son los activos totales
  sino cuánto y cómo reasegura la aseguradora (spec §5.5): con reaseguro medido de verdad,
  el proxy deja de hacer falta.
"""
import math
from typing import Any, Dict, List, Optional, Sequence

# Ventana del ciclo de suscripción. 5 es el techo del rango que pide el spec (3-5); con
# menos de 3 ejercicios no se emite Ejecución — un "promedio" de dos años no es un ciclo.
VENTANA_CICLO = 5
MIN_EJERCICIOS = 3

# Pesos DENTRO de cada eje (ya renormalizados; suman 1.0 por eje). Heredan la proporción
# del ISF donde existe correspondencia: solvencia sigue siendo la dimensión dominante de
# Resiliencia, y el peso que tenía Escala pasa a Reaseguro, que es lo que Escala proxeaba.
#
# ⚠️ Estos pesos son JUICIO EXPERTO, no derivados empíricamente — igual que los 35/20/15/15/15
# del ISF (spec §5.7). Cualquier superficie de metodología visible al cliente debe decirlo.
PESOS_RESILIENCIA = {"solvencia": 0.47, "liquidez": 0.20, "reaseguro": 0.20,
                     "volatilidad_loss": 0.13}

# ── Anclajes, derivados del panel 2018-2024 (33 aseguradoras, outliers extremos excluidos)

# Combined ratio: 100% = breakeven técnico, el único corte con ancla económica real del
# spec. Piso y techo en el p90/p10 observados (1.139 y 0.660).
CR_PEOR, CR_REF, CR_MEJOR = 1.15, 1.00, 0.66

# Volatilidad del loss ratio (σ sobre la ventana): mediana 0.043, p90 0.130.
VOL_PEOR, VOL_MEJOR = 0.130, 0.023

# Reaseguro: U INVERTIDA. Cesión casi nula = desprotección; cesión casi total = fronting
# (la aseguradora no retiene riesgo real y su margen depende de un tercero).
#
# **La banda intermedia NO pretende discriminar.** Entre 5% y 70% de cesión el dato no
# distingue "sano" de "muy sano" —haría falta un benchmark del mercado reasegurador
# caribeño que no tenemos (spec §5.5)— así que ahí el score es plano. Se penaliza solo lo
# que es interpretable con lo que hay: los dos extremos. Medido: 8 de 33 aseguradoras ceden
# menos del 5% y 3 ceden más del 70%.
CESION_MIN_SANA, CESION_MAX_SANA = 0.05, 0.70
CESION_DESPROTEGIDA, CESION_FRONTING = 0.0, 1.0


def _lineal(v: float, peor: float, mejor: float) -> float:
    """0 en *peor*, 100 en *mejor*. Funciona en ambos sentidos (mejor puede ser < peor)."""
    if peor == mejor:
        return 50.0
    return max(0.0, min(100.0, (v - peor) / (mejor - peor) * 100.0))


def _tramos(v: float, peor: float, ref: float, mejor: float) -> float:
    """Dos tramos con la referencia económica en 50 — mismo patrón que el ISF y el motor
    de banca. Para el combined ratio, ``ref`` es el breakeven técnico (100%)."""
    if (mejor < ref and v >= peor) or (mejor > ref and v <= peor):
        return 0.0
    hacia_abajo = mejor < ref  # combined ratio: menos es mejor
    en_tramo_bajo = v >= ref if hacia_abajo else v <= ref
    if en_tramo_bajo:
        return max(0.0, min(50.0, (v - peor) / (ref - peor) * 50.0))
    return max(50.0, min(100.0, 50.0 + (v - ref) / (mejor - ref) * 50.0))


def score_reaseguro(cesion: Optional[float]) -> Optional[float]:
    """U invertida sobre la cesión de prima. Ver ``CESION_MIN_SANA``.

    >>> score_reaseguro(0.0) < 50      # no transfiere riesgo: desprotección
    True
    >>> score_reaseguro(0.30) == 100.0 # banda intermedia: plana a propósito
    True
    >>> score_reaseguro(0.95) < 50     # fronting: no retiene riesgo real
    True
    """
    if cesion is None:
        return None
    if cesion < CESION_MIN_SANA:
        return round(_lineal(cesion, CESION_DESPROTEGIDA, CESION_MIN_SANA), 1)
    if cesion > CESION_MAX_SANA:
        return round(_lineal(cesion, CESION_FRONTING, CESION_MAX_SANA), 1)
    return 100.0


def metricas_del_ciclo(ejercicios: Dict[str, Dict[str, float]]) -> Optional[Dict[str, Any]]:
    """Métricas de la ventana a partir de ``{año: {loss, exp, cesion, ...}}``.

    Devuelve None si no hay ejercicios suficientes: sin ciclo no se fabrica un promedio.
    """
    años = sorted(ejercicios)[-VENTANA_CICLO:]
    if len(años) < MIN_EJERCICIOS:
        return None
    losses = [ejercicios[a]["loss"] for a in años]
    combineds = [ejercicios[a]["loss"] + ejercicios[a]["exp"] for a in años]
    n = len(losses)
    media = sum(losses) / n
    return {
        "años": años,
        "combined_promedio": sum(combineds) / len(combineds),
        "loss_volatilidad": math.sqrt(sum((x - media) ** 2 for x in losses) / n),
        "cesion_promedio": sum(ejercicios[a].get("cesion", 0.0) for a in años) / n,
    }


def calcular_ejes(ciclo: Optional[Dict[str, Any]],
                  indice_solvencia: Optional[float],
                  indice_liquidez: Optional[float]) -> Dict[str, Any]:
    """Los dos ejes de una aseguradora. Cada dimensión ausente se declara, no se rellena."""
    from modules.insurance_intel.scoring.isf import DIMENSIONS, _absolute

    ejecucion = None
    dims: Dict[str, Optional[float]] = {}
    if ciclo:
        ejecucion = round(_tramos(ciclo["combined_promedio"], CR_PEOR, CR_REF, CR_MEJOR), 1)
        dims["volatilidad_loss"] = round(
            _lineal(ciclo["loss_volatilidad"], VOL_PEOR, VOL_MEJOR), 1)
        dims["reaseguro"] = score_reaseguro(ciclo["cesion_promedio"])

    # Solvencia y liquidez reusan los anclajes ya recalibrados del ISF: son la MISMA
    # dimensión medida igual, y duplicar su calibración las haría divergir con el tiempo.
    for clave, raw in (("solvencia", indice_solvencia), ("liquidez", indice_liquidez)):
        spec = next((d for d in DIMENSIONS if d["key"] == clave), None)
        dims[clave] = round(_absolute(raw, spec), 1) if (raw is not None and spec) else None

    presentes = {k: v for k, v in dims.items() if v is not None and k in PESOS_RESILIENCIA}
    peso = sum(PESOS_RESILIENCIA[k] for k in presentes)
    resiliencia = (round(sum(presentes[k] * PESOS_RESILIENCIA[k] for k in presentes) / peso, 1)
                   if peso > 0 else None)
    return {
        "ejecucion": ejecucion,
        "resiliencia": resiliencia,
        "cobertura_resiliencia": round(peso, 2),
        "dimensiones": dims,
        "ejercicios": ciclo["años"] if ciclo else [],
        "combined_promedio": round(ciclo["combined_promedio"], 4) if ciclo else None,
    }


def correlacion(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Gate del §8, idéntico al de banca — reexportado para no duplicar el criterio."""
    from modules.banking_score.scoring.perfil_sdq import correlacion as _c
    return _c(xs, ys)


def bandas_ejecucion_por_combined(combined: Optional[float]) -> Optional[str]:
    """Banda de Ejecución sobre el combined ratio promedio.

    A diferencia de banca —donde Ejecución es relativa al panel por falta de un breakeven—
    en seguros SÍ existe el ancla económica: 100% es el punto donde la suscripción deja de
    dar pérdida. Los otros dos cortes salen de los cuartiles observados (p25 0.778,
    p75 1.010), no de números redondos.
    """
    if combined is None:
        return None
    if combined < 0.78:
        return "Sobresaliente"
    if combined < 1.00:
        return "Competitiva"
    if combined < 1.14:
        return "Rezagada"
    return "Deficiente"
