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

# ── Conversión del combined ratio a la escala 0-100 (spec §5.2) ────────────────
#
# El combined ratio es un porcentaje donde MENOS es mejor; Ejecución en banca, pensiones y
# fiduciarias es un índice 0-100 donde MÁS es mejor, con los cortes de §4 (75/60/45). Sin una
# conversión explícita, seguros quedaba en una escala paralela — y eso rompe la promesa central
# de Perfil SDQ, que es un lenguaje único entre sectores.
#
# La pendiente NO es un número nuevo: sale de los tres cortes que el §5.9 ya fijaba sobre
# combined ratio (90/100/110), que calzan exactamente con los tres límites de banda de §4.
#
#     CR  90% → 75  (borde de Sobresaliente)
#     CR 100% → 60  (borde de Competitiva — breakeven es aceptable, no sobresaliente)
#     CR 110% → 45  (borde de Rezagada)
CR_BREAKEVEN_SCORE = 60.0
CR_PENDIENTE = 1.5

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


def score_ejecucion_desde_combined(combined: Optional[float]) -> Optional[float]:
    """Combined ratio (fracción, 1.0 = 100%) → índice 0-100 donde más es mejor (§5.2).

    ``clamp(60 − 1.5 × (CR% − 100), 0, 100)``. Lineal y anclada en el breakeven: es la función
    que pone a seguros en la MISMA escala y con las MISMAS bandas que los otros tres sectores,
    en vez de una escala paralela sobre porcentajes.

    >>> score_ejecucion_desde_combined(0.90)   # borde de Sobresaliente
    75.0
    >>> score_ejecucion_desde_combined(1.00)   # breakeven → borde de Competitiva
    60.0
    >>> score_ejecucion_desde_combined(1.10)   # borde de Rezagada
    45.0
    """
    if combined is None:
        return None
    pct = combined * 100.0
    return round(max(0.0, min(100.0, CR_BREAKEVEN_SCORE - CR_PENDIENTE * (pct - 100.0))), 1)


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


def siniestros_incurridos(pagados: Optional[float],
                          reservas_actual: Optional[float],
                          reservas_previa: Optional[float]) -> Optional[Dict[str, Any]]:
    """Aproxima los siniestros INCURRIDOS: pagados + variación de reservas técnicas (§5.3).

    La base pagados es **gameable**: demorar el reconocimiento o el pago de reclamaciones
    mejora el loss ratio del ejercicio sin que haya mejorado nada. Los incurridos capturan
    lo que ocurrió, no lo que se desembolsó.

    **La limitación se declara, no se esconde — y está MEDIDA.** ``reservas_tecnicas`` tal
    como se extrae hoy mezcla la reserva de siniestros pendientes con la de riesgos en curso
    (prima no devengada, ``21xx`` + ``22xx``). Sobre el panel 2018-2024, el ajuste sube el
    loss ratio en **35 de 44 aseguradoras** — un sesgo alcista sistemático, no ruido
    simétrico: la prima no devengada crece con la cartera y ese crecimiento se cuela en el
    ajuste como si fuera siniestralidad.

    **Por eso esta función NO alimenta el score.** Se expone como métrica marcada
    (``aproximado=True``), con el ajuste explícito para que quien la consuma pueda decir de
    dónde sale la diferencia. Meterla al índice con este sesgo empeoraría la medición en vez
    de mejorarla — el problema que se quería resolver (una base gameable) se reemplazaría por
    otro (una base sesgada hacia arriba en las aseguradoras que crecen).

    Refinamiento que la habilitaría: que el extractor aísle la sub-cuenta de reserva de
    siniestros pendientes (mismo patrón ``children_sum_where``, descripción tipo
    "RESERVA.*SINIESTRO"). Con eso el ajuste deja de arrastrar el crecimiento de cartera.
    """
    if pagados is None or reservas_actual is None or reservas_previa is None:
        return None
    ajuste = reservas_actual - reservas_previa
    return {
        "incurridos": pagados + ajuste,
        "pagados": pagados,
        "ajuste_reservas": ajuste,
        "aproximado": True,
        "limitacion": ("reservas_tecnicas mezcla siniestros pendientes con riesgos en curso; "
                       "el ajuste se sobreestima si la prima no devengada se mueve por "
                       "crecimiento de cartera"),
    }


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
        ejecucion = score_ejecucion_desde_combined(ciclo["combined_promedio"])
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


def dispersion_loss_por_ramo(
        por_ramo: Dict[str, Dict[str, Optional[float]]],
        prima_minima: float = 1e6) -> Optional[Dict[str, Any]]:
    """Dispersión del loss ratio entre ramos, PONDERADA por participación de prima (§5.6).

    Si el pricing es bueno, el loss ratio debería ser parejo entre segmentos: la prima
    sigue al riesgo. Mucha dispersión esconde subsidio cruzado que el agregado no muestra —
    y es más difícil de maquillar que el margen agregado, porque exige mover varios ramos a
    la vez.

    **Ponderada, no simple.** Sin ponderar, un ramo residual domina el resultado: en Seguros
    Universal, naves aéreas mueve RD$14 millones con un loss ratio de 164% y salud mueve
    RD$6.022 millones con 71.8%. Tratarlos igual describe una anécdota, no la cartera.
    Los ramos por debajo de *prima_minima* quedan fuera por la misma razón.

    Es un CANDIDATO a extensión de Ejecución (spec §5.6), no parte del mapeo mínimo del
    §5.9: se expone como métrica y no entra al score hasta validarlo.
    """
    # (ramo, primas, siniestros) ya desempaquetado: deja los tipos explícitos y evita
    # re-derivar el filtro en cada comprensión.
    ramos: List[tuple] = []
    for nombre, v in (por_ramo or {}).items():
        primas, siniestros = v.get("primas"), v.get("siniestros")
        if primas is not None and siniestros is not None and primas >= prima_minima:
            ramos.append((nombre, float(primas), float(siniestros)))
    if len(ramos) < 2:
        return None
    total = sum(p for _n, p, _s in ramos)
    if total <= 0:
        return None
    pares = [(p / total, s / p) for _n, p, s in ramos]
    media = sum(peso * lr for peso, lr in pares)
    var = sum(peso * (lr - media) ** 2 for peso, lr in pares)
    return {
        "n_ramos": len(ramos),
        "loss_ponderado": round(media, 4),
        "dispersion": round(math.sqrt(var), 4),
        "ramos": {n: round(s / p, 4) for n, p, s in ramos},
    }


def correlacion(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Gate del §8, idéntico al de banca — reexportado para no duplicar el criterio."""
    from modules.banking_score.scoring.perfil_sdq import correlacion as _c
    return _c(xs, ys)


def band_resiliencia_o_none(score: Optional[float]) -> Optional[str]:
    """Banda de Resiliencia reusando la del ISF — incluido su techo por incumplimiento."""
    from modules.insurance_intel.scoring.isf import band_for
    return band_for(score)


def panel_por_aseguradora(db) -> Dict[str, Dict[str, Any]]:
    """Arma ``{slug: {name, ejercicios: {año: {loss, exp, cesion}}, índices, period}}``.

    Reusa ``isf._load_financials`` para la identidad canónica —agrupar por el roster oficial,
    no por el slug del año— y después recorre ``insurance_series`` para reconstruir la serie
    plurianual por entidad, que es lo que Ejecución necesita y el ISF no usa (el ISF toma
    solo el último valor de cada serie).
    """
    from modules.insurance_intel.models.models import InsuranceSeries
    from modules.insurance_intel.scoring.isf import _load_financials

    ultimos = {f["slug"]: f for f in _load_financials(db)}
    if not ultimos:
        return {}

    rows = (db.query(InsuranceSeries)
            .filter(InsuranceSeries.entity_slug.in_(list(ultimos)),
                    InsuranceSeries.dimension.is_(None),
                    InsuranceSeries.value.isnot(None)).all())
    por: Dict[str, Dict[str, Dict[str, float]]] = {}
    for r in rows:
        por.setdefault(r.entity_slug, {}).setdefault(r.period, {})[r.series_code] = r.value

    salida: Dict[str, Dict[str, Any]] = {}
    for slug, fin in ultimos.items():
        ejercicios: Dict[str, Dict[str, float]] = {}
        for periodo, s in (por.get(slug) or {}).items():
            primas = s.get("primas_suscritas")
            sin_, gop = s.get("siniestros_pagados"), s.get("gastos_operativos")
            if not primas or sin_ is None or gop is None:
                continue  # ejercicio incompleto: se omite, no se rellena
            ejercicios[periodo] = {
                "loss": sin_ / primas, "exp": gop / primas,
                "cesion": (s.get("primas_cedidas") or 0.0) / primas,
            }
        salida[slug] = {
            "name": fin.get("name", slug),
            "period": fin.get("period"),
            "ejercicios": ejercicios,
            "indice_solvencia": fin.get("indice_solvencia"),
            "indice_liquidez": fin.get("indice_liquidez"),
        }
    return salida


# Cortes de §4, los MISMOS que banca/pensiones/fiduciarias. No hay un segundo sistema de
# cortes propio de seguros: el combined ratio queda como la métrica subyacente que alimenta el
# índice, no como una escala visible en paralelo.
BANDAS_EJECUCION = [(75.0, "Sobresaliente"), (60.0, "Competitiva"), (45.0, "Rezagada"),
                    (0.0, "Deficiente")]


def banda_ejecucion(score: Optional[float]) -> Optional[str]:
    """Banda de Ejecución sobre el índice 0-100, con los cortes de §4.

    Expresado en combined ratio —que es como lo va a pensar cualquier lector técnico— esos
    cortes equivalen a Sobresaliente <90% · Competitiva 90-100% · Rezagada 100-110% ·
    Deficiente >110%. Son los mismos números que fijan la pendiente de la conversión, no un
    sistema aparte.
    """
    if score is None:
        return None
    return next((n for t, n in BANDAS_EJECUCION if score >= t), "Deficiente")


def bandas_ejecucion_por_combined(combined: Optional[float]) -> Optional[str]:
    """Atajo: banda directamente desde el combined ratio, vía la conversión de §5.2."""
    return banda_ejecucion(score_ejecucion_desde_combined(combined))
