"""Insurance Intel (SIS · SISALRIL) — API endpoints.

prefix: /api/v1/insurance-intel

F1a exposes the read-only market spine (market series, latest snapshot, national
Pulse) + an AI insight over the pulse + an admin-only sync trigger. The per-insurer
ISF ranking/detail endpoints are wired but return empty until the F1b audited-
financials backfill populates ``insurance_ratings`` — honest, never fabricated.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user, require_role
from shared.auth.models import User, UserRole
from shared.database.session import get_db
from modules.insurance_intel.models.models import (
    InsuranceRating,
    InsuranceSeries,
    InsuranceSnapshot,
)
from modules.insurance_intel.scoring.isf import compute_isf
from modules.insurance_intel.service import build_market_pulse

logger = logging.getLogger("sdq.api.insurance_intel")

router = APIRouter()

_AUDIENCES = {"inversionista", "regulador", "asegurado", "gobierno"}


async def _ai_insight(context: Dict[str, Any], audience: str = "inversionista",
                      deep: bool = False, template: str = "insurance_pulse") -> Optional[Dict[str, Any]]:
    """Claude narrative via the cerebro route (axis=insurance_intel); best-effort."""
    try:
        from shared.narrative.claude_engine import narrative_engine
        res = await narrative_engine.generate(
            context, template=template, mode="deep" if deep else "detailed",
            axis="insurance_intel", audience=audience,
        )
        return {"text": res.text, "model_used": res.model_used, "from_cache": res.from_cache}
    except Exception as e:  # noqa: BLE001 — AI is best-effort, never break the endpoint
        logger.warning("AI insight seguros (%s) no disponible: %s", template, e)
        return None


def _serialize(s: InsuranceSeries) -> Dict[str, Any]:
    return {
        "code": s.series_code, "period": s.period, "value": s.value, "unit": s.unit,
        "frequency": s.frequency, "entity_slug": s.entity_slug, "dimension": s.dimension,
        "source": s.source,
    }


@router.get("/series")
async def list_series(
    dimension: Optional[str] = Query(None, description="ramo (línea) slug; omitir = totales"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(InsuranceSeries).filter(InsuranceSeries.entity_slug.is_(None))
    if dimension:
        q = q.filter(InsuranceSeries.dimension == dimension)
    rows = q.order_by(InsuranceSeries.period.desc()).limit(1000).all()
    return {"series": [_serialize(s) for s in rows], "count": len(rows)}


@router.get("/snapshot")
async def latest_snapshot(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    snap = db.query(InsuranceSnapshot).order_by(InsuranceSnapshot.period.desc()).first()
    if not snap:
        return {"snapshot": None}
    return {"snapshot": {
        "period": snap.period, "headline": snap.headline,
        "series_count": snap.series_count, "entity_count": snap.entity_count,
        "model_version": snap.model_version,
    }}


@router.get("/pulse")
async def market_pulse(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return build_market_pulse(db)


@router.get("/health-pulse")
async def health_pulse(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SFS national health-coverage pulse (SISALRIL/CNSS). None until the SFS sync runs."""
    from modules.insurance_intel.service import build_health_pulse
    hp = build_health_pulse(db)
    return {"health_coverage": hp, "has_data": hp is not None}


@router.get("/insight")
async def pulse_insight(
    audience: str = Query("inversionista"),
    deep: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from modules.insurance_intel.ai_context import market_pulse_context
    pulse = build_market_pulse(db)
    if not pulse.get("has_data"):
        return {"audience": audience, "ai_insight": None, "has_data": False}
    aud = audience if audience in _AUDIENCES else "inversionista"
    ai = await _ai_insight(market_pulse_context(pulse), audience=aud, deep=deep)
    return {"audience": aud, "ai_insight": ai, "has_data": True}


@router.get("/perfil-sdq")
async def perfil_sdq(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Perfil SDQ de seguros: **Ejecución** y **Resiliencia**, dos ejes independientes.

    Reemplaza la lectura de un símbolo único por dos números con significado propio:
    Ejecución mide qué tan bien le va (combined ratio del ciclo) y Resiliencia qué tan
    expuesta está (solvencia, liquidez, reaseguro y volatilidad de siniestralidad).

    Ejecución se calcula sobre el **promedio de 3-5 ejercicios**, no sobre el último año:
    con un solo corte, una catástrofe puntual reclasifica a una aseguradora bien manejada.
    Una entidad sin ciclo suficiente devuelve ``ejecucion: null`` en vez de un promedio
    fabricado con dos años.
    """
    from modules.insurance_intel.scoring.perfil_sdq import (
        ANCLAJE_POR_TIPO, PESOS_RESILIENCIA, T_MINIMO, band_resiliencia_o_none,
        banda_ejecucion, banda_tendencia, calcular_ejes, metricas_del_ciclo, panel_por_aseguradora,
    )
    from modules.insurance_intel.scoring.mezcla_ramos import (
        UMBRAL_MIXTA, UMBRAL_PERSONAS, agrupar_por_entidad, mezcla_de_una,
    )
    from shared.indices.freshness import annotate_freshness

    # Tipo de compañía DERIVADO de la mezcla real de primas. El catálogo del SIS no lo trae.
    # Va como contexto de lectura: un combined de 105% en una compañía de salud y en una de
    # daños pueden no ser lo mismo, y sin el tipo a la vista el lector no puede ni preguntarlo.
    from modules.insurance_intel.models.models import InsuranceEntity
    from modules.insurance_intel.scoring.isf import _canon_map, _official_index

    _ents = (db.query(InsuranceEntity)
             .filter(InsuranceEntity.entity_type == "aseguradora").all())
    _canon, _ = _canon_map(_ents, _official_index())
    _ramos = [{"entity_slug": (_canon.get(str(r.entity_slug))
                               or (None, None, str(r.entity_slug)))[2],
               "dimension": r.dimension, "value": r.value}
              for r in db.query(InsuranceSeries)
              .filter(InsuranceSeries.series_code == "primas_suscritas",
                      InsuranceSeries.entity_slug.isnot(None),
                      InsuranceSeries.dimension.isnot(None)).all()]
    _tipos: Dict[str, Any] = {}
    for _slug, _fs in agrupar_por_entidad(_ramos).items():
        _m = mezcla_de_una(_fs)
        if _m:
            _tipos[_slug] = _m

    panel = panel_por_aseguradora(db)
    filas = []
    for slug, info in panel.items():
        ejes = calcular_ejes(metricas_del_ciclo(info["ejercicios"]),
                             info.get("indice_solvencia"), info.get("indice_liquidez"))
        filas.append({
            "slug": slug, "name": info["name"], "period": info.get("period"),
            "ejecucion": ejes["ejecucion"],
            "banda_ejecucion": banda_ejecucion(ejes["ejecucion"]),
            # El combined ratio queda como la MÉTRICA SUBYACENTE que alimenta el índice, no
            # como una segunda escala visible en paralelo (§5.2).
            "combined_ratio_promedio": ejes["combined_promedio"],
            "ejercicios": ejes["ejercicios"],
            # TRAYECTORIA — aparte del nivel, nunca mezclada en el score. Con nivel y
            # pendiente juntos se lee "buena pero deteriorando", que es la única forma de
            # que el índice sirva como señal temprana y no como fotografía.
            "pendiente_combined": ejes["pendiente_combined"],
            "pendiente_error_estandar": ejes["pendiente_error_estandar"],
            "tendencia": banda_tendencia(ejes["pendiente_combined"],
                                         ejes["pendiente_error_estandar"]),
            "ciclo_comparable": ejes["ciclo_comparable"],
            # El combined ratio es BRUTO: la cesión va al lado para que no se lea como si
            # la compañía retuviera el riesgo que originó.
            "cesion_promedio": ejes["cesion_promedio"],
            "cesion_alta": ejes["cesion_alta"],
            # Tipo DERIVADO de la mezcla real de primas; None cuando no hay desglose. Es
            # contexto de lectura y NO ajusta el score — ver `anclaje_por_tipo`.
            "tipo_derivado": (_tipos.get(slug) or {}).get("tipo"),
            "peso_personas": (_tipos.get(slug) or {}).get("peso_personas"),
            "peso_salud": (_tipos.get(slug) or {}).get("peso_salud"),
            "resiliencia": ejes["resiliencia"],
            "banda_resiliencia": band_resiliencia_o_none(ejes["resiliencia"]),
            "cobertura_resiliencia": ejes["cobertura_resiliencia"],
            "cobertura_suficiente": ejes["cobertura_suficiente"],
            "dimensiones_resiliencia": ejes["dimensiones"],
        })
    filas.sort(key=lambda f: (f["ejecucion"] is not None, f["ejecucion"] or 0), reverse=True)
    corte = annotate_freshness(filas)
    return {
        "perfil": filas, "count": len(filas), "period_end": corte,
        "ejes": {
            "ejecucion": ("Índice 0-100 derivado del combined ratio BRUTO de reaseguro "
                          "(siniestros + gastos operativos sobre primas) promediado sobre "
                          "3-5 ejercicios ponderados por exposición. Al ser bruto mide la "
                          "calidad de lo que la compañía ORIGINA, no la pérdida que "
                          "absorbe: con `cesion_alta` la lectura económica cambia y la tasa "
                          "de cesión va publicada al lado. Misma "
                          "escala y mismas bandas que banca, pensiones y fiduciarias: "
                          "combined 90% → 75, breakeven 100% → 60, 110% → 45."),
            "resiliencia": ("Solvencia y liquidez regulatorias (Ley 146-02), reaseguro y "
                            "volatilidad del loss ratio."),
            "tendencia": (
                f"Pendiente del combined ratio en puntos por año, ponderada por exposición. "
                f"Se publica APARTE del nivel, nunca mezclada en el score: una compañía "
                f"puede tener buen nivel y estar deteriorándose. Se etiqueta Mejora o "
                f"Deteriora SOLO si la pendiente se separa de cero (|t| >= {T_MINIMO:.0f}); "
                f"si no, «Sin señal», que NO es lo mismo que estable: con 3-5 ejercicios y "
                f"esta volatilidad no se puede distinguir movimiento de ruido. El error "
                f"estándar va publicado al lado para que la afirmación sea auditable."),
        },
        # Las dos superficies de seguros miden VENTANAS DISTINTAS. Sin decirlo, un lector que
        # compare ambas encuentra contradicciones aparentes — el caso testigo fue HYLSEG, con
        # 6.8% de siniestralidad en el ISF y 118.8% de combined en el eje, ambos correctos.
        "relacion_con_el_isf": (
            "El Índice de Solidez Financiera mide el ÚLTIMO EJERCICIO cerrado; este eje mide "
            "el CICLO de 3 a 5 ejercicios ponderado por exposición. Una compañía que cambió "
            "de escala o tuvo un año atípico puede verse distinta en cada superficie sin que "
            "ninguna esté mal: responden preguntas distintas."),
        # Promesa de transparencia del spec §5.7, en la superficie que ve el cliente y no
        # solo en el código: los pesos NO se derivaron empíricamente.
        "metodologia": {
            "pesos_resiliencia": PESOS_RESILIENCIA,
            "origen_de_los_pesos": (
                "Juicio experto, no derivado empíricamente. Los pesos reflejan la "
                "importancia relativa que la metodología asigna a cada dimensión; no salen "
                "de una optimización sobre datos históricos."),
            "escala_excluida": (
                "El tamaño de activos NO participa de Resiliencia: lo que convierte tamaño "
                "en resiliencia real es cuánto y cómo reasegura la entidad, que se mide "
                "directamente."),
            "anclaje_por_tipo": ANCLAJE_POR_TIPO,
            "no_es_calificacion_de_riesgo": (
                "Perfil SDQ no es una calificación crediticia ni es comparable con la "
                "notación de una agencia calificadora."),
        },
    }


@router.get("/entity-series")
async def entity_series(
    slug: Optional[str] = Query(None, description="Filtrar una aseguradora; omitir = todas"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Serie anual **por aseguradora** de los agregados auditados (dimension nula).

    ``/series`` solo devuelve la espina de mercado (``entity_slug IS NULL``), así que el
    detalle por compañía y ejercicio —que ya estaba persistido— no era legible desde afuera.
    Sin él no se puede computar la TRAYECTORIA: un promedio de cinco años no distingue una
    compañía que fue de 60% a 80% de otra que fue de 80% a 60%, y esa es justamente la
    diferencia entre una foto y una señal temprana.

    Devuelve también ``reservas_tecnicas``, que es lo que permite aproximar el siniestro
    INCURRIDO (pagado + Δreservas) frente al PAGADO que hoy alimenta el combined ratio.
    """
    q = (db.query(InsuranceSeries)
         .filter(InsuranceSeries.entity_slug.isnot(None),
                 InsuranceSeries.dimension.is_(None)))
    if slug:
        q = q.filter(InsuranceSeries.entity_slug == slug)

    por_entidad: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for r in q.all():
        slug_r, per_r, code_r = str(r.entity_slug), str(r.period), str(r.series_code)
        por_entidad.setdefault(slug_r, {}).setdefault(per_r, {})
        por_entidad[slug_r][per_r][code_r] = r.value

    return {
        "entidades": {s: dict(sorted(p.items())) for s, p in sorted(por_entidad.items())},
        "count": len(por_entidad),
        "nota_de_construccion": {
            "primas_suscritas": "PRIMA SUSCRITA (written), no devengada (earned).",
            "siniestros_pagados": (
                "RECLAMACIONES PAGADAS (paid), no incurridas. No incorpora movimiento de "
                "reservas: para incurrido aproximado, sumar la variación de "
                "reservas_tecnicas."),
            "base": (
                "BRUTA (gross) de reaseguro: la prima cedida no se resta del denominador ni "
                "los recuperables del numerador. Ambos se exponen aparte y alimentan la "
                "dimensión de reaseguro de Resiliencia, no Ejecución."),
            "gastos_operativos": (
                "Seguro DIRECTO (51xx/53xx): comisiones a intermediarios + gastos generales "
                "y administrativos + otros gastos de operación. Las comisiones SÍ están "
                "incluidas. Excluye 5501 (resultado financiero) y reaseguro aceptado."),
        },
    }


@router.get("/mezcla-ramos")
async def mezcla_ramos(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mezcla de primas por ramo y **tipo de compañía derivado** de esa mezcla.

    El catálogo del SIS no trae un campo "tipo de compañía". Pero el desglose de primas por
    ramo sí está persistido por compañía y ejercicio, así que el tipo se computa del negocio
    real en vez de declararse a mano.

    Existe porque el ancla de Ejecución —breakeven del combined ratio en 100%— es un hecho
    económico **para daños**. Salud y personas operan con siniestralidad estructuralmente
    distinta, y sin la mezcla no se puede distinguir "ejecuta mal" de "es otro negocio".
    """
    from modules.insurance_intel.models.models import InsuranceEntity
    from modules.insurance_intel.scoring.isf import _canon_map, _official_index
    from modules.insurance_intel.scoring.mezcla_ramos import (
        UMBRAL_MIXTA, UMBRAL_PERSONAS, agrupar_por_entidad, mezcla_de_una,
    )

    # Las series por ramo están bajo el slug DERIVADO (truncación de hoja de Excel), igual
    # que las de totales. Sin colapsarlas contra el roster, seis aseguradoras —justo las que
    # se recuperaron al arreglar la identidad— quedaban sin tipo. Mismo mapa que el resto.
    ents = (db.query(InsuranceEntity)
            .filter(InsuranceEntity.entity_type == "aseguradora").all())
    canon, _ = _canon_map(ents, _official_index())

    rows = (db.query(InsuranceSeries)
            .filter(InsuranceSeries.series_code == "primas_suscritas",
                    InsuranceSeries.entity_slug.isnot(None),
                    InsuranceSeries.dimension.isnot(None))
            .all())
    filas = [{"entity_slug": (canon.get(str(r.entity_slug)) or (None, None, str(r.entity_slug)))[2],
              "dimension": r.dimension, "value": r.value, "period": r.period} for r in rows]

    salida: list[Dict[str, Any]] = []
    for slug, fs in sorted(agrupar_por_entidad(filas).items()):
        m = mezcla_de_una(fs)
        if m is None:
            # Sin desglose no se clasifica: asumir "daños" por defecto sería clasificar por
            # ausencia de dato, que es justo lo que la doctrina de brecha declarada prohíbe.
            salida.append({"slug": slug, "mezcla": None, "tipo": None})
            continue
        salida.append({"slug": slug, "tipo": m.pop("tipo"), "mezcla": m,
                       "ejercicios": sorted({f["period"] for f in fs})})

    return {
        "entidades": salida, "count": len(salida),
        "metodologia": {
            "origen_del_tipo": (
                "DERIVADO de la mezcla de primas por ramo, no declarado. El catálogo "
                "regulatorio del SIS no trae tipo de compañía."),
            "cortes": (
                f"personas ≥ {UMBRAL_PERSONAS:.0%} de la prima · mixta ≥ "
                f"{UMBRAL_MIXTA:.0%} · daños por debajo. Dentro de personas se separa SALUD "
                f"de VIDA con el mismo corte: una ARS y una compañía de vida no comparten "
                f"ni estructura de siniestralidad ni marco regulatorio. Cortes de JUICIO, "
                f"no derivados empíricamente."),
            "sin_mezcla": (
                "Una compañía sin desglose por ramo devuelve tipo null. No se asume daños "
                "por defecto: sería clasificar por ausencia de dato."),
        },
    }


@router.get("/rankings")
async def rankings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Insurers ranked by ISF. Empty until F1b (audited financials) — honest.

    Cada fila lleva dos marcas que el score solo no transmite:

    * ``stale``/``periods_behind`` — el panel MEZCLA cortes. Autoseguro se rankea con estados
      de 2020 y Confederación del Canadá con los de 2023, junto a 33 aseguradoras de 2024.
      Sus scores aparecían comparables de igual a igual sin ninguna advertencia.
    * ``incumple_solvencia``/``incumple_liquidez`` — los índices de la Ley 146-02 valen 1.0
      cuando la entidad cumple. Incumplirlos es un hecho regulatorio binario, no un matiz de
      score, y hoy se diluye dentro del híbrido ponderado: en el cierre 2024 hay 5
      aseguradoras bajo el mínimo de solvencia y 2 bajo el de liquidez.
    """
    from shared.indices.freshness import annotate_freshness

    results = compute_isf(db)
    scored = [r for r in results if r["overall_score"] is not None]

    def _raw(r: Dict[str, Any], key: str) -> Optional[float]:
        d = next((x for x in r.get("dimensions") or [] if x.get("key") == key), None)
        return d.get("raw") if d and d.get("present") else None

    ranked = []
    for i, r in enumerate(scored):
        liq = _raw(r, "liquidez")
        ranked.append({
            "rank": i + 1, "slug": r["slug"], "name": r.get("name") or r["slug"],
            "overall_score": r["overall_score"], "band": r["band"],
            "band_capped": r.get("band_capped", False),
            "coverage": r["coverage"], "period": r["period"],
            "incumple_solvencia": r.get("incumple_solvencia"),
            "incumple_liquidez": None if liq is None else liq < 1.0,
        })
    corte = annotate_freshness(ranked)
    return {"rankings": ranked, "count": len(ranked), "period_end": corte,
            "scale": "ISF 0-100 (Sólida/Adecuada/En vigilancia/Frágil)",
            "note": None if ranked else "ISF pendiente: estados financieros auditados no ingeridos (F1b)."}


@router.get("/{slug}/detail")
async def entity_detail(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # ``insurance_ratings`` tiene UNA FILA POR PERÍODO desde que se ingiere el histórico
    # (2018→2024). Sin ``order_by`` el ``.first()`` devolvía una fila arbitraria, así que el
    # detalle podía mostrar un año viejo mientras ``/rankings`` —que calcula sobre el último
    # período— mostraba el actual: La Colonial daba 65.6 en el ranking y 54.5 en el detalle.
    r = (db.query(InsuranceRating)
         .filter(InsuranceRating.entity_slug == slug)
         .order_by(InsuranceRating.period.desc()).first())
    if not r:
        return {"found": False, "slug": slug,
                "note": "Sin ISF para esta aseguradora (estados financieros no ingeridos)."}
    return {"found": True, "slug": slug, "period": r.period, "overall_score": r.overall_score,
            "band": r.band, "coverage": r.coverage, "dimensions": r.dimensions}


@router.get("/entity-insight/{slug}")
async def entity_insight(
    slug: str,
    audience: str = Query("inversionista"),
    deep: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from modules.insurance_intel.ai_context import insurance_entity_context
    results = compute_isf(db)
    rating = next((r for r in results if r["slug"] == slug), None)
    if not rating or rating.get("overall_score") is None:
        return {"slug": slug, "ai_insight": None, "has_data": False}
    aud = audience if audience in _AUDIENCES else "inversionista"
    ai = await _ai_insight(insurance_entity_context(rating, results), audience=aud,
                           deep=deep, template="insurance_entity")
    return {"slug": slug, "audience": aud, "ai_insight": ai, "has_data": True}


@router.get("/ars/rankings")
async def ars_rankings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """ARS (health-risk managers) ranked by ISARS. Empty until the ARS sync runs.

    Mismas dos marcas que el ISF, por las mismas razones y verificadas contra producción:

    * ``stale``/``periods_behind`` — SeNaSa (la ARS pública más grande del país) y SEMMA se
      rankeaban con corte 2026-03 contra 2026-04 del resto, sin ninguna advertencia.
    * ``incumple_margen_solvencia`` — el indicador 405 de SISALRIL vale 1.0 cuando la ARS
      cumple. ARS Renacer (0.779) y ARS Dr. Yunén (0.764) lo incumplen y aparecían en banda
      "En vigilancia": el híbrido ponderado diluye un hecho regulatorio binario.
    """
    from modules.insurance_intel.models.models import InsuranceEntity
    from modules.insurance_intel.scoring.ars_rating import compute_ars
    from shared.indices.freshness import annotate_freshness

    results = compute_ars(db)
    names = {e.slug: e.name for e in db.query(InsuranceEntity)
             .filter(InsuranceEntity.entity_type == "ars").all()}

    ranked = []
    for i, r in enumerate(x for x in results if x["overall_score"] is not None):
        ranked.append(
            {"rank": i + 1, "slug": r["slug"], "name": names.get(r["slug"], r["slug"]),
             "category": r.get("category"), "overall_score": r["overall_score"],
             "band": r["band"], "band_capped": r.get("band_capped", False),
             "coverage": r["coverage"], "period": r["period"],
             "incumple_margen_solvencia": r.get("incumple_margen_solvencia")})
    corte = annotate_freshness(ranked)
    return {"rankings": ranked, "count": len(ranked), "period_end": corte,
            "scale": "ISARS 0-100 (Sólida/Adecuada/En vigilancia/Frágil)",
            "note": None if ranked else "ISARS pendiente: sincronización de ARS (BDFINAC) no ejecutada.",
            "caveat": ("Índice sobre los indicadores regulatorios OFICIALES de SISALRIL "
                       "(Portal Estadístico): margen de solvencia (ind. 405) y ROA (ind. 408), "
                       "ambos validados EXACTOS contra el portal; siniestralidad médica (ind. 401) "
                       "y solvencia patrimonial (patrimonio/activo). El capital mínimo (403/404) se "
                       "excluye por magnitudes inconsistentes en algunas ARS (brecha declarada).")}


@router.get("/ars/{ars_slug}/detail")
async def ars_detail(
    ars_slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from modules.insurance_intel.scoring.ars_rating import compute_ars
    r = next((x for x in compute_ars(db) if x["slug"] == ars_slug), None)
    if not r or r["overall_score"] is None:
        return {"found": False, "slug": ars_slug}
    return {"found": True, **r}


@router.post("/sync")
async def trigger_sync(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    from modules.insurance_intel.sis_sync import sis_insurance_sync
    return sis_insurance_sync(db, mode="live")


@router.post("/ars/sync")
async def trigger_ars_sync(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    from modules.insurance_intel.ars_sync import ars_sync
    return ars_sync(db, mode="live")


@router.post("/solvency/sync")
async def trigger_solvency_sync(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    from modules.insurance_intel.solvency_sync import solvency_sync
    return solvency_sync(db, mode="live")


@router.post("/financials/sync")
async def trigger_financials_sync(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    from modules.insurance_intel.financials_sync import sis_financials_sync
    return sis_financials_sync(db)


@router.post("/health/sync")
async def trigger_health_sync(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    from modules.insurance_intel.sisalril_sync import sisalril_sfs_sync
    return sisalril_sfs_sync(db, mode="live")


@router.post("/financials/history/sync")
async def trigger_financials_history(
    since_year: int = Query(2018),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    from modules.insurance_intel.financials_sync import sis_financials_history_sync
    return sis_financials_history_sync(db, since_year=since_year)


@router.post("/backtest")
async def trigger_backtest(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    import json

    from modules.insurance_intel.validation.backtest import build_backtest_report
    from shared.settings.models import AppSetting
    rep = build_backtest_report(db)
    row = db.query(AppSetting).filter(AppSetting.key == "insurance_backtest_report").first()
    payload = json.dumps(rep, ensure_ascii=False)
    if row:
        row.value, row.is_secret = payload, False
    else:
        db.add(AppSetting(key="insurance_backtest_report", value=payload, is_secret=False))
    db.commit()
    return rep


@router.get("/validation")
async def validation(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The persisted ISF backtest report (Gini + CI per signal), or None."""
    import json

    from shared.settings.models import AppSetting
    row = db.query(AppSetting).filter(AppSetting.key == "insurance_backtest_report").first()
    return {"backtest": json.loads(row.value) if row and row.value else None}
