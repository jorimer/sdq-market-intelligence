"""Banking-specific narrative generation wrapper.

Delegates to ``shared.narrative.claude_engine.NarrativeEngine`` and adds
banking-domain context (section mapping, sub-component focus, etc.).
"""
import asyncio
from typing import Dict, Optional

from shared.narrative.claude_engine import NarrativeResult, narrative_engine
from shared.narrative.derived import resumen_de_trayectoria
from modules.banking_score.scoring.weights import (
    SOLIDEZ_INDICATORS,
    CALIDAD_INDICATORS,
    EFICIENCIA_INDICATORS,
    LIQUIDEZ_INDICATORS,
    DIVERSIFICACION_INDICATORS,
)

# Indicators that belong to each sub-component (for focused per-dimension analysis).
_SUB_INDICATORS: Dict[str, list] = {
    "solidez": SOLIDEZ_INDICATORS,
    "calidad": CALIDAD_INDICATORS,
    "eficiencia": EFICIENCIA_INDICATORS,
    "liquidez": LIQUIDEZ_INDICATORS,
    "diversificacion": DIVERSIFICACION_INDICATORS,
}
_SUB_LABELS: Dict[str, str] = {
    "solidez": "Solidez Financiera",
    "calidad": "Calidad de Activos",
    "eficiencia": "Eficiencia y Rentabilidad",
    "liquidez": "Liquidez",
    "diversificacion": "Diversificación",
}

# Sections required per report type
REPORT_SECTIONS: Dict[str, list] = {
    "full_rating": [
        "executive_summary",
        "solidez_financiera",
        "calidad_activos",
        "eficiencia_rentabilidad",
        "liquidez",
        "diversificacion",
        "risk_assessment",
        "comparative",
        "recommendation",
    ],
    "scorecard": ["executive_summary", "recommendation"],
    "communique": ["executive_summary"],
    "datawatch": ["executive_summary", "trend_analysis"],
    "wire": ["executive_summary"],
    "criteria": ["risk_assessment"],
    "sector_outlook": ["sector_outlook"],
    "anuario": ["anuario"],
    "revision_anual": ["revision_anual"],
}

# Map each section to the NarrativeEngine template name
_SECTION_TO_TEMPLATE: Dict[str, str] = {
    "executive_summary": "banking_summary",
    "solidez_financiera": "subcomponent_focus",
    "calidad_activos": "subcomponent_focus",
    "eficiencia_rentabilidad": "subcomponent_focus",
    "liquidez": "subcomponent_focus",
    "diversificacion": "subcomponent_focus",
    "risk_assessment": "banking_risk",
    "comparative": "banking_comparative",
    "recommendation": "banking_recommendation",
    "entorno_operativo": "banking_operating_env",
    "soporte_soberano": "banking_support_context",
    "trend_analysis": "trend_analysis",
    "sector_outlook": "sector_outlook",
    "anuario": "anuario_sistema",
    "revision_anual": "revision_anual",
}

# Plantillas de banking que van por la RUTA CEREBRO (axis="banking"): obtienen la Barra de
# Insight (conclusión-primero), la doctrina anti-jerga y el guardrail numérico. El resto
# (trend_analysis, sector_outlook) sigue en ruta legacy.
_CEREBRO_TEMPLATES = frozenset({
    "subcomponent_focus", "banking_summary", "banking_comparative",
    "banking_risk", "banking_recommendation", "banking_operating_env",
    "banking_support_context",
    # El anuario vive en `THIN_TEMPLATES` (ruta cerebro) y faltaba acá, así que el motor lo
    # mandaba por la ruta LEGACY —donde esa plantilla no existe— y caía al relleno estático
    # EN SILENCIO. El primer anuario de producción salió con las tablas correctas y la sección
    # de análisis diciendo «el análisis cualitativo ampliado se incorpora en la versión
    # completa del producto». Registrado pero inalcanzable, igual que su endpoint.
    "anuario_sistema",
    # Misma trampa, mismo remedio: sin esta línea la Revisión Anual saldría hueca.
    "revision_anual",
})

# Profundidad POR SECCIÓN (alineada con shared.products.section_mode), para que el deep dive
# PROFUNDICE en vez de re-narrar: el RIESGO forward es la capa profunda (deep → DEEP_DIRECTIVE
# vía cerebro, 700-1000 palabras de cadena causal); el CIERRE accionable es corto (standard,
# nunca inflado); el resto sigue el mode del nivel (detailed en niveles nombrados). Las
# secciones de ruta legacy con tablas verbosas (trend_analysis) suben a 'deep' SOLO por
# presupuesto de tokens (ahí 'deep' no agrega DEEP_DIRECTIVE).
# `sector_outlook` se suma tras un PDF entregado TRUNCADO a mitad de oración: su plantilla
# pide hasta 800 palabras y corría con el presupuesto `standard` (1024 tokens), que en
# español no alcanza (~1.120). `trend_analysis` ya estaba acá por lo mismo.
_DEEP_SECTIONS = frozenset({"risk_assessment", "trend_analysis", "sector_outlook",
                            "anuario", "revision_anual"})


def _section_mode(section: str, base_mode: str) -> str:
    """Mode de narrativa por sección: el cierre accionable corto, el riesgo profundo, el
    resto al mode pedido. Ver _DEEP_SECTIONS."""
    if section == "recommendation":
        return "standard"
    if section in _DEEP_SECTIONS:
        return "deep"
    return base_mode


# Boletines cuyo sujeto es el SISTEMA, no una entidad. `criteria` no está: no se narra en
# absoluto (se genera del motor, ver criteria_doc).
_SYSTEM_REPORT_TYPES = frozenset({"wire", "datawatch", "sector_outlook", "anuario"})


def _build_system_context(report_type: str, scope_name: str, period: str,
                          benchmarks: Optional[Dict],
                          anuario: Optional[Dict] = None) -> Dict:
    """Contexto de un boletín de SISTEMA: promedios sectoriales y de grupos de pares.

    Deliberadamente NO incluye `overall_score`, `sub_components` ni `indicators`: un reporte
    de sistema no tiene entidad, y pasarlos en cero era exactamente lo que hacía que el
    modelo respondiera "el score consolidado es cero, no puedo analizar" en el cuerpo de un
    PDF de cliente. Lo que sí tiene —y basta para un resumen ejecutivo del sistema— son los
    benchmarks que `trend_analysis` y `sector_outlook` ya consumen bien.
    """
    ctx: Dict = {
        "ambito": scope_name,
        "period": period,
        "tipo_de_boletin": report_type,
        "encuadre": (
            "Este boletín describe el SISTEMA bancario dominicano en su conjunto. No hay "
            "entidad individual bajo análisis: no la pidas ni señales su ausencia."
        ),
    }
    if benchmarks and isinstance(benchmarks, dict):
        if benchmarks.get("sector_averages"):
            ctx["promedios_sistema"] = benchmarks["sector_averages"]
        if benchmarks.get("peer_groups"):
            ctx["grupos_de_pares"] = benchmarks["peer_groups"]
        if benchmarks.get("regulatory_limits"):
            ctx["limites_regulatorios"] = benchmarks["regulatory_limits"]
        # UNIVERSO declarado: dos poblaciones distintas dan cifras distintas para el mismo
        # período. Sin decirlo en el cuerpo, dos lectores comparan peras con naranjas sin
        # saberlo — y el informe se vende como "determinista y reproducible".
        proc = benchmarks.get("procedencia") or {}
        if proc.get("universo"):
            ctx["universo"] = {
                "descripcion": proc["universo"],
                "n_entidades": proc.get("n_sistema"),
                "composicion": proc.get("composicion"),
                "estadistico": proc.get("estadistico"),
            }
            ctx["encuadre"] = ctx.get("encuadre", "") + (
                f" DECLARÁ EL UNIVERSO: los agregados son la {proc['estadistico']} de "
                f"{proc.get('n_sistema')} {proc['universo']}. Dilo explícitamente al menos "
                "una vez —cuántas entidades y de qué tipos— para que el lector nunca compare "
                "cifras de poblaciones distintas sin saberlo.")
        # Cualquier otra clave del bloque (p. ej. concentración del sistema) pasa tal cual.
        for k, v in benchmarks.items():
            if k not in ("sector_averages", "peer_groups", "regulatory_limits") and v:
                ctx.setdefault(k, v)
    # Los hechos del AÑO, ya computados (ver `reports/anuario`). Van enteros: la mediana por
    # corte, el cambio por tipo, los cambios de banda y el universo con sus parciales. El
    # modelo no calcula nada de esto — y el campo `medias_y_medianas_divergen` existe para que
    # no pueda titular el año con la media cuando ambas dicen lo contrario.
    if anuario:
        ctx["anuario"] = anuario

    return ctx


# Etiqueta LEGIBLE de cada grupo de pares — la que el analista debe usar al nombrar la base
# de la comparación. Nombrar contra qué se compara no es cosmético: un indicador puede estar
# por debajo del sistema y por encima de su grupo de pares a la vez (la mora de BPD lo está),
# y confundir las bases fue justamente el bug de dirección del 2026-08-05.
_PEER_GROUP_LABEL: Dict[str, str] = {
    # Claves de los benchmarks MEDIDOS del panel (por tipo de entidad supervisada). El
    # grupo se deriva del catálogo, no de una lista de nombres fija que envejece con cada
    # fusión. Se conservan las claves viejas mientras exista el fallback declarado.
    "banca_multiple": "promedio de bancos múltiples",
    "aap": "promedio de asociaciones de ahorros y préstamos",
    "banco_ahorro_credito": "promedio de bancos de ahorro y crédito",
    "corporacion_credito": "promedio de corporaciones de crédito",
    "cambiaria": "promedio de agentes de cambio",
    "fiduciaria": "promedio de fiduciarias",
    "large_banks": "promedio de bancos grandes (referencia declarada)",
    "medium_banks": "promedio de bancos medianos (referencia declarada)",
}


def _comparaciones_resueltas(all_indicators: Dict, benchmarks: Optional[Dict],
                             entity_type: Optional[str] = None) -> list:
    """Comparaciones indicador↔referencia con la DIRECCIÓN ya computada.

    El modelo no debe derivar "por encima / por debajo": erra la relación aunque las cifras
    sean correctas (dos informes de cliente salieron con el sentido invertido, contradiciendo
    su propia tabla de pares). Misma cura que ``derived_figures`` aplica a aportes y deltas —
    servir el resultado para que lo COPIE. El detector de ``numeric_guard`` queda como alarma
    de regresión, no como corrector de turno.
    """
    from shared.data.sib_client import INDICATOR_TO_BENCHMARK
    from shared.narrative.derived import comparaciones_vs_referencia
    from modules.banking_score.scoring.indicator_detail import INDICATOR_META

    if not isinstance(benchmarks, dict):
        return []
    sector = benchmarks.get("sector_averages") or {}
    peers = benchmarks.get("peer_groups") or {}

    valores, referencias = {}, {}
    for ind, bkey in INDICATOR_TO_BENCHMARK.items():
        blob = all_indicators.get(ind)
        raw = blob.get("raw") if isinstance(blob, dict) else None
        if raw is None:
            continue
        refs: Dict[str, Optional[float]] = {}
        if sector.get(bkey) is not None:
            refs["promedio del sistema"] = sector[bkey]
        for gname, grp in peers.items():
            # Solo el grupo de pares de la PROPIA entidad. Comparar un banco múltiple
            # contra el promedio de agentes de cambio o de fiduciarias es ruido, no señal
            # — es la lección que ya documentaba `_named_peers` y que un panel por tipo
            # vuelve a poner al alcance. Sin tipo conocido se usan todos (compat).
            if entity_type and gname != entity_type and gname in _PEER_GROUP_LABEL:
                continue
            if isinstance(grp, dict) and grp.get(f"{bkey}_avg") is not None:
                etiqueta = grp.get("label")
                refs[f"promedio de {etiqueta}" if etiqueta
                     else _PEER_GROUP_LABEL.get(gname, f"promedio {gname}")] = grp[f"{bkey}_avg"]
        if refs:
            valores[ind] = raw
            referencias[ind] = refs
    # La UNIDAD viaja con la comparación: el HHI es un índice de 0 a 10.000, y sin esto su
    # brecha salía enunciada en "puntos porcentuales" — cifra correcta, unidad imposible.
    unidades = {ind: (INDICATOR_META.get(ind) or {}).get("unit") for ind in valores}
    # El SENTIDO DE LA ESCALA viaja con la comparación para que el veredicto —¿esta posición
    # es fortaleza o debilidad?— se compute acá y no lo tenga que deducir el modelo uniendo
    # dos hechos que hasta ahora llegaban en lugares distintos del contexto.
    direcciones = {ind: (INDICATOR_META.get(ind) or {}).get("direction") for ind in valores}
    return comparaciones_vs_referencia(valores, referencias, unidades=unidades,
                                       direcciones=direcciones)


def _razones_resueltas(all_indicators: Dict, benchmarks: Optional[Dict],
                       entity_type: Optional[str] = None) -> list:
    """Razones (cuántas VECES) contra las MISMAS referencias que las comparaciones.

    Hermana de ``_comparaciones_resueltas``: aquélla sirve la dirección y la brecha en
    puntos, ésta el múltiplo. El modelo derivaba la razón a mano y la erraba — «un ROA de
    0.39% que triplica el promedio de 1.61%» cuando es 0.24×.

    Las direcciones del registro viajan para que los indicadores de ÓPTIMO INTERMEDIO
    (`ltd`, `exposicion_re`, `migracion`) no reciban una razón: estar al doble del promedio
    ahí no es mejor ni peor.
    """
    from shared.data.sib_client import INDICATOR_TO_BENCHMARK
    from shared.narrative.derived import razones_vs_referencia
    from modules.banking_score.scoring.indicator_detail import INDICATOR_META

    if not isinstance(benchmarks, dict):
        return []
    sector = benchmarks.get("sector_averages") or {}
    peers = benchmarks.get("peer_groups") or {}
    valores, referencias = {}, {}
    for ind, bkey in INDICATOR_TO_BENCHMARK.items():
        blob = all_indicators.get(ind)
        raw = blob.get("raw") if isinstance(blob, dict) else None
        if raw is None:
            continue
        refs: Dict[str, Optional[float]] = {}
        if sector.get(bkey) is not None:
            refs["promedio del sistema"] = sector[bkey]
        for gname, grp in peers.items():
            if entity_type and gname != entity_type and gname in _PEER_GROUP_LABEL:
                continue
            if isinstance(grp, dict) and grp.get(f"{bkey}_avg") is not None:
                etiqueta = grp.get("label")
                refs[f"promedio de {etiqueta}" if etiqueta
                     else _PEER_GROUP_LABEL.get(gname, f"promedio {gname}")] = grp[f"{bkey}_avg"]
        if refs:
            valores[ind] = raw
            referencias[ind] = refs
    direcciones = {ind: (INDICATOR_META.get(ind) or {}).get("direction") for ind in valores}
    return razones_vs_referencia(valores, referencias, direcciones=direcciones)


def _factores_hasta_umbral(scoring_result: Dict) -> list:
    """Cuánto debe multiplicarse cada indicador para alcanzar el umbral de sensibilidad.

    Relación DISTINTA de la razón contra el mercado —"dónde deberías estar" no es "dónde
    está el mercado"— y por eso viaja aparte. Fundirlas en una cláusula fue el error de §12.
    Se sirve porque da contexto: cuán lejos está la entidad de la frontera que el modelo
    reconoce.
    """
    from shared.narrative.derived import factores_hasta_umbral

    sens = scoring_result.get("sensibilidades") or {}
    inds = scoring_result.get("indicators") or {}
    umbrales, valores = {}, {}
    for fila in (sens.get("palancas_alza") or []):
        ind, u = fila.get("indicador"), fila.get("umbral_raw")
        blob = inds.get(ind) if ind else None
        raw = blob.get("raw") if isinstance(blob, dict) else None
        if ind and u is not None and raw is not None:
            umbrales[ind], valores[ind] = u, raw
    if not umbrales:
        return []
    return factores_hasta_umbral(
        valores, umbrales,
        que_es="umbral de sensibilidad (mejorar hasta ahí sube el score)")


_SENTIDO = {
    "higher": "un valor MÁS ALTO del indicador es MEJOR",
    "lower": "un valor MÁS BAJO del indicador es MEJOR",
}


def _semantica_indicadores(keys: list, indicadores: Dict) -> Dict:
    """Qué MIDE cada indicador y qué implica el valor observado — computado, no inferido.

    El contexto de sub-componente servía ``raw`` y ``score`` y nada más. Con eso, la única
    pista que el modelo tiene sobre si la cifra es buena o mala es el SCORE, y de ahí deduce
    la glosa. Para un indicador de ÓPTIMO INTERMEDIO esa deducción es inválida: el score es
    alto a AMBOS lados del óptimo.

    Fue el segundo defecto del LTD de BPD (2026-08-13), el que sobrevivió a corregir la
    dirección numérica. Con 92.45% y score 98.62 la §5 escribió «destina proporcionalmente
    MENOS de cada peso captado en préstamos» y «preserva margen para atender retiros» —la
    lectura de un LTD BAJO— mientras la §7 del mismo informe decía lo contrario y bien. La
    cifra y la brecha estaban correctas; lo invertido era el SIGNIFICADO.

    Sirve, por indicador: qué mide, en qué sentido corre la escala y —cuando el óptimo es
    intermedio— de qué lado del óptimo cayó el valor. Sin esto el modelo lo adivina.
    """
    from modules.banking_score.scoring.indicator_detail import INDICATOR_META

    out: Dict = {}
    for k in keys:
        meta = INDICATOR_META.get(k)
        blob = indicadores.get(k)
        if not meta or not isinstance(blob, dict):
            continue
        unidad = meta.get("unit", "")
        bloque: Dict = {"mide": meta.get("que", ""), "unidad": unidad}
        direccion = meta.get("direction")
        optimo = meta.get("optimo")
        if direccion in _SENTIDO:
            bloque["sentido_de_la_escala"] = _SENTIDO[direccion]
        elif direccion == "target" and optimo is not None:
            bloque["sentido_de_la_escala"] = (
                f"ÓPTIMO INTERMEDIO en {optimo:g}{unidad}: alejarse en CUALQUIER dirección "
                "empeora la lectura. Un score alto NO significa que el valor sea alto ni "
                "bajo — significa que está cerca del óptimo.")
            raw = blob.get("raw")
            v: Optional[float] = None
            if raw is not None:
                try:
                    v = float(raw)
                except (TypeError, ValueError):
                    v = None
            if v is not None:
                lado = "POR ENCIMA" if v > optimo else ("POR DEBAJO" if v < optimo else "EN")
                brecha_u = "puntos porcentuales" if unidad == "%" else (unidad or "puntos")
                bloque["posicion_vs_optimo"] = (
                    f"el valor observado ({v:.2f}{unidad}) está {lado} del óptimo "
                    f"({optimo:g}{unidad}), a {abs(v - optimo):.2f} {brecha_u}")
        out[k] = bloque
    return out


# Sub-component key lookup for focused sections
_SUB_COMPONENT_MAP: Dict[str, str] = {
    "solidez_financiera": "solidez",
    "calidad_activos": "calidad",
    "eficiencia_rentabilidad": "eficiencia",
    "liquidez": "liquidez",
    "diversificacion": "diversificacion",
}


def _build_section_context(
    section: str,
    bank_name: str,
    scoring_result: Dict,
    period: str,
    benchmarks: Optional[Dict] = None,
) -> Dict:
    """Build the context dict that gets serialized into the Claude prompt."""
    all_indicators = scoring_result.get("indicators", {})
    # Amplitud (Fase 4): trayectoria multi-período + percentil vs el sistema. Vienen en
    # el scoring_result (calculadas en snapshot con DB); pueden faltar en muestras/tests.
    traj = scoring_result.get("trayectorias") or {}
    pct = scoring_result.get("percentiles") or {}

    # Entorno Operativo (Fase 4): telón macro del BCRD (factores reales del contrato
    # compartido). Contexto propio — ni sub-componente ni panorama de la entidad: es el
    # entorno sistémico común, encuadrado para el perfil del banco.
    if section == "entorno_operativo":
        return {
            "entity_name": bank_name,
            "period": period,
            # Los DOS EJES, no el símbolo: lo que entra al contexto es lo que la narrativa
            # termina escribiendo, así que pasarle el tier reintroduciría por texto la
            # notación que la superficie retiró.
            # Las bandas viajan CON su magnitud. Sin el score del eje, el modelo tiene
            # enfrente `overall_score` y una banda, y relaciona lo único que ve: así se
            # escribe «con un score de 60,06 se ubica En vigilancia», que es falso —la
            # banda sale de Resiliencia, que excluye eficiencia—. El hueco es lo que lo
            # llena mal.
            "ejecucion": scoring_result.get("ejecucion"),
            "resiliencia": scoring_result.get("resiliencia"),
            "banda_ejecucion": scoring_result.get("banda_ejecucion"),
            "banda_resiliencia": scoring_result.get("banda_resiliencia"),
            "entorno_macro": scoring_result.get("entorno_macro", {}),
        }

    # Soporte y Techo Soberano (Fase 6): overlay de contexto estilo Fitch (soporte estatal,
    # importancia sistémica, techo soberano). Contexto propio — NO es el score standalone,
    # que se mantiene puro; se presenta como capa analítica separada.
    if section == "soporte_soberano":
        return {
            "entity_name": bank_name,
            "period": period,
            # Los DOS EJES, no el símbolo: lo que entra al contexto es lo que la narrativa
            # termina escribiendo, así que pasarle el tier reintroduciría por texto la
            # notación que la superficie retiró.
            # Las bandas viajan CON su magnitud. Sin el score del eje, el modelo tiene
            # enfrente `overall_score` y una banda, y relaciona lo único que ve: así se
            # escribe «con un score de 60,06 se ubica En vigilancia», que es falso —la
            # banda sale de Resiliencia, que excluye eficiencia—. El hueco es lo que lo
            # llena mal.
            "ejecucion": scoring_result.get("ejecucion"),
            "resiliencia": scoring_result.get("resiliencia"),
            "banda_ejecucion": scoring_result.get("banda_ejecucion"),
            "banda_resiliencia": scoring_result.get("banda_resiliencia"),
            "overall_score": scoring_result.get("overall_score", 0),
            "soporte_soberano": scoring_result.get("soporte_soberano", {}),
        }

    sub_key = _SUB_COMPONENT_MAP.get(section)

    # Sub-component sections: a TIGHT context with only this dimension's indicators,
    # its driver/drag and its peer stats — so the model analyses the dimension in
    # depth instead of re-deriving the whole bank (which read as repetitive).
    if sub_key:
        keys = _SUB_INDICATORS.get(sub_key, [])
        ind = {k: all_indicators[k] for k in keys if k in all_indicators}
        scored = {
            k: v for k, v in ind.items()
            if isinstance(v, dict) and v.get("available", True) and v.get("score") is not None
        }
        driver = max(scored, key=lambda k: scored[k]["score"], default=None)
        drag = min(scored, key=lambda k: scored[k]["score"], default=None)
        ctx: Dict = {
            "entity_name": bank_name,
            "period": period,
            # Los DOS EJES, no el símbolo: lo que entra al contexto es lo que la narrativa
            # termina escribiendo, así que pasarle el tier reintroduciría por texto la
            # notación que la superficie retiró.
            # Las bandas viajan CON su magnitud. Sin el score del eje, el modelo tiene
            # enfrente `overall_score` y una banda, y relaciona lo único que ve: así se
            # escribe «con un score de 60,06 se ubica En vigilancia», que es falso —la
            # banda sale de Resiliencia, que excluye eficiencia—. El hueco es lo que lo
            # llena mal.
            "ejecucion": scoring_result.get("ejecucion"),
            "resiliencia": scoring_result.get("resiliencia"),
            "banda_ejecucion": scoring_result.get("banda_ejecucion"),
            "banda_resiliencia": scoring_result.get("banda_resiliencia"),
            "sub_componente": _SUB_LABELS.get(sub_key, sub_key),
            "score_sub_componente": scoring_result.get("sub_components", {}).get(sub_key, 0),
            "indicadores": ind,
            # Qué mide cada uno y qué implica su valor. Sin esto el modelo deduce el
            # significado del score, y en un indicador de óptimo intermedio esa deducción
            # es inválida (ver `_semantica_indicadores`).
            "semantica_indicadores": _semantica_indicadores(keys, ind),
            "impulsor": driver,
            "lastre": drag,
        }
        # Amplitud de la dimensión: la trayectoria del score del sub-componente, su
        # percentil vs el sistema, y —por indicador de la dimensión— su serie reciente
        # y su percentil. Da al cerebro la profundidad Fitch (evolución + posición
        # relativa) en vez de solo el corte actual.
        traj_sub = (traj.get("sub") or {}).get(sub_key)
        if traj_sub:
            ctx["trayectoria_sub_componente"] = traj_sub
            resumen = resumen_de_trayectoria(traj_sub)
            if resumen:
                ctx["resumen_trayectoria_sub_componente"] = resumen
        pct_sub = (pct.get("sub") or {}).get(sub_key)
        if pct_sub:
            ctx["percentil_sub_componente"] = pct_sub
        traj_ind = traj.get("indicators") or {}
        pct_ind = pct.get("indicators") or {}
        amplitud = {}
        for k in keys:
            if k not in ind:
                continue
            block = {}
            if traj_ind.get(k):
                block["trayectoria"] = traj_ind[k][-8:]
            if pct_ind.get(k):
                block["percentil"] = pct_ind[k]
            if block:
                amplitud[k] = block
        if amplitud:
            ctx["amplitud_indicadores"] = amplitud
        if benchmarks and isinstance(benchmarks, dict):
            sub_bench = benchmarks.get(sub_key) or benchmarks.get(section)
            if sub_bench:
                ctx["pares"] = sub_bench
        # Direcciones ya resueltas, acotadas a los indicadores de ESTA dimensión.
        comps = [c for c in _comparaciones_resueltas(
                     all_indicators, benchmarks, scoring_result.get("entity_type"))
                 if c["indicador"] in ind]
        if comps:
            ctx["comparaciones"] = comps
        razones = [r for r in _razones_resueltas(
            all_indicators, benchmarks, scoring_result.get("entity_type"))
            if r["indicador"] in ind]
        if razones:
            ctx["razones"] = razones
        return ctx

    # Overview sections (executive summary, comparative, recommendation…) keep the
    # full picture.
    ctx = {
        "entity_name": bank_name,
        "period": period,
        "overall_score": scoring_result.get("overall_score", 0),
        # Las bandas viajan CON su magnitud. Sin el score del eje, el modelo tiene
        # enfrente `overall_score` y una banda, y relaciona lo único que ve: así se
        # escribe «con un score de 60,06 se ubica En vigilancia», que es falso —la
        # banda sale de Resiliencia, que excluye eficiencia—. El hueco es lo que lo
        # llena mal.
        "ejecucion": scoring_result.get("ejecucion"),
        "resiliencia": scoring_result.get("resiliencia"),
        "banda_ejecucion": scoring_result.get("banda_ejecucion"),
        "banda_resiliencia": scoring_result.get("banda_resiliencia"),
        "sub_components": scoring_result.get("sub_components", {}),
        "indicators": all_indicators,
        # La misma semántica que reciben las secciones de dimensión: si solo la tuviera
        # una de las dos superficies, el informe podría volver a contradecirse entre §5 y
        # §7 — que es exactamente la forma en que se manifestó el defecto.
        "semantica_indicadores": _semantica_indicadores(
            list(all_indicators), all_indicators),
        # Encuadre (Fase 3): mantiene la prosa consistente con las Limitaciones —
        # el score es fortaleza financiera standalone, no un rating de crédito.
        "encuadre": (
            "La calificación SDQ mide FORTALEZA FINANCIERA STANDALONE sobre dato público "
            "supervisado; NO es un rating de crédito ni mide probabilidad de incumplimiento, "
            "y no incorpora soporte soberano ni techo país. No la describas como rating "
            "crediticio ni la compares con las escalas de calificadoras internacionales."
        ),
    }
    # Amplitud a nivel de entidad: trayectoria del score global + de cada
    # sub-componente, y percentil vs el sistema (score global + sub-componentes). El
    # comparativo y el resumen ejecutivo leen posición relativa y evolución, no solo
    # el corte actual.
    if traj.get("overall"):
        ctx["trayectoria_score"] = traj["overall"]
        # Anclas COMPUTADAS de la trayectoria. Sin esto cada sección elegía la suya —la §1
        # el pico, la §9 el inicio de ventana— y el informe citaba dos magnitudes distintas
        # del mismo deterioro sin decir que eran anclas distintas. Ambas eran correctas;
        # el documento se leía contradiciéndose.
        resumen = resumen_de_trayectoria(traj["overall"])
        if resumen:
            ctx["resumen_trayectoria"] = resumen
    if traj.get("sub"):
        ctx["trayectoria_sub"] = traj["sub"]
    # Pesos del sub-componente: el chequeo determinista de "aporta N puntos" necesita
    # score×peso, y sin los pesos ese patrón quedaba muerto en la ruta de reportes. Al
    # modelo también le sirven — explican por qué una dimensión mueve más que otra.
    try:
        from modules.banking_score.scoring.weights import get_sub_component_weights
        pesos_sub = get_sub_component_weights(scoring_result.get("entity_type"))
        ctx["pesos_sub_componentes"] = pesos_sub
        # QUÉ MOVIÓ el score, ya descompuesto. La dimensión que más se movió NO es la que más
        # movió el resultado —los pesos difieren— y esa cuenta el modelo la hacía a ojo: un
        # informe entregado atribuyó el deterioro de un semestre al «colapso de eficiencia»
        # cuando en ese semestre la eficiencia MEJORÓ y aportó a favor. Las cifras estaban
        # todas bien; la atribución era una derivación.
        if traj.get("sub"):
            from shared.narrative.derived import aportes_al_cambio
            aportes = aportes_al_cambio(traj["sub"], pesos_sub)
            if aportes:
                ctx["aportes_al_cambio"] = aportes
    except Exception:  # noqa: BLE001 — el contexto nunca depende de esto
        pass
    if pct.get("overall"):
        ctx["percentil_score"] = pct["overall"]
    if pct.get("sub"):
        ctx["percentil_sub"] = pct["sub"]
    # Sensibilidades (Fase 4): palancas al alza / riesgos a la baja con umbral en valor
    # crudo y delta al score global. El riesgo forward y el cierre accionable las citan
    # para dar umbrales concretos ("a qué nivel una señal pasa de vigilancia a acción").
    if scoring_result.get("sensibilidades"):
        ctx["sensibilidades"] = scoring_result["sensibilidades"]
    if benchmarks:
        ctx["benchmarks"] = benchmarks
        # El veto de superlativos de `numeric_guard` lee `posiciones_dimension` en el NIVEL
        # SUPERIOR del contexto; viene anidada bajo los pares nombrados. Sin elevarla, el
        # patrón se salta entero y la narrativa puede afirmar "el mayor del sistema" en una
        # dimensión que otro lidera.
        pos = ((benchmarks.get("named_peers") or {}).get("posiciones_dimension")
               if isinstance(benchmarks, dict) else None)
        if pos:
            ctx["posiciones_dimension"] = pos
        # Las comparaciones contra sistema y pares llegan RESUELTAS: el resumen ejecutivo y
        # el comparativo son las secciones donde el modelo más las enuncia, y donde erró el
        # sentido teniendo las dos cifras correctas a la vista.
        comps = _comparaciones_resueltas(all_indicators, benchmarks,
                                         scoring_result.get("entity_type"))
        if comps:
            ctx["comparaciones"] = comps
        razones = _razones_resueltas(all_indicators, benchmarks,
                                     scoring_result.get("entity_type"))
        if razones:
            ctx["razones"] = razones
    # El factor hasta el umbral no depende de los benchmarks (sale de las sensibilidades),
    # así que va fuera del bloque: el Deep Dive lo trae aunque el panel no dé referencias.
    factores = _factores_hasta_umbral(scoring_result)
    if factores:
        ctx["factores_hasta_umbral"] = factores
    return ctx


async def generate_report_narratives(
    report_type: str,
    bank_name: str,
    scoring_result: Dict,
    period: str,
    benchmarks: Optional[Dict] = None,
    anuario: Optional[Dict] = None,
    revision: Optional[Dict] = None,
) -> Dict[str, str]:
    """Generate all narrative sections required for *report_type*.

    Returns ``{section_key: narrative_text}``.
    """
    # El documento de criterios NO se narra: es la metodología, determinista y generada de
    # la configuración del motor. Se intercepta acá —el choke point de AMBAS rutas (informe
    # de sistema y por-banco)— para que ninguna pueda pedirle a la IA que narre una
    # plantilla por-banco con un scoring_result vacío, que era el defecto original. Sin
    # sesión de DB se omite el backtest vivo; jamás se inventa una cifra.
    if report_type == "criteria":
        from modules.banking_score.reports.criteria_doc import build_criteria_document
        return build_criteria_document()

    sections = REPORT_SECTIONS.get(report_type, ["executive_summary"])
    narratives: Dict[str, str] = {}
    # Boletines de SISTEMA: su sujeto es el sistema, no una entidad. `executive_summary`
    # resolvía a `banking_summary` —plantilla POR BANCO— y recibía un `scoring_result` en
    # ceros, así que el modelo se negaba a analizar y esa disculpa quedaba impresa. En
    # DataWatch convivía con una sección de Tendencias completa sobre el mismo período: se
    # lee como bug en vivo, no como función pendiente.
    is_system = report_type in _SYSTEM_REPORT_TYPES

    for section in sections:
        if section == "anuario":
            # El anuario tiene su propio sujeto —el sistema en un AÑO— y su contexto son los
            # hechos ya computados. Va antes del caso general de sistema porque no es un
            # boletín de corte: su unidad es el año.
            template = "anuario_sistema"
            context = _build_system_context(report_type, bank_name, period, benchmarks,
                                            anuario=anuario)
        elif section == "revision_anual":
            # La Revisión Anual tiene sujeto de ENTIDAD pero unidad de AÑO, así que no entra
            # ni por el caso de sistema ni por el de sección de corte: su contexto son los
            # hechos del año ya computados (ver `reports/revision_anual`), con el telón de
            # pares del cierre para que la posición relativa tenga contra qué leerse.
            template = "revision_anual"
            context = {"entity_name": bank_name, "period": period,
                       "revision_anual": revision or {}}
            if benchmarks:
                context["benchmarks"] = benchmarks
        elif is_system and section == "executive_summary":
            template = "system_summary"
            context = _build_system_context(report_type, bank_name, period, benchmarks)
        else:
            template = _SECTION_TO_TEMPLATE.get(section, "banking_summary")
            context = _build_section_context(
                section, bank_name, scoring_result, period, benchmarks,
            )

        # Use 'detailed' mode for full_rating to get longer outputs; las secciones de
        # panorama suben a 'deep' (4096) para no truncarse (ver _section_mode).
        base_mode = "detailed" if report_type == "full_rating" else "standard"
        mode = _section_mode(section, base_mode)

        # Ruta cerebro para las plantillas banking (resumen, comparativo, riesgo, decisión y
        # sub-componentes): Barra de Insight + doctrina anti-jerga + guardrail. El lector es
        # fijo (comité de crédito). trend_analysis/sector_outlook quedan en ruta legacy.
        cerebro = {"axis": "banking", "audience": "comite_credito"} \
            if template in _CEREBRO_TEMPLATES else {}

        result: NarrativeResult = await narrative_engine.generate(
            context=context,
            template=template,
            mode=mode,
            **cerebro,
        )
        narratives[section] = result.text

    return narratives


async def generate_named_narratives(
    sections: list,
    bank_name: str,
    scoring_result: Dict,
    period: str,
    benchmarks: Optional[Dict] = None,
    mode: str = "detailed",
) -> Dict[str, str]:
    """Genera narrativas para una lista EXPLÍCITA de secciones (driven por el manifiesto
    de nivel del producto), reutilizando el mapeo sección→template y el contexto
    enfocado existentes. No reemplaza ``generate_report_narratives`` (keyed por
    report_type); es la vía de la productización por niveles.
    """
    narratives: Dict[str, str] = {}
    # Una llamada IA por sección, generadas en PARALELO (asyncio.gather): antes era secuencial
    # (~15s × N secciones). El cliente Anthropic ya libera el event loop (asyncio.to_thread en
    # claude_engine); aquí solo falta lanzar las llamadas juntas. La construcción de contexto
    # (barata) sigue en el loop; solo el await del motor va al gather.
    pending: list = []   # (section, kwargs de generate)
    for section in sections:
        template = _SECTION_TO_TEMPLATE.get(section, "banking_summary")
        context = _build_section_context(section, bank_name, scoring_result, period, benchmarks)
        cerebro = {"axis": "banking", "audience": "comite_credito"} \
            if template in _CEREBRO_TEMPLATES else {}
        # Profundidad por sección: riesgo profundo, cierre corto, resto al mode pedido
        # (ver _section_mode).
        pending.append((section, dict(
            context=context, template=template, mode=_section_mode(section, mode), **cerebro,
        )))

    async def _gen(section: str, kwargs: Dict) -> tuple:
        result: NarrativeResult = await narrative_engine.generate(**kwargs)
        return section, result.text

    for section, text in await asyncio.gather(*(_gen(s, k) for s, k in pending)):
        narratives[section] = text
    return narratives
