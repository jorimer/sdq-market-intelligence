"""Compact AI context for the sector attractiveness (IAI) narrative.

The narrative engine receives a SMALL, pre-digested context (IAI score, band,
the per-dimension contributions, the strongest/weakest dimension and the real-vs-
rubric provenance) — never the whole peer dataset — so prompts stay cheap and
focused (plan §5.2). Module-local, mirrors :mod:`macro_political_risk.ai_context`.
"""
from typing import Any, Dict, List, Optional

from shared.narrative.derived import derived_figures

_DIM_LABELS = {
    "sector": "Sector (tamaño y crecimiento, BCRD)",
    "macro": "Exposición macro (contrato macro→sectorial)",
    "business": "Entorno de negocios",
    "talent": "Talento y mano de obra",
    "regulation": "Regulatoria",
}
#: Cada variable del IAI, con el SUJETO y la UNIDAD en el nombre, y la forma en que se va a
#: CITAR. El `raw` del breakdown viene en la unidad del motor y hay dos que no se pueden
#: servir así: la rentabilidad es una razón (0,048) que el modelo escribe como «4,8 %» —la
#: familia de falso positivo del guard que ya costó tres informes— y el empleo viene en
#: personas con decimales. Se transforman acá, una vez, y viajan listos para citar.
#: `(nombre citable con su unidad, nombre CORTO para la frase del puesto, forma de citarlo)`.
#: El corto existe por la regla del sujeto: el puesto se escribe «13 de los 16 sectores con
#: dato de costo del capital» y no «13 de 16», porque el modelo reatribuye el denominador al
#: sujeto más cercano. Verificado en producción: con «2 de 17» servido para el salario y
#: «13 de 16» para la tasa, el informe publicó «segundo puesto entre los dieciséis sectores
#: con dato» — se llevó el denominador de la línea de al lado.
_VARIABLES = {
    "macro_exposure": ("exposición macro del sector (0-100, mayor = el ciclo lo favorece más)",
                       "exposición macro", lambda v: round(v, 1)),
    "ease_of_business": ("facilidad de hacer negocios (0-100)",
                         "facilidad de hacer negocios", lambda v: round(v, 1)),
    "operating_cost": ("costo laboral: salario promedio cotizable del sector, RD$/mes",
                       "costo laboral", lambda v: round(v, 2)),
    "credit_cost": ("costo del capital: tasa promedio ponderada que el sistema financiero le "
                    "cobra al sector, en POR CIENTO", "costo del capital", lambda v: round(v, 2)),
    "profitability": ("rentabilidad del sector (utilidad sobre ingresos), en POR CIENTO",
                      "rentabilidad", lambda v: round(v * 100.0, 2)),
    "labor_availability": ("ocupados en la rama de actividad del sector, en personas",
                           "ocupados de la rama", lambda v: round(v)),
    "skills_index": ("índice de capital humano del país (0-100)",
                     "capital humano", lambda v: round(v, 2)),
    "regulatory_quality": ("calidad regulatoria del país (0-100)",
                           "calidad regulatoria", lambda v: round(v, 2)),
    "regulatory_volatility": ("volatilidad regulatoria del país (desviación de la serie)",
                              "volatilidad regulatoria", lambda v: round(v, 3)),
    "sector_growth": ("crecimiento real del sector, en POR CIENTO",
                      "crecimiento real", lambda v: round(v, 2)),
    "sector_size": ("peso del sector en el valor agregado nacional, en POR CIENTO",
                    "peso en el valor agregado", lambda v: round(v, 3)),
}


def _procedencia_de_la_dimension(detalle):
    """La procedencia de una dimensión, COMPUTADA de sus variables.

    **Estaba transcrita y envejeció.** Acá vivía `_LIVE_DIMS = {"sector", "macro"}` y una
    nota en prosa que le decía al modelo que negocios, talento y regulatoria eran «rúbrica
    declarada». Cuando se escribió era cierto; hoy 8 de las 9 variables del índice corren con
    dato real —TSS, SIB, ENCFT, ENAE, capital humano del Banco Mundial y WGI— y la única
    rúbrica efectiva es `ease_of_business`, porque el Doing Business se descontinuó. El
    resultado era un producto que se subestimaba a sí mismo en el texto que se vende, y el
    prompt además mandaba a no construir conclusión fuerte sobre el 60 % del peso del score.

    Es la misma regla que la doctrina ya se aplica a sí misma: la procedencia se GENERA del
    registro, nunca se afirma en prosa. El breakdown persistido trae `source` por variable
    (lo estampa `_stamp_provenance`), así que la respuesta está en el dato.
    """
    vs = (detalle.get("variables") or {})
    if not vs:
        return {"procedencia": "no declarada", "variables_reales": 0, "variables_totales": 0}
    reales = [k for k, v in vs.items() if v.get("source") == "live"]
    rubrica = sorted(k for k in vs if k not in reales)
    if not reales:
        clase = "rúbrica declarada"
    elif not rubrica:
        clase = "real"
    else:
        clase = "real en parte"
    out = {"procedencia": clase, "variables_reales": len(reales), "variables_totales": len(vs)}
    if rubrica:
        # Se nombran las que SON rúbrica, no las que son reales: es la lista corta, y es la
        # que el modelo necesita para no construir una conclusión fuerte encima.
        out["sobre_rubrica_declarada"] = [_VARIABLES.get(k, (k,))[0] for k in rubrica]
    return out


def _variables_de_la_dimension(detalle, puestos=None):
    """Las variables de una dimensión, con su nombre citable y su valor ya en la unidad en
    que se va a escribir.

    Sin esto el contexto solo llevaba el SCORE de cada dimensión, así que el modelo podía
    decir que negocios lastra y no podía decir POR QUÉ. Agropecuario cambió de banda el
    2026-09-01 al entrar el costo del capital —paga 13,61 % de tasa con el segundo salario
    más bajo del país— y esa frase, que es la única accionable del informe, no se podía
    escribir.
    """
    puestos = puestos or {}
    filas = []
    for var, det in sorted((detalle.get("variables") or {}).items()):
        etiqueta, corto, forma = _VARIABLES.get(var, (var, var, lambda v: v))
        crudo = det.get("raw")
        fila = {
            "variable": etiqueta,
            "valor": forma(crudo) if crudo is not None else None,
            # NO es un percentil, y se llamaba de un modo que invitaba a decirlo: el motor
            # normaliza por min-max sobre el VALOR, no sobre el rango. En un panel sesgado
            # los dos se separan mucho, y el modelo publicó «percentil 25,35».
            "posicion_en_la_escala_de_valor_del_panel_0_100": det.get("normalized"),
            "procedencia": "real" if det.get("source") == "live" else "rúbrica declarada",
        }
        p = puestos.get(var)
        if p:
            # LA relación que el lector quiere, computada contra los sectores que TIENEN la
            # variable — que no son siempre 17: el crédito lo tienen 16 y la rentabilidad 8.
            # LA POBLACIÓN DENTRO DE LA FRASE. «13 de 16» a secas se lo lleva el sujeto más
            # cercano; con el nombre de la variable adentro, la frase no se puede reatribuir.
            fila["puesto_del_sector"] = (
                f"{p['puesto']} de los {p['de']} sectores con dato de {corto} "
                f"(1 = el más favorable)")
        filas.append(fila)
    return filas


def economic_structure_ai_context(structure: Dict[str, Any]) -> Dict[str, Any]:
    """Compact context for the aggregate economic-structure narrative.

    *structure* is the ``get_economic_structure`` output. Surfaces the structural weight
    ranking, the growth drivers vs drags (by contribution) and the aggregate VA growth, so
    the narrative explains which sectors move the economy — distinguishing SIZE (weight)
    from CONTRIBUTION (weight × growth). Honest: real BCRD value-added, no synthetic score."""
    def _slim(r: Dict[str, Any]) -> Dict[str, Any]:
        return {"sector": r.get("sector"), "weight_pct": r.get("weight"),
                "growth_pct": r.get("growth"), "contribution_pp": r.get("contribution"),
                # sujeto-ok: fila ya rotulada con `sector`; «of_growth» nombra el total
                "share_of_growth": r.get("contribution_share")}

    sectors = structure.get("sectors") or []
    return {
        "period": structure.get("period"),
        "total_va_growth_pct": structure.get("total_va_growth"),
        "coverage": structure.get("coverage"),
        # HHI sobre el peso de los SECTORES en el Valor Agregado. La clave interna conserva
        # su nombre; la que ve el modelo nombra la población.
        "concentration_hhi_sectors": structure.get("concentration_hhi"),
        "n_sectors": structure.get("n_sectors"),
        "direction": ("peso = importancia estructural (share del Valor Agregado); "
                      "contribución = peso × crecimiento = aporte real al crecimiento"),
        "structure_top_weight": [_slim(r) for r in sectors[:6]],
        "growth_drivers": [_slim(r) for r in (structure.get("drivers") or [])[:6]],
        "growth_drags": [_slim(r) for r in (structure.get("drags") or [])],
        "source": structure.get("source"),
        "note": ("Real: BCRD PIB por sectores de origen (Valor Agregado base 2018). Mide "
                 "importancia económica y contribución al crecimiento — NO valor exportado "
                 "(esa es otra lente, donde joyería/oro lideran) ni atractividad (IAI). "
                 "Agregado nacional anual; sin score sintético. Si una cifra no está, dilo."),
    }


def sector_ai_context(
    latest: Dict[str, Any],
    sector_name: Optional[str] = None,
    sgps_detail: Optional[Dict[str, Any]] = None,
    puestos: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Compact context for one sector's IAI attractiveness assessment.

    *latest* is the ``/{sector}/latest`` payload (iai_score, iai_band, sgps_score,
    iai_breakdown). Surfaces dimensions sorted by contribution + strongest/weakest,
    flagging which are real vs declared rubric, so the narrative explains (not
    restates) the score and stays honest about provenance."""
    dims = latest.get("iai_breakdown") or {}
    rows: List[Dict[str, Any]] = []
    for key, d in dims.items():
        proc = _procedencia_de_la_dimension(d)
        rows.append({
            "dimension": _DIM_LABELS.get(key, key),
            "score": d.get("score"),
            "weight": d.get("weight"),
            "contribution": d.get("contribution"),
            "provenance": proc["procedencia"],
            "variables_reales_de_la_dimension": (
                f"{proc['variables_reales']} de {proc['variables_totales']}"),
            "sobre_rubrica_declarada": proc.get("sobre_rubrica_declarada"),
            # LO QUE EXPLICA EL SCORE. Sin esto el modelo dice que una dimensión lastra y no
            # puede decir por qué; con esto nombra la variable y su valor.
            "que_hay_dentro": _variables_de_la_dimension(d, puestos),
        })
    scored = [r for r in rows if r["score"] is not None]
    strongest = max(scored, key=lambda r: r["score"], default=None)
    weakest = min(scored, key=lambda r: r["score"], default=None)
    rows.sort(key=lambda r: (r["contribution"] is None, -(r["contribution"] or 0)))

    # Forma canónica para la ruta cerebro: score_global + sub_componentes (con peso) +
    # cifras_derivadas (precompute compartido). Sin serie ni pares en este eje → el
    # precompute solo emite aportes/gaps/superlativos de dimensión.
    subcomp = [{"componente": r["dimension"], "score": r["score"], "peso": r["weight"],
                "procedencia": r["provenance"]} for r in rows]
    return {
        "sector_code": latest.get("sector_code"),
        "sector_name": sector_name,
        "period": latest.get("period"),
        "iai_score": latest.get("iai_score"),
        "iai_band": latest.get("iai_band"),
        "sgps_score": latest.get("sgps_score"),
        "direction": "mayor score = mayor atractivo de inversión",
        "dimensions": rows,
        "strongest_dimension": strongest,
        "weakest_dimension": weakest,
        "acceleration": (sgps_detail or {}).get("acceleration_detail"),
        # La `note` que vivía acá afirmaba en prosa qué era real y qué era rúbrica, y
        # envejeció: decía que negocios, talento y regulatoria eran rúbrica cuando hoy
        # corren con dato real. La procedencia viaja COMPUTADA en cada dimensión.
        # ── canónico (cerebro) ──
        "score_global": latest.get("iai_score"),
        "sub_componentes": subcomp,
        "cifras_derivadas": derived_figures(
            score=latest.get("iai_score"),
            subcomponents=[{"componente": s["componente"], "score": s["score"],
                            "peso": s["peso"]} for s in subcomp],
        ),
    }
