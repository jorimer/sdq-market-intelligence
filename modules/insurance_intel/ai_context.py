"""AI context builders for Insurance Intel narratives.

Each builder digests a read-side payload into a flat, source-stamped context dict
for ``shared.narrative`` templates. Numbers only — the narrative engine never counts,
it interprets (numeric_guard). Mirrors ``pension_intel.ai_context``.
"""
from typing import Any, Dict, List, Optional


def _dims(rating: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {"dimension": d["label"], "score": d.get("score"), "peso": d["weight"],
         "valor_real": d.get("raw"), "presente": d.get("present")}
        for d in rating.get("dimensions") or []
    ]


def _comparaciones(rating, peers) -> list:
    """Comparaciones dimensión↔panel con la DIRECCIÓN ya resuelta.

    Misma cura que en banca: el modelo no debe derivar "por encima / por debajo" —
    erra la relación aunque las cifras sean correctas. Se computa acá contra la MEDIANA
    del panel en cada dimensión y se sirve para que la COPIE. También es lo que activa
    el detector de ``numeric_guard``, que fuera de banca estaba ciego por depender del
    mapeo de indicadores bancarios.
    """
    import statistics as st

    from shared.narrative.derived import comparaciones_vs_referencia

    valores: Dict[str, Optional[float]] = {}
    referencias: Dict[str, Dict[str, Optional[float]]] = {}
    for d in rating.get("dimensions") or []:
        label, mio = d.get("label"), d.get("score")
        if not label or mio is None:
            continue
        otros = []
        for p in peers or []:
            for pd in p.get("dimensions") or []:
                if pd.get("label") == label and pd.get("score") is not None:
                    otros.append(float(pd["score"]))
        if len(otros) < 3:      # panel muy chico: la mediana no representa
            continue
        valores[str(label)] = float(mio)
        referencias[str(label)] = {"mediana del panel": round(st.median(otros), 2)}
    return comparaciones_vs_referencia(valores, referencias)


def _posiciones(rating: Dict[str, Any], peers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Posición de la aseguradora en CADA dimensión, para vetar el superlativo transversal.

    El patrón nació y se curó en pensiones, pero su input (``posiciones_dimension``) sólo se
    inyectaba allí: el veto de ``numeric_guard`` se saltaba entero en seguros, así que un
    rank ISF global podía narrarse como "la más sólida del mercado" en una dimensión que
    otra lidera. Mismo helper transversal que usa banca.
    """
    from shared.narrative.derived import posiciones_por_dimension

    panel = [
        {"id": p.get("slug"), "name": p.get("name") or p.get("slug"),
         "dimensiones": {d.get("label"): d.get("score")
                         for d in (p.get("dimensions") or []) if d.get("label")}}
        for p in peers or []
    ]
    return posiciones_por_dimension(rating.get("slug"), panel)


_ANTI_SUPERLATIVO = (
    " POSICIÓN POR DIMENSIÓN: 'posiciones_dimension' trae {rank, n, es_lider, lider} por "
    "dimensión. NO afirmes que esta aseguradora es 'la mayor / la más alta / la líder del "
    "mercado' en una dimensión salvo que 'es_lider' sea true en ESA dimensión; si no lidera, "
    "da su posición real y nombra a quién lidera. El rank ISF GLOBAL no implica liderar cada "
    "dimensión. Y un percentil o un primer lugar describen la MUESTRA ACTUAL: nunca los "
    "narres como 'sin precedente' o 'nunca visto' — eso afirma sobre la historia, que no se "
    "midió."
    " DIRECCIÓN: si el contexto trae 'comparaciones', la dirección ya está resuelta "
    "ahí ('direccion': por encima / por debajo / en línea): COPIALA, no la deduzcas."
)


def insurance_entity_context(rating: Dict[str, Any], peers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Context for a named insurer's ISF assessment (template ``insurance_entity``)."""
    from shared.narrative.derived import rank_comparable, universo_comparable

    universo = universo_comparable(peers)
    pos = rank_comparable(rating.get("slug"), universo)
    return {
        "aseguradora": rating.get("name") or rating.get("slug"),
        "isf_score": rating.get("overall_score"),
        "banda": rating.get("band"),
        "coverage": rating.get("coverage"),
        # El rank se computa SOLO entre las de cobertura completa. Un ISF armado sobre 3 de 5
        # dimensiones no es comparable con uno de 5, y ordenarlos juntos producía «posición 7
        # de 35» sin decir de qué 35. Las parciales se listan aparte, nunca se ocultan.
        **pos,
        "periodo": rating.get("period"),
        "dimensiones": _dims(rating),
        "posiciones_dimension": _posiciones(rating, peers),
        "comparaciones": _comparaciones(rating, peers),
        "direction": "mayor solvencia/liquidez/resultado y menor siniestralidad = más sólida",
        "source": "SIS — estados financieros auditados por compañía (dato real)",
        "note": ("El ISF integra cinco dimensiones sobre los estados financieros auditados que "
                 "publica la SIS: solvencia (patrimonio/activos), siniestralidad (loss ratio), "
                 "liquidez, escala y resultado técnico. Es una medida de solidez por bandas, no "
                 "un rating de crédito ni una clasificación de Solvencia II." + _ANTI_SUPERLATIVO),
    }


def insurance_peer_context(name: str, rating: Dict[str, Any],
                           peers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Context for peer positioning against the market (template ``insurance_peer_positioning``)."""
    from shared.narrative.derived import rank_comparable, universo_comparable

    universo = universo_comparable(peers)
    comparables = universo["comparables"]

    def _cell(p: Dict[str, Any], parcial: bool = False) -> Dict[str, Any]:
        by = {d["key"]: d.get("score") for d in p.get("dimensions") or []}
        c = {"aseguradora": p.get("name") or p.get("slug"), "isf": p.get("overall_score"),
             "solvencia": by.get("solvencia"), "siniestralidad": by.get("siniestralidad"),
             "liquidez": by.get("liquidez"), "escala": by.get("escala"),
             "resultado_tecnico": by.get("resultado_tecnico")}
        if parcial:
            # Sin esto, una fila con dos celdas vacías se leía como un par más de la lista.
            c["cobertura"] = p.get("coverage")
            c["comparable"] = False
            c["dimensiones_ausentes"] = [d["label"] for d in p.get("dimensions") or []
                                         if not d.get("present")]
        return c

    pos = rank_comparable(rating.get("slug"), universo)
    avg = (round(sum(p["overall_score"] for p in comparables) / len(comparables), 1)
           if comparables else None)
    return {
        "aseguradora": name, "isf": rating.get("overall_score"), "banda": rating.get("band"),
        **pos,
        # La tabla ordenada son SOLO las comparables; las parciales van en su propia lista con
        # la cobertura y las dimensiones que les faltan, para que se muestren sin mezclarse.
        "tabla_pares": [_cell(p) for p in comparables[:12]],
        "pares_cobertura_parcial": [_cell(p, parcial=True) for p in universo["parciales"]],
        "lider_isf": comparables[0].get("name") if comparables else None,
        # El promedio también es de las comparables: promediar scores de distinta cobertura
        # produce una referencia que no describe a ninguna población.
        "promedio_isf": avg,
        "posiciones_dimension": _posiciones(rating, peers),
        "comparaciones": _comparaciones(rating, peers),
        "source": "SIS — estados financieros auditados por compañía (dato real)",
        "note": ("Posición relativa por bandas de solidez (0-100). No es un rating de crédito."
                 + _ANTI_SUPERLATIVO),
    }


def _n_autorizadas() -> Optional[int]:
    """Aseguradoras del roster autorizado de la SIS, o None si no está disponible.

    Nunca revienta el contexto: sin roster se declara la ausencia (None) y el modelo se queda
    sin la cifra, que es preferible a que tome otra que no significa lo mismo.
    """
    try:
        from modules.insurance_intel.scoring.isf import _official_index
        return len(_official_index()) or None
    except Exception:  # noqa: BLE001 — el contexto jamás debe caerse por una cifra de apoyo
        return None


def market_pulse_context(pulse: Dict[str, Any]) -> Dict[str, Any]:
    """Context for the national insurance-market Pulse (template ``insurance_pulse``)."""
    mix: List[Dict[str, Any]] = pulse.get("mix") or []
    hc = pulse.get("health_coverage") or {}
    return {
        "periodo": pulse.get("period"),
        "cobertura_salud_sfs": {
            "afiliados_total": hc.get("afiliados_total"),
            "afiliados_contributivo": hc.get("afiliados_contributivo"),
            "afiliados_subsidiado": hc.get("afiliados_subsidiado"),
            "crecimiento_5a_pct": hc.get("crecimiento_5a_pct"),
            "periodo": hc.get("period"),
            "fuente": "SISALRIL/CNSS — Seguro Familiar de Salud",
        } if hc else None,
        "anio": pulse.get("latest_year"),
        "primas_totales_rd": pulse.get("total_premiums_rd"),
        "crecimiento_pct": pulse.get("growth_pct"),
        "crecimiento_ventana": pulse.get("growth_years"),
        # ⚠️ NO es «cuántas aseguradoras hay en el mercado». La serie de origen
        # (`sis.aseguradoras.activas_max`) es el MÁXIMO, entre ramos, de cuántas compañías
        # operan en un ramo: 26 significa que el ramo más concurrido tiene 26 participantes.
        # Bajo el nombre `aseguradoras_activas` el modelo publicó «un mercado de 26 operadores
        # activos» —falso, el panel tiene 35 con ISF— y de ahí dedujo «la cola restante, 22
        # operadores». El nombre ahora dice lo que la serie mide.
        "max_aseguradoras_en_un_mismo_ramo": pulse.get("active_insurers"),
        # El tamaño REAL del mercado, con su propio nombre. Sin una cifra correcta disponible,
        # el modelo toma la que haya: por eso se sirve el roster autorizado de la SIS junto a
        # la anterior, en vez de dejar el hueco que ya se llenó mal una vez.
        "aseguradoras_autorizadas_sis": _n_autorizadas(),
        "n_ramos": pulse.get("n_ramos"),
        # ⚠️ EL SUJETO VIAJA CON EL NÚMERO. Esta cifra es la suma de los cuatro RAMOS de mayor
        # peso, no la cuota de las cuatro mayores COMPAÑÍAS. Se llamaba `concentracion_top4_pct`
        # —sin sujeto— y el modelo, leyéndola junto a `aseguradoras_activas`, publicó «cuatro
        # compañías concentran el 87,1% de las primas» en un Deep Dive. El número era correcto;
        # lo que se perdió camino al modelo fue de qué era. La concentración por compañía es
        # otra cosa y vale ~69%: si alguna vez se necesita, se computa y se pasa aparte.
        "concentracion_top4_ramos_pct": pulse.get("top4_concentration_pct"),
        "concentracion_top4_ramos_nombres": [d.get("label") for d in mix[:4]],
        "mezcla_por_ramo": [
            {"ramo": d["label"], "monto_rd": d["amount"], "pct": d.get("pct")}
            for d in mix[:6]
        ],
        "unit_primas": "RD$ (primas netas cobradas)",
        "direction": "mayor tamaño, crecimiento sostenido y mezcla diversificada = mercado más profundo",
        "source": "SIS — Superintendencia de Seguros (dato real, datos.gob.do)",
        "note": (
            "Pulso del mercado asegurador (agregado, sin nombres de aseguradora). "
            "Primas netas cobradas; el crecimiento se lee como tasa compuesta entre años "
            "independientes. " + (pulse.get("data_caveat") or "")
        ).strip(),
    }


# Prosa que la narrativa debe respetar, como CONSTANTES y no incrustada en el dict: un
# literal partido por ancho de línea deja de existir como frase en el código fuente, así que
# un test que la busque ahí falla aunque el valor sea correcto (pasó al escribir estos tests).
REGLA_TENDENCIA = (
    "«Sin señal» NO significa estable: significa que con 3-5 ejercicios y esta volatilidad no "
    "se distingue movimiento de ruido. Son afirmaciones distintas y no se pueden intercambiar."
)

# El ISF de las otras secciones mide el ÚLTIMO ejercicio; la trayectoria es el promedio del
# ciclo ponderado por exposición. Son dos cifras distintas de la misma compañía y, sin decirlo,
# el documento parece contradecirse: MAPFRE-BHD da 72 % en 2024 y 75,2 % en el ciclo 2020-2024.
VENTANA_DEL_CICLO = (
    "promedio del CICLO ponderado por exposición, no el último ejercicio: si citás esta cifra, "
    "decí el rango de años. El combined ratio y el margen técnico de las otras secciones son "
    "del último cierre."
)


def insurance_early_warning_context(db, slug: str, rating: Dict[str, Any],
                                    peers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Contexto de ALERTA TEMPRANA: la TRAYECTORIA, no la foto.

    **Por qué existe.** La sección caía al mismo template y al mismo contexto que la evaluación
    de solidez, así que el Deep Dive publicaba dos veces el mismo análisis con distinto título
    —y el modelo repetía hasta el encabezado de la §1—. No era el modelo repitiéndose: se le
    pedía dos veces lo mismo.

    Y faltaba lo esencial: Perfil SDQ computa la PENDIENTE del combined ratio con su error
    estándar y la etiqueta por SIGNIFICANCIA (|t| ≥ 2), que es exactamente material de señal
    temprana, y nada de eso llegaba a la sección que debía usarlo. Una alerta temprana escrita
    desde un corte estático solo puede repetir el nivel.

    Todo lo que no se pueda computar se declara ausente; no se rellena.
    """
    from modules.insurance_intel.scoring.perfil_sdq import (
        banda_tendencia, calcular_ejes, metricas_del_ciclo, panel_por_aseguradora,
    )

    trayectoria: Dict[str, Any] = {"disponible": False}
    try:
        info = (panel_por_aseguradora(db) or {}).get(slug)
        ciclo = metricas_del_ciclo(info["ejercicios"]) if info else None
        if ciclo:
            ejes = calcular_ejes(ciclo, (info or {}).get("indice_solvencia"),
                                 (info or {}).get("indice_liquidez"))
            trayectoria = {
                "disponible": True,
                "ejercicios": ejes["ejercicios"],
                "combined_promedio_ciclo": ejes["combined_promedio"],
                "pendiente_pp_por_año": ejes["pendiente_combined"],
                "pendiente_error_estandar": ejes["pendiente_error_estandar"],
                # La etiqueta ya resuelve la significancia: el modelo la COPIA, no la deduce.
                "tendencia": banda_tendencia(ejes["pendiente_combined"],
                                             ejes["pendiente_error_estandar"]),
                "ciclo_comparable": ejes["ciclo_comparable"],
                "cesion_promedio": ejes["cesion_promedio"],
                "ejecucion": ejes["ejecucion"],
                "ejecucion_no_publicable": ejes["ejecucion_no_publicable"],
                "regla_tendencia": REGLA_TENDENCIA,
                "ventana": VENTANA_DEL_CICLO,
            }
    except Exception:  # noqa: BLE001 — sin trayectoria la sección sigue siendo publicable
        trayectoria = {"disponible": False}

    dims = [d for d in (rating.get("dimensions") or []) if d.get("score") is not None]
    debil = min(dims, key=lambda d: d["score"]) if dims else None
    ctx = insurance_entity_context(rating, peers)
    ctx.update({
        "trayectoria": trayectoria,
        "dimension_mas_debil": ({"dimension": debil["label"], "score": debil.get("score"),
                                 "peso": debil.get("weight")} if debil else None),
        "enfoque": (
            "ALERTA TEMPRANA: escribí sobre lo que PUEDE CAMBIAR, no sobre el nivel actual. "
            "La evaluación de solidez ya cubrió el nivel en otra sección — NO la repitas ni "
            "reproduzcas su encabezado. Acá van tres cosas y solo tres: (1) la TRAYECTORIA del "
            "combined ratio con su etiqueta de significancia, copiada tal cual; (2) el umbral "
            "concreto que, de cruzarse, cambiaría la banda, nombrando la dimensión y el valor; "
            "(3) qué observar en el próximo corte. Si la trayectoria no está disponible, decilo "
            "y limitate a los disparadores. No repitas cifras de posición relativa."),
    })
    return ctx
