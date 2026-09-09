"""Compact AI context for the construction conjuncture (ICC) narrative.

The narrative engine receives a SMALL, pre-digested context (ICC score, band, the four
dimensions with their metric + contribution, and the latest-year levels) — never raw
series — so prompts stay cheap and honest about provenance. Module-local, mirrors
:mod:`free_zones_intel.ai_context`.
"""
from typing import Any, Dict, List, Optional
from shared.data.bcrd_sectors import BCRDSectorsClient
from shared.data.mivhed_client import MIVHEDClient
from shared.narrative.atribucion import Fuente, bloque_de_atribucion


#: Los DOS emisores del eje. Se construyen del conector: etiqueta y licencia salen del
#: mismo objeto que trae el dato, así que cambiar de conector las cambia juntas.
_MIVHED = Fuente.de_cliente(
    MIVHEDClient, descripcion="MIVHED (licencias de construcción), datos abiertos")
_BCRD = Fuente.de_cliente(
    BCRDSectorsClient, descripcion="BCRD (PIB construcción), estadísticas oficiales")


_DIM_LABELS = {
    "production": "Producción del sector (crec. real PIB construcción 3y, BCRD)",
    "pipeline": "Pipeline de permisos (CAGR m² licenciados 3y, MIVHED)",
    "typology_diversification": "Diversificación tipológica (HHI por tipología, MIVHED)",
    "geographic_breadth": "Amplitud geográfica (HHI por provincia, MIVHED)",
}
# clave de dimensión → bloque de métricas + campo de "ritmo" a exponer
_METRIC = {"production": ("production", "avg_growth"), "pipeline": ("pipeline", "cagr"),
           "typology_diversification": ("typology", "hhi"),
           "geographic_breadth": ("geography", "hhi")}


def _financiamiento(perfil: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Delega en `shared.perfil_del_sector.contexto_del_perfil_del_sector`.

    El cuerpo vivía acá y era el único. Subió a `shared/` al cablear el segundo eje: cuatro
    copias de la misma forma es como una se queda atrás. Se conserva el nombre local porque
    es el que usan los tests de este módulo.

    **`actividad` se OMITE, y es el único eje que la omite.** Este contexto ya publica el
    crecimiento del PIB de construcción del BCRD como `construction_gdp_growth_latest_pct` y
    `..._3y_pct`: sumarle la misma lectura con otro nombre pondría dos cifras de crecimiento
    del mismo sector en el mismo contexto y el modelo elige la que le cae más cerca.
    """
    from shared.perfil_del_sector import contexto_del_perfil_del_sector
    return contexto_del_perfil_del_sector(perfil, "construccion", omitir=("actividad",))


def construction_ai_context(index: Dict[str, Any], period: str,
                            perfil: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Compact context for the construction conjuncture assessment.

    *index* is the ``compute_construction_index`` output. Surfaces the dimensions (score +
    metric + contribution) and the latest-year levels so the narrative explains the score
    and stays honest about provenance/coverage."""
    dims = index.get("dimensions") or {}
    rows: List[Dict[str, Any]] = []
    for key, d in dims.items():
        block_key, metric_key = _METRIC.get(key, ("", ""))
        m = index.get(block_key) or {}
        rows.append({
            "dimension": _DIM_LABELS.get(key, key),
            "score": d.get("score"),
            "weight": d.get("weight"),
            "contribution": d.get("contribution"),
            "metric": m.get(metric_key),
            "provenance": d.get("provenance"),
        })
    levels = index.get("levels") or {}
    inv = levels.get("investment_dop")
    # Desagregado por tipología (m² licenciados + participación por tipo de construcción) —
    # dato real del MIVHED; top 5 por m² para que la narrativa cite el peso físico de cada
    # segmento (p.ej. Comercial y oficinas) sin fabricar. NO se expone la "inversión" por
    # tipología: es un costo estándar derivado (m² × tarifa), redundante con los m² y distinto
    # del valor tasado de la ONE (ver mivhed_client.parse_licenses).
    typ_breakdown = ((index.get("typology") or {}).get("breakdown")) or []
    typology_rows = [{
        "typology": r.get("typology"),
        "permits": r.get("permits"),
        "sqm": r.get("sqm"),
        "sqm_share_pct": r.get("sqm_share"),
    } for r in typ_breakdown[:5]]
    # Capa autoritativa ONE: valor tasado REAL (tasación) + construcciones validadas por
    # tipología. Anual; se atribuye a la ONE y NO se confunde con el costo derivado del MIVHED.
    one = index.get("one_typology") or {}
    one_bt = one.get("by_typology") or {}
    one_rows = [{
        "typology": lbl,
        "licencias": d.get("licencias"),
        "construcciones": d.get("construcciones"),
        "sqm": d.get("sqm"),
        "valor_tasado_mm_dop": (round(d["valor_tasado"] / 1e6, 1)
                                if d.get("valor_tasado") is not None else None),
    } for lbl, d in sorted(one_bt.items(),
                           key=lambda kv: (kv[1] or {}).get("valor_tasado") or 0,
                           reverse=True)[:5]]
    return {
        "period": period,
        "icc_score": index.get("icc_score"),
        "band": index.get("band"),
        "coverage": index.get("coverage"),
        "direction": "mayor score = construcción con mejor coyuntura (producción + pipeline)",
        "dimensions": rows,
        "permits": levels.get("permits"),
        "sqm_licensed": levels.get("sqm"),
        "investment_licensed_mm_dop": round(inv / 1e6) if inv is not None else None,
        "construction_gdp_growth_latest_pct": levels.get("prod_growth_latest"),
        "construction_gdp_growth_3y_pct": levels.get("prod_growth_3y"),
        "top_typology": levels.get("top_typology"),
        "top_typology_share_pct": levels.get("top_typology_share"),
        "typology_breakdown": typology_rows,
        "one_valor_tasado_year": one.get("year"),
        "one_typology_valor_tasado": one_rows,
        "top_province": levels.get("top_province"),
        "top_province_share_pct": levels.get("top_province_share"),
        "score_global": index.get("icc_score"),
        **_financiamiento(perfil),
        **bloque_de_atribucion(_MIVHED, _BCRD),
        "note": ("Sobre dato real: PIPELINE de permisos (MIVHED, líder) + PRODUCCIÓN "
                 "efectiva (PIB construcción BCRD). Índice de coyuntura — distingue "
                 "actividad LÍDER (permisos) de PRODUCCIÓN realizada (PIB). Agregado "
                 "nacional anual; los permisos MIVHED arrancan en 2022 (historia corta para "
                 "el flujo de permisos); sin validación retrospectiva de resultados. La inversión licenciada es nominal "
                 "(RD$); no la confundas con la inversión ejecutada."),
    }


def construction_delta_context(delta: Dict[str, Any], periodo_del_informe: str) -> Dict[str, Any]:
    """Contexto de la sección del MOVIMIENTO DEL MES. Bloque CERRADO: el modelo lo copia.

    **Todas las relaciones vienen resueltas.** Dirección, variación, línea base y su tipo se
    computan en ``shared/observations/delta.py``; acá solo se reetiquetan para el narrador. El
    modelo acierta las cifras y falla las relaciones, y además el guard numérico exige que
    toda cifra del texto se trace al contexto: si el modelo produce el número, no hay contra
    qué trazarlo.

    **Cada cifra viaja con su sujeto y su medida.** ``metros_cuadrados_licenciados_del_mes``,
    no ``valor``; ``variacion_pct_vs_mismo_mes_del_anio_anterior``, no ``variacion``. El
    modelo reatribuye al sujeto más cercano — así se publicó una vez «cuatro compañías» donde
    eran cuatro ramos.

    **Lo que no se pudo leer viaja también.** ``series_sin_lectura`` va al contexto con su
    motivo: una lista que solo trae lo que salió bien se lee como que todo salió bien.
    """
    return {
        "periodo_del_movimiento": delta.get("periodo"),
        "periodo_del_indice_anual_del_informe": periodo_del_informe,
        "emisor_del_movimiento": delta.get("emisor"),
        "series_del_mes": delta.get("series") or [],
        "series_sin_lectura": delta.get("sin_lectura") or [],
        "metros_cuadrados_licenciados_por_provincia_del_mes": delta.get("provincias") or [],
        "metros_cuadrados_licenciados_por_tipologia_del_mes": delta.get("tipologias") or [],
        **bloque_de_atribucion(_MIVHED),
        "regla_de_alcance": (
            "Esta sección LEE el movimiento y su magnitud. NO explica su causa: la atribución "
            "de este producto es por sección y fuente, no por oración, así que una afirmación "
            "causal no tendría con qué respaldarse."),
        "note": ("El movimiento del mes es un FLUJO de licencias emitidas (indicador líder: el "
                 "permiso precede a la obra), no producción ejecutada. Se compara contra el "
                 "MISMO mes del año anterior porque la serie tiene estación. La ventana móvil "
                 "de doce meses, cuando viene, es la magnitud comparable con el índice anual "
                 "de este informe. La inversión del MIVHED no se sirve: es un costo estándar "
                 "derivado de los m² con una tarifa fija, no un valor tasado."),
    }
