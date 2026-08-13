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


def _lectura(direccion: str, etiqueta: str, brecha: float) -> str:
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
        return (f"en línea con el {etiqueta} (brecha de {brecha:+.2f} puntos "
                "porcentuales, materialmente nula)")
    return f"{direccion} del {etiqueta} en {abs(brecha):.2f} puntos porcentuales"


def comparaciones_vs_referencia(
    valores: Dict[str, Optional[float]],
    referencias: Dict[str, Dict[str, Optional[float]]],
    *,
    materialidad_pp: float = MATERIALIDAD_PP,
) -> List[Dict[str, Any]]:
    """Dirección y brecha de cada (indicador, referencia), ya resueltas.

    Args:
        valores: ``{indicador: valor_de_la_entidad}``.
        referencias: ``{indicador: {etiqueta_legible: valor_de_referencia}}``. La etiqueta
            es la que el analista debe usar al nombrar la base ("promedio del sistema",
            "promedio de pares grandes"): nombrar CONTRA QUÉ se compara es la mitad del
            problema, porque un indicador puede estar bajo el sistema y sobre su grupo de
            pares a la vez.

    Returns:
        Lista de ``{indicador, valor, referencia, valor_referencia, direccion, brecha_pp,
        lectura}`` con ``direccion`` ∈ {"por encima", "por debajo", "en línea"} y ``lectura``
        la cláusula ya redactada (ver ``_lectura``). Agnóstica de eje: el llamador arma el
        mapeo indicador→referencias con el vocabulario de su dominio.
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
            brecha = round(v - r, 2)
            if abs(brecha) < materialidad_pp:
                direccion = "en línea"
            else:
                direccion = "por encima" if brecha > 0 else "por debajo"
            out.append({
                "indicador": indicador,
                "valor": round(v, 4),
                "referencia": etiqueta,
                "valor_referencia": round(r, 4),
                "direccion": direccion,
                "brecha_pp": brecha,
                "lectura": _lectura(direccion, str(etiqueta), brecha),
            })
    return out


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
