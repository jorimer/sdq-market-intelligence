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

# Umbral de tendencia, en puntos de combined ratio por año. JUICIO, no derivado: por debajo
# de 1 punto anual el movimiento no se separa del ruido de tarificación del panel.
UMBRAL_TENDENCIA = 1.0

# Salto de escala tolerado DENTRO de la ventana (prima mayor / prima menor). Por encima, los
# extremos del ciclo describen empresas distintas y el promedio no es interpretable.
SALTO_ESCALA_MAX = 10.0

# Cobertura mínima de Resiliencia para publicarla. El ISF ya exigía 0.50; el eje no lo hacía
# y publicaba 100.0 y 0.0 para entidades sin un solo ejercicio financiero cargado.
MIN_COBERTURA_RESILIENCIA = 0.50

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
    """Métricas de la ventana a partir de ``{año: {loss, exp, cesion, primas}}``.

    El promedio del ciclo va **PONDERADO POR EXPOSICIÓN** (prima devengada), no simple.
    Un promedio simple da el mismo peso a un ejercicio de 3 millones de prima que a uno de
    30, y eso destruye la medición de cualquier compañía que haya cambiado de escala:
    HYLSEG creció 7× en cinco años y su promedio simple daba 118.9% —arrastrado por dos
    ejercicios diminutos donde el costo fijo se comía la prima— contra 89.0% ponderado.
    En UNIT, en pleno arranque, la diferencia era 2.584% contra 343%.

    Ponderar por exposición es además la forma estándar del combined ratio de ciclo: es
    equivalente a Σ(siniestro incurrido + gasto) / Σ(prima devengada) sobre la ventana.

    Devuelve None si no hay ejercicios suficientes: sin ciclo no se fabrica un promedio.
    """
    años = sorted(ejercicios)[-VENTANA_CICLO:]
    if len(años) < MIN_EJERCICIOS:
        return None
    losses = [ejercicios[a]["loss"] for a in años]
    combineds = [ejercicios[a]["loss"] + ejercicios[a]["exp"] for a in años]
    # Sin volumen registrado se cae al promedio simple —comportamiento anterior— en vez de
    # descartar el ejercicio: un peso ausente no debe borrar la observación.
    pesos = [float(ejercicios[a].get("primas") or 0.0) for a in años]
    total = sum(pesos)
    n = len(losses)
    if total > 0:
        combined_prom = sum(c * w for c, w in zip(combineds, pesos)) / total
        media = sum(x * w for x, w in zip(losses, pesos)) / total
        var = sum(w * (x - media) ** 2 for x, w in zip(losses, pesos)) / total
        cesion = sum(ejercicios[a].get("cesion", 0.0) * w
                     for a, w in zip(años, pesos)) / total
    else:
        combined_prom = sum(combineds) / n
        media = sum(losses) / n
        var = sum((x - media) ** 2 for x in losses) / n
        cesion = sum(ejercicios[a].get("cesion", 0.0) for a in años) / n
    # ── TENDENCIA ────────────────────────────────────────────────────────────────
    # Un promedio de ciclo, aun ponderado, NO distingue una compañía que fue de 60 a 80 de
    # otra que fue de 80 a 60. Medido sobre el panel, la correlación de rangos entre nivel y
    # pendiente es +0.26: la trayectoria es información casi independiente del nivel, y es lo
    # que separa una señal temprana de una fotografía. Se expone APARTE, nunca mezclada en el
    # score: fundirla repetiría el error del símbolo único que Perfil SDQ vino a reemplazar.
    pend = _pendiente(años, combineds, pesos if total > 0 else None)

    # Una compañía cuya prima cambió de orden de magnitud dentro de la ventana no tiene un
    # ciclo comparable: los extremos describen empresas distintas. No se corrige el número
    # —sería fabricarlo— se DECLARA para que el lector lo descuente. Caso testigo: UNIT, con
    # prima de 106 mil en el primer ejercicio y 132 millones en el último.
    vivos = [w for w in pesos if w > 0]
    comparable = bool(vivos) and (max(vivos) / min(vivos)) <= SALTO_ESCALA_MAX

    return {
        "años": años,
        "combined_promedio": combined_prom,
        "loss_volatilidad": math.sqrt(var),
        "cesion_promedio": cesion,
        "ponderado_por_exposicion": total > 0,
        "pendiente_combined": pend,
        "ciclo_comparable": comparable,
    }


def _pendiente(años: Sequence[str], combineds: Sequence[float],
               pesos: Optional[Sequence[float]]) -> Optional[float]:
    """Pendiente OLS del combined ratio en **puntos porcentuales por año**.

    Ponderada por exposición cuando hay volumen, por el mismo motivo que el promedio.
    Positiva = deteriora. Devuelve None si los años no tienen dispersión.
    """
    xs = [float(int(a)) for a in años]
    ys = [c * 100.0 for c in combineds]
    ws = list(pesos) if pesos else [1.0] * len(xs)
    W = sum(ws)
    if W <= 0 or len(xs) < MIN_EJERCICIOS:
        return None
    mx = sum(x * w for x, w in zip(xs, ws)) / W
    my = sum(y * w for y, w in zip(ys, ws)) / W
    den = sum(w * (x - mx) ** 2 for x, w in zip(xs, ws))
    if den == 0:
        return None
    return round(sum(w * (x - mx) * (y - my) for x, y, w in zip(xs, ys, ws)) / den, 2)


def banda_tendencia(pendiente: Optional[float]) -> Optional[str]:
    """Etiqueta de trayectoria. El umbral es de JUICIO y se declara como tal.

    ±1 punto de combined ratio por año: por debajo, el movimiento no se distingue del ruido
    de tarificación anual del panel; por encima, cinco años de ventana acumulan 5 puntos,
    que sí mueven de banda.
    """
    if pendiente is None:
        return None
    if pendiente > UMBRAL_TENDENCIA:
        return "Deteriora"
    if pendiente < -UMBRAL_TENDENCIA:
        return "Mejora"
    return "Estable"


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
    # Cobertura insuficiente ⇒ NO se publica el eje. El ISF ya exigía este mínimo; el eje no
    # lo hacía y llegó a publicar 100.0 y 0.0 para entidades sin un solo ejercicio financiero
    # cargado — un número armado con una sola dimensión renormalizada al 100%, que es
    # precisamente rellenar una brecha en vez de declararla.
    resiliencia = (round(sum(presentes[k] * PESOS_RESILIENCIA[k] for k in presentes) / peso, 1)
                   if peso >= MIN_COBERTURA_RESILIENCIA else None)
    return {
        "ejecucion": ejecucion,
        "resiliencia": resiliencia,
        "cobertura_resiliencia": round(peso, 2),
        "cobertura_suficiente": peso >= MIN_COBERTURA_RESILIENCIA,
        "dimensiones": dims,
        "ejercicios": ciclo["años"] if ciclo else [],
        "combined_promedio": round(ciclo["combined_promedio"], 4) if ciclo else None,
        "pendiente_combined": ciclo.get("pendiente_combined") if ciclo else None,
        "ciclo_comparable": ciclo.get("ciclo_comparable") if ciclo else None,
    }


def dispersion_loss_por_ramo(
        por_ramo: Dict[str, Dict[str, Optional[float]]],
        prima_minima: float = 1e6) -> Optional[Dict[str, Any]]:
    """Dispersión del loss ratio entre ramos, PONDERADA por participación de prima (§5.6).

    Si el pricing es bueno, el loss ratio debería ser parejo entre segmentos: la prima
    sigue al riesgo. Mucha dispersión esconde subsidio cruzado que el agregado no muestra —
    y es más difícil de maquillar que el margen agregado, porque exige mover varios ramos a
    la vez.

    ⚠️ **Esta métrica sigue en base PAGADO sobre SUSCRITO, y no puede corregirse.** El
    agregado de la compañía pasó a base incurrida/devengada tras la revisión actuarial de
    2026-08, pero el catálogo regulatorio **no abre el movimiento de reservas por ramo**:
    las cuentas de reserva (5112/5311, 4109/4310 y sus específicas) son de la compañía, no
    del ramo. Reconstruir un incurrido por ramo exigiría prorratear la reserva, que es
    inventar el dato. Se deja en base pagada y se DECLARA: sirve para comparar ramos entre
    sí dentro de una misma compañía —donde el sesgo es común— y no para comparar el nivel
    contra el combined ratio agregado, que ya está en otra base.

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
    from modules.insurance_intel.models.models import InsuranceEntity, InsuranceSeries
    from modules.insurance_intel.scoring.isf import (
        _canon_map, _load_financials, _official_index,
    )

    ultimos = {f["slug"]: f for f in _load_financials(db)}
    if not ultimos:
        return {}

    # Las series NO están guardadas bajo el slug canónico: el nombre de hoja del Excel se
    # trunca a 31 caracteres y el slug deriva entre años y fuentes. Consultar por el slug
    # canónico directamente devolvía CERO filas para siete aseguradoras con primas de
    # cientos de millones —Cuna Mutual, One Alliance, Cooperativa Nacional…— y quedaban sin
    # Ejecución como si no tuvieran datos. Hay que recorrer el mismo mapa que usa el ISF.
    ents = (db.query(InsuranceEntity)
            .filter(InsuranceEntity.entity_type == "aseguradora").all())
    canon, _ = _canon_map(ents, _official_index())

    rows = (db.query(InsuranceSeries)
            .filter(InsuranceSeries.entity_slug.in_(list(canon) or [""]),
                    InsuranceSeries.dimension.is_(None),
                    InsuranceSeries.value.isnot(None)).all())
    por: Dict[str, Dict[str, Dict[str, float]]] = {}
    for r in rows:
        c = canon.get(r.entity_slug)
        if c is None:
            continue
        por.setdefault(c[2], {}).setdefault(r.period, {})[r.series_code] = r.value

    salida: Dict[str, Dict[str, Any]] = {}
    for slug, fin in ultimos.items():
        ejercicios: Dict[str, Dict[str, float]] = {}
        for periodo, s in (por.get(slug) or {}).items():
            # Base DEVENGADA/INCURRIDA cuando el ejercicio la trae; si no, no se computa.
            # Mezclar bases entre compañías produciría un ranking sin sentido, así que un
            # ejercicio sin la base nueva se OMITE en vez de caer al pagado-sobre-suscrito
            # (revisión actuarial: numerador y denominador deben estar en la misma base).
            primas = s.get("primas_devengadas")
            sin_ = s.get("siniestros_incurridos")
            gop = s.get("gastos_operativos")
            if not primas or sin_ is None or gop is None:
                continue  # ejercicio incompleto: se omite, no se rellena
            ejercicios[periodo] = {
                # ``primas`` es el PESO de exposición del ejercicio, no un ratio: sin él el
                # promedio del ciclo trata igual un año diminuto que uno grande.
                "primas": primas,
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
