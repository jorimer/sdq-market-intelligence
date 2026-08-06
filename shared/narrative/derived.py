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
        Lista de ``{indicador, valor, referencia, valor_referencia, direccion, brecha_pp}``
        con ``direccion`` ∈ {"por encima", "por debajo", "en línea"}. Agnóstica de eje: el
        llamador arma el mapeo indicador→referencias con el vocabulario de su dominio.
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
            })
    return out
