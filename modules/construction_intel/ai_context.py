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
    """El crédito y el costo laboral del sector, para el contexto del modelo.

    **Por qué el eje lo necesitaba.** Medía permisos, m², diversificación tipológica y
    amplitud geográfica: actividad física, sin una sola señal de cómo se financia. Cuánto
    crédito recibe la construcción, a qué tasa y con qué mora sale del cubo de la SIB, y
    hasta la fase 4 del plan de enriquecimiento sectorial solo lo veía banca.

    **El SUJETO en cada clave.** `..._al_sector_construccion_...` y no `credito_pct`: el
    modelo reatribuye una cuota al sujeto más cercano, y este contexto tiene cerca los
    permisos y los m². Así se publicó una vez «cuatro compañías concentran el 87,1%» cuando
    eran cuatro ramos.

    **Las relaciones se COMPUTAN acá y el modelo las copia.** «La construcción paga X puntos
    más de tasa que el promedio del crédito del país» es una resta que el modelo invierte;
    ya pasó en este repo. Va resuelta, con su dirección en palabras.

    Sin perfil devuelve ``{}``: la clave no existe y el modelo no tiene qué citar. No se
    declara la ausencia — decisión del dueño del 2026-08-31.
    """
    if not perfil:
        return {}
    out: Dict[str, Any] = {}
    c = perfil.get("credito_del_sistema") or {}
    if c:
        out["credito_del_sistema_al_sector_construccion"] = {
            "corte_de_esta_capa": c.get("corte"),
            "deuda_del_sistema_al_sector_construccion_dop": c.get(
                "deuda_del_sistema_al_sector"),
            "peso_de_la_construccion_en_la_cartera_del_sistema_pct": c.get(
                "peso_del_sector_en_el_credito_del_pais_pct"),
            "entidades_que_le_prestan_a_la_construccion": c.get("entidades_que_le_prestan"),
            "mora_del_sector_construccion_pct": c.get("mora_pct"),
            "mora_temprana_31_90_del_sector_construccion_pct": c.get(
                "mora_temprana_31_90_pct"),
            "tasa_promedio_ponderada_al_sector_construccion_pct": c.get(
                "tasa_promedio_ponderada_pct"),
            "cobertura_de_provision_sobre_vencida_del_sector_construccion_pct": c.get(
                "cobertura_de_provision_sobre_vencida_pct"),
            "garantia_sobre_deuda_del_sector_construccion_pct": c.get(
                "garantia_sobre_deuda_pct"),
            "credito_promedio_por_operacion_en_construccion_dop": c.get("credito_promedio"),
        }
        # La lectura que el modelo NO debe derivar: es una resta de dos porcentajes y la
        # invierte. Va con la dirección dicha en palabras.
        if c.get("es_agregado"):
            out["credito_del_sistema_al_sector_construccion"]["ojo_la_cifra_es_de_un_"
                                                              "agregado_que_incluye"] = (
                c.get("el_agregado_incluye"))
    sal = perfil.get("costo_laboral") or {}
    if sal:
        out["costo_laboral_del_sector_construccion"] = {
            "salario_promedio_cotizable_en_construccion_dop_mes": sal.get(
                "salario_promedio_cotizable_del_sector_dop_mes"),
            # El AÑO viaja con el número: es una lectura transversal de la TSS y leerla como
            # si fuera del corte del informe sería atribuirle una fecha que no tiene.
            "anio_de_esta_capa": sal.get("anio"),
            "fuente": sal.get("fuente"),
        }
    return out


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
