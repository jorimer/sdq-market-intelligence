"""Precompute canónico de cifras derivadas para la ruta cerebro (transversal a ejes).

El modelo erra al CALCULAR relaciones (aportes, deltas, rangos, extremos); la cura es
servírselas YA calculadas para que COPIE (ver piloto banking). Este módulo computa esas
cifras a partir de una forma CANÓNICA de contexto que cualquier eje puede poblar:

    score:         float | None         — el score global del ítem (entidad/sector/país…)
    subcomponents: [{"componente","score","peso"}]   — dimensiones con su peso
    trend:         [{"periodo","score"}] | None       — serie temporal (si existe)
    peers:         {"entity_type":{median_score,p75_score,percentile,n}, "sector":{…}} | None

Cada eje llama `derived_figures(...)` con lo que tenga; lo ausente se omite (best-effort).
El detector determinista (`numeric_guard.deterministic_unsupported`) lee estas mismas
cifras + la forma canónica, así que funciona para todo eje sin cambios.
"""
from typing import Any, Dict, List, Optional


def derived_figures(
    *,
    score: Optional[float],
    subcomponents: List[Dict[str, Any]],
    trend: Optional[List[Dict[str, Any]]] = None,
    peers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Cifras derivadas que el analista DEBE copiar (no recalcular). Solo incluye las
    secciones que el dato soporta: aportes/gaps y superlativos de componente siempre;
    deltas/percentiles si hay `peers`; rango/variaciones/cortes si hay `trend`."""
    out: Dict[str, Any] = {}
    subs = subcomponents or []

    aportes = [{"componente": s.get("componente"),
                "aporte_pts": round((s.get("score") or 0) * (s.get("peso") or 0), 2),
                "gap_al_techo_pts": round(100 - (s.get("score") or 0), 2)}
               for s in subs]
    if aportes:
        out["aporte_por_componente"] = aportes
        lider = max(aportes, key=lambda a: a["aporte_pts"])
        resto = round(sum(a["aporte_pts"] for a in aportes) - lider["aporte_pts"], 2)
        out["aporte_lider_vs_resto"] = {
            "lider": lider["componente"], "aporte_lider": lider["aporte_pts"],
            "suma_resto": resto, "lider_supera_al_resto": lider["aporte_pts"] > resto,
        }
        mg = max(aportes, key=lambda a: a["gap_al_techo_pts"])
        out["componente_mayor_gap_al_techo"] = {
            "componente": mg["componente"], "gap_al_techo_pts": mg["gap_al_techo_pts"],
        }
        out["componentes_por_peso_desc"] = [
            s.get("componente") for s in sorted(subs, key=lambda s: -(s.get("peso") or 0))
        ]

    peers = peers or {}
    et = peers.get("entity_type") or {}
    sec = peers.get("sector") or {}
    if score is not None:
        deltas: Dict[str, Any] = {}
        if et.get("median_score") is not None:
            deltas["vs_mediana_tipo"] = round(score - et["median_score"], 2)
        if et.get("p75_score") is not None:
            deltas["vs_p75_tipo"] = round(score - et["p75_score"], 2)
        if sec.get("median_score") is not None:
            deltas["vs_mediana_sector"] = round(score - sec["median_score"], 2)
        if deltas:
            out["delta_score"] = deltas
    if et.get("percentile") is not None and et.get("n"):
        out["pares_tipo_que_lo_superan_aprox"] = {
            "aprox": round((1 - et["percentile"] / 100) * et["n"]), "de_n": et["n"],
        }

    scores = [(t.get("periodo"), t["score"]) for t in (trend or [])
              if t.get("score") is not None]
    if scores:
        lo = min(scores, key=lambda x: x[1])
        hi = max(scores, key=lambda x: x[1])
        out["rango_score_12t"] = {
            "min": {"periodo": lo[0], "score": lo[1]},
            "max": {"periodo": hi[0], "score": hi[1]},
            "n_periodos": len(scores),
        }
        cur_p, cur = scores[-1]
        var: Dict[str, Any] = {"caida_desde_max": round(hi[1] - cur, 2),
                               "subida_desde_min": round(cur - lo[1], 2)}
        if len(scores) >= 2:
            var["vs_trimestre_anterior"] = round(cur - scores[-2][1], 2)
        if len(scores) >= 5:
            var["vs_mismo_trimestre_ano_previo"] = round(cur - scores[-5][1], 2)
        out["variacion_score_actual"] = var
        drops = [(scores[i - 1][0], scores[i][0], round(scores[i - 1][1] - scores[i][1], 2))
                 for i in range(1, len(scores)) if scores[i - 1][1] > scores[i][1]]
        if drops:
            de, a, caida = max(drops, key=lambda d: d[2])
            out["mayor_caida_intertrimestral"] = {"de": de, "a": a, "caida": caida}
        cortes_q1 = [{"periodo": p, "score": s} for p, s in scores
                     if str(p or "")[5:7] == "03"]
        if cortes_q1:
            out["cortes_q1_marzo"] = cortes_q1
    return out


# ── Comparaciones contra referencia (dirección RESUELTA, no derivada) ─────────
#
# Bug 2026-08-05/06: dos informes de cliente afirmaron una comparación con el sentido
# invertido ("mora de 1.67% por debajo del promedio de pares (1.5%)"; "ICAP de 16.44% por
# encima del promedio del sistema (16.5%)"), contradiciendo la tabla del propio informe.
# Las cifras eran correctas: lo que el modelo erró fue la RELACIÓN entre ellas — el mismo
# modo de falla que este módulo ya cura para aportes, deltas y extremos. La cura es la
# misma: servir la dirección YA RESUELTA para que la COPIE. Un detector solo avisa; esto
# elimina el modo de falla.

# Por debajo de esta brecha no se afirma dirección. Nace del caso real: 16.44 vs 16.5
# difieren 0.06 pp — forzar "por encima/por debajo" ahí invita a elegir el lado equivocado
# y, sobre todo, no informa nada. "en línea con" es la lectura honesta.
MATERIALIDAD_PP = 0.1

# La UNIDAD viaja con la brecha. Sin esto, `_lectura` decía siempre "puntos porcentuales" y
# una comparación de HHI —un ÍNDICE de 0 a 10.000, no un porcentaje— salía narrada como
# «412,30 puntos porcentuales por encima del promedio del sistema»: una cifra correcta con una
# unidad imposible. Es la misma familia de defecto que el sujeto que no viaja con el número.
UNIDAD_DE_BRECHA = {
    "%": "puntos porcentuales",
    "índice": "puntos del índice",
}
_UNIDAD_POR_DEFECTO = "%"

# Piso de RUIDO por unidad, no umbral de significancia. En %, 0.1 pp nace del caso real
# (16.44 vs 16.5 difieren 0.06 pp: forzar un lado ahí no informa nada). En un índice HHI la
# escala es otra —los valores viven en cientos o miles— y 0.1 punto es ruido de redondeo; 10
# puntos es lo primero que se distingue de eso. NO es el umbral antimonopolio de 100 puntos:
# ése mide si un cambio de concentración es SIGNIFICATIVO, y acá solo se decide si vale
# afirmar un lado.
MATERIALIDAD_POR_UNIDAD = {
    "%": MATERIALIDAD_PP,
    "índice": 10.0,
}


def _lectura(direccion: str, etiqueta: str, brecha: float,
             unidad_brecha: str = "puntos porcentuales") -> str:
    """La comparación como CLÁUSULA ya redactada, lista para copiar.

    Reincidencia 2026-08-13 (Rating Completo BPD §5): el contexto traía
    ``{"direccion": "por encima", "brecha_pp": 7.31}`` para el LTD y la prosa salió
    «7.31 puntos porcentuales POR DEBAJO del promedio de bancos múltiples» —
    contradiciendo a la §7 del mismo documento, que lo dijo bien.

    Lo revelador es CÓMO falló: el modelo copió la magnitud y redactó la palabra. Servir
    los campos por separado deja media relación en sus manos, y esa mitad es justamente la
    que erra. El campo ``brecha_pp`` se conserva firmado (el chequeo determinista lo lee),
    pero la frase se sirve armada para que copiar sea más fácil que redactar.
    """
    if direccion == "en línea":
        return (f"en línea con el {etiqueta} (brecha de {brecha:+.2f} {unidad_brecha}, "
                "materialmente nula)")
    return f"{direccion} del {etiqueta} en {abs(brecha):.2f} {unidad_brecha}"


#: Posición + sentido de la escala → VEREDICTO. La unión que faltaba.
#:
#: El contexto servía los dos hechos por separado —"por debajo del promedio en 3.70 pp" en un
#: lado, "un valor MÁS ALTO es MEJOR" en otro— y dejaba que el modelo los UNIERA. Esa unión es
#: una derivación, que es exactamente la operación que este módulo entero existe para evitar.
#:
#: Huella del defecto en un informe real (Deep Dive de banca, §7 «Análisis Comparativo»): con
#: patrimonio/activos en 7.41% contra una mediana de grupo de 11.11%, la sección escribió que
#: «SUPERA en 3.70 puntos porcentuales al promedio de su grupo» y dos líneas después que el
#: margen de absorción es «estructuralmente MÁS DELGADO que el del par típico». No es un
#: desliz de una palabra: son DOS uniones distintas del mismo par de hechos, una bien y otra
#: al revés. Un error de tipeo no se comporta así.
_VEREDICTO = {
    ("higher", "por encima"): "favorable", ("higher", "por debajo"): "desfavorable",
    ("lower", "por encima"): "desfavorable", ("lower", "por debajo"): "favorable",
}
_POR_QUE = {"higher": "en este indicador un valor más alto es mejor",
            "lower": "en este indicador un valor más bajo es mejor"}


def _veredicto(direccion_escala: Optional[str], posicion: str) -> tuple:
    """``(veredicto, por_qué)`` de una posición dada el sentido de la escala.

    ``no_aplica`` en los indicadores de ÓPTIMO INTERMEDIO, y no por no saber: ahí la vara NO
    es el promedio sino el óptimo, así que estar por encima o por debajo del grupo no tiene
    lectura de bueno o malo. Esa la da ``posicion_vs_optimo``. Se declara el motivo — un campo
    ausente se lee como que nadie miró.
    """
    if posicion == "en línea":
        return "en línea", "la brecha no es material"
    if direccion_escala == "target":
        return "no_aplica", ("indicador de óptimo intermedio: la vara es el óptimo, no el "
                             "promedio — leé 'posicion_vs_optimo'")
    escala = direccion_escala or ""
    v = _VEREDICTO.get((escala, posicion))
    if v is None:
        return "no_aplica", "no se declaró el sentido de la escala de este indicador"
    return v, _POR_QUE[escala]


def comparaciones_vs_referencia(
    valores: Dict[str, Optional[float]],
    referencias: Dict[str, Dict[str, Optional[float]]],
    *,
    unidades: Optional[Dict[str, Optional[str]]] = None,
    direcciones: Optional[Dict[str, Optional[str]]] = None,
    materialidad_pp: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Dirección y brecha de cada (indicador, referencia), ya resueltas.

    Args:
        valores: ``{indicador: valor_de_la_entidad}``.
        referencias: ``{indicador: {etiqueta_legible: valor_de_referencia}}``. La etiqueta
            es la que el analista debe usar al nombrar la base ("promedio del sistema",
            "promedio de pares grandes"): nombrar CONTRA QUÉ se compara es la mitad del
            problema, porque un indicador puede estar bajo el sistema y sobre su grupo de
            pares a la vez.
        unidades: ``{indicador: unidad}`` (``"%"`` | ``"índice"``). Decide en qué unidad se
            ENUNCIA la brecha y qué piso de ruido se le aplica. Por defecto ``"%"``, que es
            lo que asumía el módulo entero cuando solo había porcentajes.
        materialidad_pp: fuerza un piso de ruido único para todos los indicadores. Sin él,
            cada uno usa el de SU unidad (``MATERIALIDAD_POR_UNIDAD``).

    Returns:
        Lista de ``{indicador, valor, referencia, valor_referencia, direccion, brecha_pp,
        unidad_brecha, lectura}`` con ``direccion`` ∈ {"por encima", "por debajo", "en línea"}
        y ``lectura`` la cláusula ya redactada (ver ``_lectura``). Agnóstica de eje: el
        llamador arma el mapeo indicador→referencias con el vocabulario de su dominio.

        ``brecha_pp`` conserva el nombre aunque la unidad no sea siempre pp: es el campo que
        leen el chequeo determinista de dirección (``numeric_guard``) y la instrucción del
        cerebro. La unidad viaja al lado, en ``unidad_brecha``, y ya redactada en ``lectura``.
    """
    out: List[Dict[str, Any]] = []
    for indicador, refs in (referencias or {}).items():
        val = (valores or {}).get(indicador)
        if val is None or not isinstance(refs, dict):
            continue
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        for etiqueta, ref in refs.items():
            if ref is None:
                continue
            try:
                r = float(ref)
            except (TypeError, ValueError):
                continue
            unidad = (unidades or {}).get(indicador) or _UNIDAD_POR_DEFECTO
            unidad_brecha = UNIDAD_DE_BRECHA.get(unidad, UNIDAD_DE_BRECHA[_UNIDAD_POR_DEFECTO])
            piso = (materialidad_pp if materialidad_pp is not None
                    else MATERIALIDAD_POR_UNIDAD.get(unidad, MATERIALIDAD_PP))
            brecha = round(v - r, 2)
            if abs(brecha) < piso:
                direccion = "en línea"
            else:
                direccion = "por encima" if brecha > 0 else "por debajo"
            veredicto, por_que = _veredicto(
                (direcciones or {}).get(indicador), direccion)
            out.append({
                "indicador": indicador,
                "valor": round(v, 4),
                "referencia": etiqueta,
                "valor_referencia": round(r, 4),
                "direccion": direccion,
                "brecha_pp": brecha,
                "unidad_brecha": unidad_brecha,
                # `lectura` se COPIA literal (así lo pide el prompt), así que el veredicto NO
                # va adentro: terminaría impreso en el informe. Viaja aparte, es INTERNO — el
                # modelo lo usa para orientarse y redacta con su propio criterio.
                "lectura": _lectura(direccion, str(etiqueta), brecha, unidad_brecha),
                "veredicto": veredicto,
                "veredicto_por_que": por_que,
            })
    return out


# ── Resumen de trayectoria (anclas computadas, no elegidas) ──────────────────
#
# Defecto 2026-08-13 (Deep Dive BPD): la §1 resumió la trayectoria desde el PICO ("de 74.81
# en junio 2024… tres puntos en seis trimestres") y la §9 desde el INICIO DE VENTANA ("ocho
# cortes consecutivos —de 74.30 a 71.76—"). Las dos eran correctas y las dos citaban puntos
# reales de la misma serie, pero el documento nunca dijo que eran anclas distintas, así que
# leído de corrido se contradice consigo mismo en el indicador principal.
#
# El modelo elegía el ancla porque el contexto le daba la serie cruda y nada más. Acá se
# COMPUTAN las tres lecturas posibles con su nombre, para que la sección cite una y diga
# cuál es. Mismo principio que la dirección de las comparaciones: la relación se sirve.


def resumen_de_trayectoria(serie: List[Dict[str, Any]], *,
                           clave_periodo: str = "period_end",
                           clave_score: str = "score") -> Optional[Dict[str, Any]]:
    """Anclas de una serie cronológica ascendente, cada una con su nombre.

    Args:
        serie: puntos ``[{periodo, score}, ...]`` en orden ascendente.

    Returns:
        ``{n_cortes, n_trimestres, primer_corte, ultimo_corte, pico, valle,
        delta_desde_el_inicio, delta_desde_el_pico, lectura}`` o ``None`` con menos de dos
        puntos. ``lectura`` es la frase ya redactada, que nombra AMBAS anclas — es lo que
        impide que dos secciones citen magnitudes distintas sin decir de dónde salen.
    """
    puntos = []
    for p in serie or []:
        if not isinstance(p, dict):
            continue
        per, sc = p.get(clave_periodo), p.get(clave_score)
        if per is None or sc is None:
            continue
        try:
            puntos.append((str(per), float(sc)))
        except (TypeError, ValueError):
            continue
    if len(puntos) < 2:
        return None

    primero, ultimo = puntos[0], puntos[-1]
    pico = max(puntos, key=lambda x: x[1])
    valle = min(puntos, key=lambda x: x[1])
    d_inicio = round(ultimo[1] - primero[1], 2)
    d_pico = round(ultimo[1] - pico[1], 2)

    def _p(par):
        return {"periodo": par[0], "score": round(par[1], 2)}

    verbo = "cede" if d_inicio < 0 else ("gana" if d_inicio > 0 else "se mantiene en")
    lectura = (
        f"la ventana tiene {len(puntos)} cortes ({len(puntos) - 1} trimestres). "
        f"Desde el PRIMER corte de la ventana ({primero[1]:.2f} en {primero[0][:7]}) "
        f"{verbo} {abs(d_inicio):.2f} puntos; desde el PICO "
        f"({pico[1]:.2f} en {pico[0][:7]}) cede {abs(d_pico):.2f}. "
        "Si citás una de las dos magnitudes, decí cuál ancla usás — son distintas y "
        "ambas son correctas."
    )
    return {
        "n_cortes": len(puntos),
        "n_trimestres": len(puntos) - 1,
        "primer_corte": _p(primero),
        "ultimo_corte": _p(ultimo),
        "pico": _p(pico),
        "valle": _p(valle),
        "delta_desde_el_inicio": d_inicio,
        "delta_desde_el_pico": d_pico,
        "lectura": lectura,
    }


# ── Posición por dimensión (anti-superlativo transversal) ────────────────────
#
# Sin esto la narrativa solo conoce sus scores propios y su rank GLOBAL, así que infiere
# superlativos falsos: "el mayor del sistema", "capacidad sin precedente" — cuando en
# realidad es #1 global pero #2 en esa dimensión concreta. El modo se diagnosticó y se curó
# en pensiones; vivía sólo ahí, así que en banca y seguros el guard de `numeric_guard`
# (patrón 8) se saltaba entero por falta de este dato. Esta es la versión transversal.

def posiciones_por_dimension(
    subject_id: Optional[str],
    panel: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Posición de la entidad en CADA dimensión, computada del panel.

    Args:
        subject_id: identificador de la entidad analizada dentro del panel.
        panel: ``[{"id": str, "name": str, "dimensiones": {etiqueta: score}}]``. Forma
            normalizada: cada eje adapta la suya (pensiones/seguros traen ``dimensions``
            como lista de dicts; banca, columnas de sub-componente).

    Returns:
        ``{etiqueta: {dimension, rank, n, es_lider, lider, lider_score}}``. Un score mayor
        es siempre mejor posición (los scores ya vienen orientados, incluido costo).
        Lo lee la narrativa y también ``numeric_guard`` para vetar el superlativo donde la
        entidad no lidera.
    """
    out: Dict[str, Any] = {}
    etiquetas: List[str] = []
    for ent in panel or []:
        for et in (ent.get("dimensiones") or {}):
            if et not in etiquetas:
                etiquetas.append(et)

    for etiqueta in etiquetas:
        filas = []
        for ent in panel or []:
            val = (ent.get("dimensiones") or {}).get(etiqueta)
            if val is None:
                continue
            try:
                filas.append((ent.get("name"), ent.get("id"), float(val)))
            except (TypeError, ValueError):
                continue
        if not filas:
            continue
        filas.sort(key=lambda t: t[2], reverse=True)
        mia = next((t for t in filas if t[1] == subject_id), None)
        if mia is None:
            continue  # la entidad no puntúa esta dimensión: no se afirma posición
        # Ranking de COMPETICIÓN: los empatados comparten el mejor puesto. Con orden simple,
        # dos entidades con el mismo score quedaban 1.ª y 2.ª de forma arbitraria — el
        # informe mostraba "2.º" para un banco con puntaje máximo, contradiciendo su propio
        # percentil 100 y la prosa que decía que superaba a todo su grupo. Además haría que
        # el guardrail vetara como falso un superlativo que SÍ es cierto (empatado en el
        # tope), justo el falso positivo que hay que evitar.
        mejor = filas[0][2]
        rank = sum(1 for t in filas if t[2] > mia[2]) + 1
        empatados = [t for t in filas if t[2] == mia[2]]
        out[etiqueta] = {
            "dimension": etiqueta,
            "rank": rank,
            "n": len(filas),
            "es_lider": mia[2] >= mejor,
            "empatados_en_su_puesto": len(empatados),
            "lider": filas[0][0],
            "lider_score": round(mejor, 2),
        }
    return out


# Cobertura por debajo de la cual un score global NO es comparable con uno completo. El
# corte es 1.0 a propósito: cualquier dimensión ausente cambia lo que el índice mide, y
# «casi completo» ya es otra medición. Los motores que emiten BANDA usan este mismo criterio
# (banda solo con cobertura ~total), así que un score sin banda tampoco debe entrar al rank.
COBERTURA_COMPARABLE = 0.99


def universo_comparable(peers: List[Dict[str, Any]],
                        clave_score: str = "overall_score") -> Dict[str, Any]:
    """Separa el panel en COMPARABLES (cobertura completa) y parciales.

    **Por qué existe.** Un score armado sobre 3 de 5 dimensiones no mide lo mismo que uno
    armado sobre 5, y ordenarlos en una sola lista produce la afirmación «posición 7 de 35»
    sin que el lector pueda saber de qué 35 se habla. Es el mismo problema que en banca se
    resolvió agrupando el ranking por tipo de entidad: comparar cosas no comparables.

    Los parciales NO se descartan —omitirlos los haría desaparecer sin aviso, que es peor—:
    se devuelven aparte y marcados, para que la superficie los muestre diciendo qué les falta.

    Un ítem sin ``coverage`` se trata como COMPLETO: los motores que no exponen cobertura no
    deben perder su ranking por una clave que nunca escribieron.

    >>> u = universo_comparable([{"overall_score": 70.0, "coverage": 1.0},
    ...                          {"overall_score": 74.6, "coverage": 0.65}])
    >>> len(u["comparables"]), len(u["parciales"])
    (1, 1)
    >>> u["parciales"][0]["cobertura"]
    0.65
    """
    conscore = [p for p in peers if p.get(clave_score) is not None]
    comparables: List[Dict[str, Any]] = []
    parciales: List[Dict[str, Any]] = []
    for p in conscore:
        cob = p.get("coverage")
        (parciales if (cob is not None and cob < COBERTURA_COMPARABLE)
         else comparables).append(p)
    comparables.sort(key=lambda p: p[clave_score], reverse=True)
    parciales.sort(key=lambda p: p[clave_score], reverse=True)
    return {
        "comparables": comparables,
        "parciales": [{**p, "cobertura": p.get("coverage")} for p in parciales],
        "n_comparables": len(comparables),
        "n_parciales": len(parciales),
    }


def rank_comparable(slug: Optional[str], universo: Dict[str, Any],
                    clave_slug: str = "slug") -> Dict[str, Any]:
    """Posición dentro del universo COMPARABLE, más el contexto para narrarla sin mentir.

    Devuelve ``rank=None`` y ``comparable=False`` cuando el propio ítem tiene cobertura
    parcial: en ese caso no hay posición que afirmar, y decirlo es la información.
    """
    comp = universo["comparables"]
    rank = next((i + 1 for i, p in enumerate(comp) if p.get(clave_slug) == slug), None)
    return {
        "rank": rank,
        "n_comparables": len(comp),
        "n_parciales": universo["n_parciales"],
        "comparable": rank is not None,
        "criterio": (f"posición entre las {len(comp)} entidades con las cinco dimensiones "
                     f"medidas; {universo['n_parciales']} quedan fuera del orden por cobertura "
                     f"parcial y se listan aparte con lo que les falta"),
    }


# ── Razones contra referencia (la relación que faltaba servir) ────────────────
#
# `comparaciones_vs_referencia` sirve la DIRECCIÓN y la BRECHA en puntos. Faltaba la tercera
# forma de relacionar dos cifras —cuántas VECES una es la otra— y el modelo la seguía
# derivando a mano. Defecto real (Deep Dive de banca, 2026-03-31, §12): «una rentabilidad
# sobre activos (0.39%) que TRIPLICA el umbral de alerta respecto al promedio de bancos
# múltiples (1.61%)». Las dos cifras eran correctas y estaban servidas; la razón es 0.24×, y
# la §10 del mismo informe lo decía bien («una cuarta parte de la velocidad de sus pares»).
#
# La prosa de razón es frecuente, no marginal: en ese único informe hay cinco afirmaciones de
# ese tipo. Y ningún chequeo determinista las miraba —«triplica» no tiene dígitos que parear—,
# así que la única red era el juez semántico, que corrió sobre ese texto y lo dejó pasar.

#: Debajo de este valor absoluto, un denominador vuelve la razón inestable: con una mora de
#: 0.00% (Citibank, corte 2026-03) o un ROA de 0.06% (Banesco), dividir produce un número que
#: cambia de orden de magnitud con el último decimal.
PISO_DENOMINADOR = 0.10

#: Fracciones que un analista SÍ escribe. Se sirven ya redactadas para que copiar sea más
#: fácil que derivar — es toda la tesis de este módulo.
_FRACCIONES = [
    (0.25, "una cuarta parte"), (0.33, "un tercio"), (0.50, "la mitad"),
    (0.75, "tres cuartas partes"), (2.0, "el doble"), (3.0, "el triple"),
    (4.0, "el cuádruple"),
]
_TOLERANCIA_FRACCION = 0.04


def _frase_de_razon(r: float) -> tuple:
    """``(frase, conector)`` de la razón.

    La tolerancia es RELATIVA a la fracción, no absoluta: con un margen fijo, un 0.29 se
    redondeaba a «una cuarta parte» —un 16% de error en una frase que suena exacta—. Relativa,
    0.25 admite ±0.01 y 2.0 admite ±0.08, que es lo que hace correcto llamar «el doble» a un
    2.05 y no a un 2.4.
    """
    for valor, nombre in _FRACCIONES:
        if abs(r - valor) <= _TOLERANCIA_FRACCION * valor:
            return nombre, "del"
    return f"{r:.2f} veces", "el"


def _lectura_de_razon(razon: float, etiqueta: str, ambos_neg: bool) -> str:
    """La razón como CLÁUSULA lista para copiar — misma tesis que ``_lectura`` para la
    dirección: si copiar es más fácil que derivar, el modelo copia."""
    frase, conector = _frase_de_razon(razon)
    if ambos_neg:
        # Con ambos en pérdida la razón se lee sobre MAGNITUDES y en clave de pérdida: decir
        # "es el doble" de un número negativo invierte la gravedad al oído.
        puente = "de lo que pierde el" if conector == "del" else "lo que pierde el"
        return f"pierde {frase} {puente} {etiqueta} ({razon:.2f}× esa pérdida)"
    return f"es {frase} {conector} {etiqueta} ({razon:.2f}× su nivel)"


def razones_vs_referencia(
    valores: Dict[str, Optional[float]],
    referencias: Dict[str, Dict[str, Optional[float]]],
    *,
    direcciones: Optional[Dict[str, Optional[str]]] = None,
) -> List[Dict[str, Any]]:
    """Cuántas VECES el valor de la entidad es su referencia, con la relación ya resuelta.

    Hermana de ``comparaciones_vs_referencia`` y se sirve junto a ella: la brecha ordena
    magnitudes, la razón las hace sentir. Tres relaciones posibles, y la que NO es una razón
    es la más importante:

    ``razon``
        Ambos valores del mismo signo. Se sirve ``razon_vs_referencia`` y la cláusula.
        Con ambos negativos la razón se computa sobre magnitudes y se dice en clave de
        pérdida ("pierde 2.3 veces lo que pierde el grupo").

    ``cruce_de_cero``
        Signos opuestos. **No se publica razón, y no porque haya que ocultarla: porque la
        razón informa MAL.** En el corte 2026-03 hay 24 casos reales; dos de ellos: JMMB con
        ROA −0.26 contra una mediana de +1.52 da −0.17×, y Banco Activo con −13.76 da −9.04×.
        El hecho es el mismo en los dos —la entidad pierde mientras su grupo gana— y la razón
        los hace parecer de naturaleza distinta, además de leerse "−0.17×" como una diferencia
        menor cuando es un cambio de signo. El cruce de cero es EL hallazgo, viaja marcado
        (``cruza_cero``), y la magnitud la sigue dando la brecha en puntos, que sí ordena
        (−15.28 pp contra −1.78 pp).

    ``no_procede``
        Denominador por debajo de ``PISO_DENOMINADOR``, o indicador de ÓPTIMO INTERMEDIO
        (``direcciones[ind] == "target"``), donde estar al doble del promedio no es mejor ni
        peor y la lectura correcta ya la da ``posicion_vs_optimo``. Se DECLARA el motivo: un
        campo ausente se lee como que nadie miró.

    Los nombres de campo llevan su sujeto (``razon_vs_referencia``, no ``razon``) a propósito:
    el defecto de §12 fue exactamente reatribuir una razón a la referencia equivocada.
    """
    out: List[Dict[str, Any]] = []
    for indicador, refs in (referencias or {}).items():
        val = (valores or {}).get(indicador)
        if val is None or not isinstance(refs, dict):
            continue
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        es_target = (direcciones or {}).get(indicador) == "target"
        for etiqueta, ref in refs.items():
            if ref is None:
                continue
            try:
                r = float(ref)
            except (TypeError, ValueError):
                continue
            fila: Dict[str, Any] = {
                "indicador": indicador, "valor": round(v, 4),
                "referencia": etiqueta, "valor_referencia": round(r, 4),
                "cruza_cero": False,
            }
            if es_target:
                fila.update(relacion="no_procede", lectura=None, motivo=(
                    "indicador de óptimo intermedio: una razón contra el promedio no dice si "
                    "mejora o empeora — la lectura válida es la posición vs el óptimo"))
            elif (v < 0) != (r < 0):
                gana, pierde = ("la referencia", "la entidad") if v < 0 else ("la entidad", "la referencia")
                fila.update(
                    relacion="cruce_de_cero", cruza_cero=True,
                    brecha=round(v - r, 2),
                    lectura=(
                        f"no hay razón que valga: {pierde} está en terreno negativo "
                        f"({(v if v < 0 else r):.2f}) y {gana} en positivo "
                        f"({(r if v < 0 else v):.2f}) — es un cambio de SIGNO, no de magnitud; "
                        f"la distancia es de {abs(v - r):.2f} puntos"),
                    motivo="signos opuestos: la razón se lee como una diferencia menor")
            elif abs(r) < PISO_DENOMINADOR:
                fila.update(relacion="no_procede", lectura=None, motivo=(
                    f"la referencia ({r:.2f}) está demasiado cerca de cero: la razón cambia de "
                    "orden de magnitud con el último decimal — usá la brecha en puntos"))
            else:
                razon = abs(v) / abs(r)
                ambos_neg = v < 0 and r < 0
                fila.update(
                    relacion="razon",
                    razon_vs_referencia=round(razon, 2),
                    factor_para_igualar_referencia=(round(1 / razon, 2) if razon else None),
                    lectura=_lectura_de_razon(razon, etiqueta, ambos_neg),
                )
            out.append(fila)
    return out


def factores_hasta_umbral(
    valores: Dict[str, Optional[float]],
    umbrales: Dict[str, Optional[float]],
    *,
    que_es: str,
) -> List[Dict[str, Any]]:
    """Cuánto debe multiplicarse cada indicador para ALCANZAR su umbral.

    Es una relación DISTINTA de la razón contra una referencia —"dónde deberías estar" no es
    "dónde está el mercado"— y por eso viaja en su propia lista, con su propio nombre de
    campo y su propia glosa. Fundirlas en una cláusula fue el error literal de §12: «una
    rentabilidad sobre activos (0.39%) que triplica el umbral de alerta respecto al promedio
    de bancos múltiples (1.61%)» mezcla el umbral con el promedio y sale falsa contra los dos.

    Se sirve porque da contexto de mercado —cuán lejos está la entidad de la frontera que el
    modelo de scoring reconoce—, no para reemplazar la comparación contra pares.
    """
    out: List[Dict[str, Any]] = []
    for indicador, umbral in (umbrales or {}).items():
        val = (valores or {}).get(indicador)
        if val is None or umbral is None:
            continue
        try:
            v, u = float(val), float(umbral)
        except (TypeError, ValueError):
            continue
        fila: Dict[str, Any] = {"indicador": indicador, "valor": round(v, 4),
                                "umbral": round(u, 4), "que_es": que_es}
        if (v < 0) != (u < 0) or abs(v) < PISO_DENOMINADOR:
            fila.update(factor_para_alcanzar_umbral=None, lectura=(
                f"la distancia al umbral ({u:.2f}) es de {abs(u - v):.2f} puntos; no se "
                "expresa como múltiplo porque el valor actual no lo admite"))
        else:
            f = abs(u) / abs(v)
            fila.update(
                factor_para_alcanzar_umbral=round(f, 2),
                lectura=(f"debería multiplicarse por {f:.2f} para alcanzar el {que_es} "
                         f"({u:.2f}); hoy está en {v:.2f}"))
        out.append(fila)
    return out
