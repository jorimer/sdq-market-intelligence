"""Tourism Intelligence como ``SectorProduct`` — producto dedicado del sector turismo.

Mono-módulo (patrón Free Zones/Energy): ``tourism_intel`` tiene conector real (ONE,
datos abiertos) + índice ITT (tracción de demanda del destino RD). Implementa el
``Protocol`` ``SectorProduct`` SIN tocar el framework de productos, reusando el motor de
narrativa y los getters PÚBLICOS del módulo (``service``/``ai_context``).

Naturaleza NACIONAL: el "entity" es el sector turismo de RD; no hay firmas →
``entity_roster=()``. El Pulse es el pulso del destino; el nivel nombrado nombra al sector.

REEMPLAZA en el catálogo el corte transversal de ``sector_intel`` para ``tourism``:
el producto dedicado (demanda real ONE) es más fiel al sector que el slice del IAI
transversal. El IAI transversal interno (peer set de 17 sectores) NO se toca — solo
cambia el producto consumible del slot ``tourism`` (``tourism`` sale de
``SECTOR_PRODUCTS`` de sector_intel; sigue en el peer set vía ``bcrd_sectors``).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.products import (
    DataHealth,
    Granularity,
    ProductSnapshot,
    ProductTier,
    SectorProductManifest,
    TierLevelSpec,
    ValidationState,
    distinct_periods,
    register_product,
    section_mode,
)
from shared.products.render import render_product_pdf
from modules.tourism_intel.ai_context import tourism_ai_context
from modules.tourism_intel.models.models import TourismScore
from modules.tourism_intel.service import get_latest, get_scores

logger = logging.getLogger("sdq.products.tourism")

SECTOR_KEY = "tourism"
DISPLAY = "Sector Turismo · RD"
_UNSET = object()

_SECTION_TITLES = {
    "tourism_pulse": "Pulso del Sector Turismo",
    "tourism_assessment": "Evaluación de Tracción Turística (ITT)",
    "positioning": "Posición y Trayectoria",
    "recommendation": "Lectura para Decisión",
    "limitations": "Limitaciones",
}
_LIMITATIONS = (
    "El Índice de Tracción Turística (ITT) se construye sobre datos abiertos de la ONE "
    "(datos.gob.do, llegada de pasajeros vía aérea de no residentes): demanda total, "
    "demanda extranjera, resiliencia y recuperación (nivel frente al pico prepandemia) y "
    "diversificación de mercados (HHI por región emisora). Mide la tracción de la demanda "
    "(volumen, recuperación, concentración de origen); no cubre la oferta hotelera, la tasa "
    "de ocupación ni los ingresos por turismo (divisas en US$), ya que el BCRD discontinuó "
    "esas series estructuradas en 2018-2019 —el Banco Mundial las refleja igualmente "
    "desactualizadas— y hoy solo aparecen como cifra suelta en informes PDF, sin serie "
    "limpia disponible. El dato es anual y agregado nacional, sin desglose por polo "
    "turístico (Punta Cana, Puerto Plata, etc.). Índice preliminar, aún sin validación "
    "retrospectiva de resultados."
)
_NO_DATA = (
    "No hay ITT persistido: el producto está cableado pero su cobertura es insuficiente "
    "para publicar. No se fabrican cifras."
)

# Narrativa CURADA tier-1 de la muestra (exemplar), coherente con el dato real 2025
# (ITT 93.0 «Fuerte», ~8.86M no residentes, ~7.34M extranjeros, recuperación 134.9% del
# pico 2018; CAGR demanda 7.35%, CAGR extranjeros 8.14%; diversificación 65, NA 62.2%).
_SAMPLE_NARRATIVES = {
    "tourism_pulse": (
        "El sector turismo dominicano cierra el período con un **Índice de Tracción "
        "Turística de 93.0/100 —banda Fuerte—**, perfil propio de un destino en expansión "
        "de demanda. Las llegadas de no residentes alcanzan un máximo histórico de **~8.86 "
        "millones** y crecen a **7.4% anual** (CAGR 3 años), por encima del umbral de plena "
        "tracción; la demanda **extranjera genuina** (~7.34 millones, sin la diáspora) "
        "avanza a un ritmo superior, de **8.1% anual**. La **resiliencia** constituye la "
        "fortaleza estructural: las llegadas superan en **35%** el pico pre-pandemia de "
        "2018, lo que indica no solo recuperación sino un nuevo nivel máximo. El principal "
        "contrapunto es la **concentración de mercados**: Norteamérica origina el **62%** de "
        "los turistas extranjeros, una dependencia que conviene diversificar. En términos de "
        "mercado, la demanda se observa firme y resiliente, y el principal factor de riesgo "
        "no es el volumen sino la diversificación del origen."
    ),
    "tourism_assessment": (
        "La tracción del destino RD se evalúa en **93.0/100 (banda Fuerte)**, sostenida por "
        "el crecimiento de demanda y la recuperación, y acotada únicamente por la "
        "concentración de mercados. Las llegadas de no residentes (~8.86 millones) crecen a "
        "7.4% anual y la demanda extranjera (~7.34 millones) a 8.1% —ambas por encima del "
        "objetivo—. La resiliencia es notable: el destino opera 35% por encima de su pico de "
        "2018, señal de una demanda estructuralmente más alta tras la pandemia. El "
        "contrapunto reside en la **diversificación**: con Norteamérica aportando el 62% de "
        "los turistas extranjeros, la base de demanda es sólida pero queda expuesta a un "
        "solo mercado emisor. Desde la óptica del inversionista, la oportunidad de demanda "
        "es clara; el factor a vigilar es la exposición a Norteamérica y el avance hacia "
        "mercados europeos y suramericanos."
    ),
    "positioning": (
        "**El ITT se ubica en banda Fuerte con trayectoria ascendente, traccionada por el "
        "volumen y la recuperación más que por la diversificación.** La lectura de trayectoria "
        "aporta una señal que el nivel por sí solo no transmite: el índice avanza de forma "
        "sostenida en los últimos períodos, impulsado por una demanda que crece por encima de "
        "7% anual y que opera 35% por encima del pico pre-pandemia de 2018, un nuevo nivel "
        "máximo y no una mera recuperación. La dimensión que impulsa el movimiento es la "
        "tracción de demanda —total y extranjera, ambas en su aporte máximo— mientras la "
        "diversificación de mercados permanece como la restricción rezagada (Norteamérica "
        "origina el 62% de los turistas extranjeros). Para el comité, ello ubica al destino RD "
        "en una posición de fortaleza estructural con progreso concentrado en el volumen y "
        "margen de mejora futura en la diversificación del origen. Sin un panel regional "
        "comparativo, esta es una posición frente a la propia historia del destino y no un "
        "ordenamiento entre países."
    ),
    "recommendation": (
        "Para un inversionista o comité con exposición al sector turismo dominicano, el "
        "cuadro corresponde a una demanda firme y resiliente: las llegadas crecen >7% anual "
        "y superan el pico pre-pandemia, lo que respalda tesis de capacidad (planta "
        "hotelera, servicios). La palanca de mayor retorno sobre la **resiliencia** del "
        "destino —y no sobre el volumen, que ya crece— es la **diversificación de mercados "
        "emisores**: reducir la dependencia del 62% de Norteamérica mediante la captación de "
        "demanda europea y suramericana (la de más rápido crecimiento) protege los ingresos "
        "ante un shock en un solo mercado. Se recomienda priorizar tesis ancladas a la "
        "demanda probada y ponderar el riesgo de concentración de origen al dimensionar la "
        "exposición. Nota: esta lectura corresponde a la DEMANDA; la rentabilidad por plaza "
        "depende también de ocupación y tarifa (divisas), serie que el BCRD discontinuó en "
        "2018-2019 y actualmente no publica de forma limpia."
    ),
}


def tourism_manifest() -> SectorProductManifest:
    return SectorProductManifest(
        sector_key=SECTOR_KEY, display_name="SDQ Tourism & Hospitality", levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=("tourism_pulse",), narrative_templates=("tourism_outlook",),
                audience="mercado / abierto", cadence="periodic",
                watermark="Vista abierta · SDQMIP", price_band="abierto"),
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.named_entity,
                sections=("tourism_assessment", "positioning"),
                narrative_templates=("tourism_outlook", "sector_positioning"),
                audience="cliente / comité", cadence="recurring", price_band="suscripción"),
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=("tourism_assessment", "positioning", "recommendation", "limitations"),
                narrative_templates=("tourism_outlook", "sector_positioning"),
                audience="comité / contraparte", cadence="on_demand", price_band="on-demand"),
        })


def _latest_score(db: Session, period: Optional[str] = None) -> Optional[TourismScore]:
    try:
        with db.begin_nested():
            row = get_latest(db, period or None)
            # Producto ANUAL: el selector de período de la UI es trimestral (p.ej.
            # "2026-Q1") y nunca casa con el año del ITT → caer al último año disponible
            # en vez de quedar en blanco. Un período anual que SÍ existe se respeta.
            if row is None and period:
                row = get_latest(db, None)
            return row
    except Exception as e:  # noqa: BLE001
        logger.warning("ITT no disponible: %s", e)
        return None


def _index_dict(s: TourismScore) -> Dict[str, Any]:
    bd = s.breakdown or {}
    return {"itt_score": s.itt_score, "band": s.band, "coverage": s.coverage,
            "dimensions": bd.get("dimensions", {}), "total_demand": bd.get("total_demand", {}),
            "foreign_demand": bd.get("foreign_demand", {}), "recovery": bd.get("recovery", {}),
            "diversification": bd.get("diversification", {}), "levels": bd.get("levels", {})}


def _fmt(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.1f}"


def _trend_series(db: Optional[Session]):
    """``[(period, itt_score), …]`` ascendente para la línea de tendencia. Best-effort."""
    if db is None:
        return []
    try:
        rows = get_scores(db)
    except Exception:  # noqa: BLE001
        return []
    return [(r.period, r.itt_score) for r in reversed(rows) if r.itt_score is not None]


class TourismProduct:
    sector_key = SECTOR_KEY

    def __init__(self, db: Optional[Session] = None):
        self._db = db
        self._cache: Any = _UNSET

    def _require_db(self) -> Session:
        if self._db is None:
            raise RuntimeError("TourismProduct requiere una sesión de DB para esta operación.")
        return self._db

    def _latest(self) -> Optional[TourismScore]:
        if self._cache is _UNSET:
            self._cache = _latest_score(self._require_db())
        return self._cache

    def product_manifest(self) -> SectorProductManifest:
        return tourism_manifest()

    def data_signals(self) -> DataHealth:
        s = self._latest()
        if s is None:
            return DataHealth(coverage=0.0, freshness_days=None, cadence="annual",
                              sources=("ONE",), detail="Sin ITT persistido.")
        from datetime import date
        coverage = s.coverage if s.coverage is not None else 0.0
        freshness = None
        try:
            freshness = max(0, (date.today() - date(int(str(s.period)[:4]), 12, 31)).days)
        except (ValueError, TypeError):
            pass
        return DataHealth(coverage=coverage, freshness_days=freshness, cadence="annual",
                          sources=("ONE (datos.gob.do)",),
                          detail=f"ITT {_fmt(s.itt_score)} ({s.band}) en {s.period} · "
                                 f"{int(s.nonresident) if s.nonresident else '—'} no residentes")

    def has_engine(self) -> bool:
        return self._latest() is not None

    def available_periods(self) -> List[str]:
        return distinct_periods(self._require_db(), TourismScore.period)

    def validation_state(self) -> ValidationState:
        # Índice PRELIMINAR: 4 dimensiones sobre dato real ONE, pero SIN backtest de
        # outcomes → validación parcial honesta, no veredicto pleno.
        return ValidationState(approved=True, score=0.55,
                               notes="ITT preliminar (sin backtest de outcomes). Demanda "
                                     "total, demanda extranjera, recuperación y "
                                     "diversificación de mercados sobre dato real ONE "
                                     "(llegadas agregadas nacionales).")

    # ── Snapshot por nivel ──
    def snapshot(self, tier: ProductTier, period: str,
                 scope: Optional[str] = None) -> ProductSnapshot:
        s = _latest_score(self._require_db(), period or None)
        if s is None:
            entity = None if tier == ProductTier.pulse else DISPLAY
            return ProductSnapshot(tier=tier, period=period or "—",
                                   payload={"has_score": False}, entity_name=entity,
                                   entity_roster=())
        payload = {"has_score": True, "index": _index_dict(s)}
        if tier == ProductTier.pulse:
            return ProductSnapshot(tier=tier, period=s.period, payload=payload,
                                   entity_name=None, entity_roster=())
        return ProductSnapshot(tier=tier, period=s.period, payload=payload, entity_name=DISPLAY)

    # ── Muestra sintética (datos demo ilustrativos, sin DB) ──
    def sample_snapshot(self, tier: ProductTier) -> ProductSnapshot:
        index = {"itt_score": 93.01, "band": "Fuerte", "coverage": 1.0,
                 "dimensions": {
                     "total_demand": {"score": 100.0, "weight": 0.30,
                                      "provenance": "real", "contribution": 30.0},
                     "foreign_demand": {"score": 100.0, "weight": 0.25,
                                        "provenance": "real", "contribution": 25.0},
                     "recovery": {"score": 100.0, "weight": 0.25,
                                  "provenance": "real", "contribution": 25.0},
                     "diversification": {"score": 65.06, "weight": 0.20,
                                         "provenance": "real", "contribution": 13.01}},
                 "total_demand": {"latest": 8860709.0, "cagr": 7.35, "score": 100.0},
                 "foreign_demand": {"latest": 7341745.0, "cagr": 8.14, "score": 100.0},
                 "recovery": {"latest": 8860709.0, "peak": 6568888.0, "ratio": 134.9,
                              "peak_year": 2018, "score": 100.0},
                 "diversification": {"hhi": 4423.0, "top_region": "América del Norte",
                                     "top_share": 62.2, "score": 65.06},
                 "levels": {"nonresident": 8860709.0, "foreign": 7341745.0,
                            "top_region": "América del Norte", "top_share": 62.2, "hhi": 4423.0}}
        payload = {"has_score": True, "index": index}
        if tier == ProductTier.pulse:
            return ProductSnapshot(tier=tier, period="2025", payload=payload,
                                   entity_name=None, entity_roster=())
        return ProductSnapshot(tier=tier, period="2025", payload=payload, entity_name=DISPLAY)

    def sample_narratives(self, tier: ProductTier) -> Dict[str, str]:
        sections = self.product_manifest().require_level(tier).sections
        return {sec: (_LIMITATIONS if sec == "limitations" else _SAMPLE_NARRATIVES[sec])
                for sec in sections}

    # ── Narrativas (sin DB) ──
    async def narratives(self, tier: ProductTier, snapshot: ProductSnapshot,
                         lang: str = "es") -> Dict[str, str]:
        sections = self.product_manifest().require_level(tier).sections
        if not snapshot.payload.get("has_score"):
            return {sec: (_LIMITATIONS if sec == "limitations" else _NO_DATA)
                    for sec in sections}

        from shared.narrative.claude_engine import narrative_engine
        base_ctx = tourism_ai_context(snapshot.payload["index"], snapshot.period)
        audience = "inversionista"
        trend = _trend_series(self._db)  # trayectoria para la sección de posición (best-effort)
        templates = {"recommendation": "sector_decision", "positioning": "sector_positioning"}
        out: Dict[str, str] = {}
        for section in sections:
            if section == "limitations":
                out["limitations"] = _LIMITATIONS
                continue
            ctx = dict(base_ctx)
            if section == "recommendation":
                ctx["enfoque"] = ("Cierre ACCIONABLE: la palanca de mayor retorno sobre la "
                                  "tracción del destino turístico, dado el cuadro anterior.")
            elif section == "positioning" and trend:
                ctx["trayectoria"] = [{"periodo": p, "score": v} for p, v in trend]
            res = await narrative_engine.generate(
                context=ctx, template=templates.get(section, "tourism_outlook"),
                mode=section_mode(tier, section, sections),
                axis="tourism_intel", audience=audience)
            out[section] = res.text
        return out

    # ── Render (sin DB, renderer genérico) ──
    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None, fmt: str = "pdf") -> str:
        level = self.product_manifest().require_level(tier)
        title = {"pulse": "Pulse Turismo", "insight": "Insight Turismo",
                 "deep_dive": "Deep Dive Turismo"}.get(tier.value, "Turismo")
        display = ("Sector Turismo · RD" if tier == ProductTier.pulse else DISPLAY)
        tables: List = []
        charts: List = []
        index = (snapshot.payload or {}).get("index") or {}
        dims = index.get("dimensions") or {}
        if dims:
            labels = {"total_demand": "Demanda total", "foreign_demand": "Demanda extranjera",
                      "recovery": "Recuperación", "diversification": "Diversificación"}
            rows = [["Dimensión", "Score", "Peso"]] + [
                [labels.get(k, k), _fmt((d or {}).get("score")), _fmt((d or {}).get("weight"))]
                for k, d in dims.items()]
            tables.append(("Dimensiones del ITT", rows))
            items = [(labels.get(k, k), (d or {}).get("score")) for k, d in dims.items()]
            charts.append({"title": "Dimensiones del ITT (score 0-100)", "items": items})
        trend = _trend_series(None if sample else self._db)
        if len(trend) >= 2:
            charts.append({"kind": "line", "title": "Tendencia del ITT (por año)", "items": trend})
        sc = index.get("itt_score")
        headline = (f"ITT {_fmt(sc)} · {index.get('band')}" if sc is not None else None)
        return render_product_pdf(
            sector_key=SECTOR_KEY, display_name=display, title=title,
            period=snapshot.period, narratives=narratives,
            section_titles=_SECTION_TITLES, tables=tables, charts=charts, headline=headline,
            subtitle=None, watermark=level.watermark, sample=sample,
            output_dir=output_dir, fmt=fmt)


register_product(SECTOR_KEY, lambda db: TourismProduct(db))
