"""Construction Intelligence como ``SectorProduct`` — producto dedicado del sector construcción.

Mono-módulo (patrón Free Zones/Tourism): ``construction_intel`` tiene conector real (MIVHED
licencias + BCRD PIB construcción, datos abiertos) + índice ICC (coyuntura del sector
construcción). Implementa el ``Protocol`` ``SectorProduct`` SIN tocar el framework de
productos, reusando el motor de narrativa y los getters PÚBLICOS del módulo
(``service``/``ai_context``).

Naturaleza NACIONAL: el "entity" es el sector construcción de RD; no hay firmas →
``entity_roster=()``. El Pulse es el pulso del sector; el nivel nombrado nombra al sector.

REEMPLAZA en el catálogo el corte transversal de ``sector_intel`` para ``construction``: el
producto dedicado (permisos líder MIVHED + producción BCRD) es más fiel al sector que el
slice del IAI transversal. El IAI transversal interno (peer set de 17 sectores) NO se toca
— construction sigue en el peer set vía ``bcrd_sectors``; solo cambia el producto consumible
del slot ``construction``. Se importa DESPUÉS de ``sector_intel.products`` en ``app/main``
para sobreescribir el registro.
"""
from __future__ import annotations

import asyncio
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
from modules.construction_intel.ai_context import construction_ai_context
from modules.construction_intel.models.models import ConstructionScore
from modules.construction_intel.service import get_latest

logger = logging.getLogger("sdq.products.construction")

SECTOR_KEY = "construction"
DISPLAY = "Sector Construcción · RD"
_UNSET = object()

_SECTION_TITLES = {
    "construction_pulse": "Pulso del Sector Construcción",
    "construction_assessment": "Evaluación de Coyuntura (ICC)",
    "positioning": "Posición y Trayectoria",
    "recommendation": "Lectura para Decisión",
    "limitations": "Limitaciones",
}
_LIMITATIONS = (
    "El Índice de Construcción (ICC) se construye sobre dos fuentes abiertas y "
    "complementarias: las licencias de construcción del MIVHED (datos.gob.do), un indicador "
    "líder —el permiso precede a la obra—, y el crecimiento real del PIB de construcción del "
    "BCRD (producción efectiva). Cuatro dimensiones: producción (crecimiento real a 3 años), "
    "flujo de permisos (CAGR de m² a 3 años), diversificación tipológica y amplitud "
    "geográfica (HHI). El dato es anual y agregado nacional: los permisos del MIVHED "
    "comienzan en 2022 (historia corta para el CAGR del flujo) y la inversión licenciada es "
    "nominal (RD$), no ejecutada. Índice preliminar, aún sin validación retrospectiva de "
    "resultados."
)
_NO_DATA = (
    "No hay ICC persistido: el producto está cableado pero su cobertura es insuficiente "
    "para publicar. No se fabrican cifras."
)

# Narrativa CURADA tier-1 de la muestra (exemplar), coherente con el dato real 2025
# (ICC 26.5 «Crítico»: producción 3y +0.39% y flujo de permisos −7.5% deprimen el
# índice pese a una diversificación tipológica/geográfica más sana; 951 licencias, 4.47M
# m², ~RD$271 mil millones licenciados; apartamentos 59.6%, Santo Domingo 22.8%).
_SAMPLE_NARRATIVES = {
    "construction_pulse": (
        "El sector construcción dominicano cierra el período con un **Índice de "
        "Construcción de 26.5/100 —banda Crítico—**, lectura consistente con una coyuntura "
        "en enfriamiento tras el auge post-pandemia. El resultado lo determinan las dos "
        "dimensiones cíclicas: la **producción efectiva** (PIB real de construcción) "
        "promedia **+0.39% anual** en los últimos tres años y cerró 2025 en **−1.8%**, "
        "mientras el **flujo de permisos** se contrae de forma marcada —los metros² "
        "licenciados caen a un **−7.5% anual** (CAGR 3 años), de 5.7M a 4.5M de m²—. El "
        "componente estructural resulta más sólido: la actividad se mantiene "
        "**razonablemente diversificada** por tipología (apartamentos lideran con 59.6% de "
        "los permisos) y **distribuida geográficamente** (Santo Domingo concentra solo "
        "22.8%). En términos de mercado, el sector de mayor peso en la economía (13.5% del "
        "VAB) atraviesa una corrección —menor obra nueva en cartera— y la señal líder de los "
        "permisos anticipa que la debilidad de producción aún no toca fondo."
    ),
    "construction_assessment": (
        "La coyuntura de la construcción se evalúa en **26.5/100 (banda Crítico)**, "
        "deprimida por sus dos motores cíclicos y sostenida principalmente por la "
        "diversificación. La **producción** real del sector se estancó (promedio 3 años "
        "+0.4%, último año −1.8%), y el **flujo de permisos** —el mejor indicador adelantado "
        "disponible— se mantiene en terreno negativo: con 951 licencias y 4.5M de m² en "
        "2025, los permisos registran una contracción aproximada de 7.5% anual. La "
        "**inversión licenciada** se ubica en torno a los RD$271 mil millones (nominal). "
        "Como contrapeso, la base de actividad no depende de un solo segmento ni región: la "
        "diversificación tipológica (apartamentos 59.6%) y la amplitud geográfica (Santo "
        "Domingo 22.8%) obtienen puntajes elevados. Desde la óptica del inversionista, el "
        "cuadro corresponde a un **sector en corrección**: existe oportunidad selectiva "
        "donde la demanda estructural persiste, pero con el ciclo de permisos aún a la baja."
    ),
    "positioning": (
        "**El ICC se ubica en banda Crítico y su posición la define el contraste entre dos "
        "dimensiones cíclicas débiles y un componente estructural sano.** Ordenadas por "
        "aporte, las dimensiones que deprimen el índice son la producción (PIB real, "
        "promedio 3 años +0.4% y último año −1.8%) y, sobre todo, el flujo de permisos "
        "(metros² licenciados a −7.5% anual), ambas en terreno cíclico negativo. En el polo "
        "opuesto, la diversificación tipológica (apartamentos 59.6%) y la amplitud "
        "geográfica (Santo Domingo 22.8%) obtienen puntajes elevados y sostienen la base de "
        "actividad. La dimensión que define la posición es el flujo de permisos: como "
        "indicador adelantado, su contracción explica por qué el índice no toca fondo pese a "
        "la solidez estructural. Cabe una nota de honestidad metodológica: los permisos "
        "MIVHED arrancan en 2022, por lo que la serie histórica es corta y no permite leer "
        "una trayectoria de varios ciclos, solo la posición relativa de las dimensiones en "
        "el período medido."
    ),
    "recommendation": (
        "Para un inversionista, desarrollador o decisor público con exposición a la "
        "construcción dominicana, la señal dominante es un **ciclo en contracción**: tanto "
        "la producción (PIB real) como el flujo líder de permisos apuntan a la baja, por "
        "lo que el momento de nueva exposición exige cautela y selectividad. La palanca de "
        "mayor valor no reside en sumar capacidad horizontal sino en la **lectura del "
        "indicador adelantado de permisos por tipología y provincia**: la diversificación "
        "sólida indica que existen segmentos y plazas donde la demanda estructural persiste "
        "(vivienda, plazas fuera del Gran Santo Domingo). Se recomienda condicionar las "
        "tesis a una reactivación del flujo de permisos —el mejor indicador adelantado— "
        "antes de asumir un giro del ciclo, y priorizar nichos diversificados sobre "
        "posiciones concentradas."
    ),
}


def construction_manifest() -> SectorProductManifest:
    return SectorProductManifest(
        sector_key=SECTOR_KEY, display_name="SDQ Construction Intelligence", levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=("construction_pulse",),
                narrative_templates=("construction_outlook",),
                audience="mercado / abierto", cadence="periodic",
                watermark="Vista abierta · SDQMIP", price_band="abierto"),
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.named_entity,
                sections=("construction_assessment", "positioning"),
                narrative_templates=("construction_outlook", "sector_positioning"),
                audience="cliente / comité", cadence="recurring", price_band="suscripción"),
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=("construction_assessment", "positioning", "recommendation", "limitations"),
                narrative_templates=("construction_outlook", "sector_positioning"),
                audience="comité / contraparte", cadence="on_demand", price_band="on-demand"),
        })


def _latest_score(db: Session, period: Optional[str] = None) -> Optional[ConstructionScore]:
    try:
        with db.begin_nested():
            row = get_latest(db, period or None)
            # Producto ANUAL: el selector de período de la UI puede ser trimestral (p.ej.
            # "2026-Q1") y nunca casa con el año del ICC → caer al último año disponible en
            # vez de quedar en blanco. Un período anual que SÍ existe se respeta.
            if row is None and period:
                row = get_latest(db, None)
            return row
    except Exception as e:  # noqa: BLE001
        logger.warning("ICC no disponible: %s", e)
        return None


def _index_dict(s: ConstructionScore) -> Dict[str, Any]:
    bd = s.breakdown or {}
    return {"icc_score": s.icc_score, "band": s.band, "coverage": s.coverage,
            "dimensions": bd.get("dimensions", {}), "production": bd.get("production", {}),
            "pipeline": bd.get("pipeline", {}), "typology": bd.get("typology", {}),
            "geography": bd.get("geography", {}), "levels": bd.get("levels", {})}


def _fmt(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.1f}"


class ConstructionProduct:
    sector_key = SECTOR_KEY

    def __init__(self, db: Optional[Session] = None):
        self._db = db
        self._cache: Any = _UNSET

    def _require_db(self) -> Session:
        if self._db is None:
            raise RuntimeError("ConstructionProduct requiere una sesión de DB para esta operación.")
        return self._db

    def _latest(self) -> Optional[ConstructionScore]:
        if self._cache is _UNSET:
            self._cache = _latest_score(self._require_db())
        return self._cache

    def product_manifest(self) -> SectorProductManifest:
        return construction_manifest()

    def data_signals(self) -> DataHealth:
        s = self._latest()
        if s is None:
            return DataHealth(coverage=0.0, freshness_days=None, cadence="annual",
                              sources=("MIVHED", "BCRD"), detail="Sin ICC persistido.")
        from datetime import date
        coverage = s.coverage if s.coverage is not None else 0.0
        freshness = None
        try:
            freshness = max(0, (date.today() - date(int(str(s.period)[:4]), 12, 31)).days)
        except (ValueError, TypeError):
            pass
        return DataHealth(coverage=coverage, freshness_days=freshness, cadence="annual",
                          sources=("MIVHED (datos.gob.do)", "BCRD"),
                          detail=f"ICC {_fmt(s.icc_score)} ({s.band}) en {s.period} · "
                                 f"{int(s.permits) if s.permits else '—'} licencias")

    def has_engine(self) -> bool:
        return self._latest() is not None

    def available_periods(self) -> List[str]:
        return distinct_periods(self._require_db(), ConstructionScore.period)

    def validation_state(self) -> ValidationState:
        # Índice PRELIMINAR: 4 dimensiones sobre dato real MIVHED+BCRD, pero SIN backtest de
        # outcomes y con historia corta de permisos (2022+) → validación parcial honesta.
        return ValidationState(approved=True, score=0.55,
                               notes="ICC preliminar (sin validación retrospectiva de resultados; permisos "
                                     "MIVHED desde 2022). Producción (PIB construcción BCRD), "
                                     "flujo de permisos, diversificación tipológica y "
                                     "amplitud geográfica sobre dato real.")

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

    # ── Muestra sintética (datos demo ilustrativos, sin DB; fiel al dato real 2025) ──
    def sample_snapshot(self, tier: ProductTier) -> ProductSnapshot:
        index = {"icc_score": 26.52, "band": "Crítico", "coverage": 1.0,
                 "dimensions": {
                     "production": {"score": 9.75, "weight": 0.35,
                                    "provenance": "real", "contribution": 3.41},
                     "pipeline": {"score": 0.0, "weight": 0.35,
                                  "provenance": "real", "contribution": 0.0},
                     "typology_diversification": {"score": 65.31, "weight": 0.15,
                                                  "provenance": "real", "contribution": 9.8},
                     "geographic_breadth": {"score": 88.74, "weight": 0.15,
                                            "provenance": "real", "contribution": 13.31}},
                 "production": {"latest": -1.8, "avg_growth": 0.39, "score": 9.75},
                 "pipeline": {"latest": 4473895.0, "cagr": -7.52, "score": 0.0},
                 "typology": {"hhi": 3971.1, "top": "APARTAMENTOS", "top_share": 59.6,
                              "score": 65.31},
                 "geography": {"hhi": 1443.1, "top": "SANTO DOMINGO", "top_share": 22.8,
                               "score": 88.74},
                 "levels": {"permits": 951, "sqm": 4473895.0,
                            "investment_dop": 271302161786.0, "prod_growth_latest": -1.8,
                            "prod_growth_3y": 0.39, "top_typology": "APARTAMENTOS",
                            "top_typology_share": 59.6, "top_province": "SANTO DOMINGO",
                            "top_province_share": 22.8}}
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
        base_ctx = construction_ai_context(snapshot.payload["index"], snapshot.period)
        audience = "inversionista"
        templates = {"recommendation": "sector_decision", "positioning": "sector_positioning"}
        out: Dict[str, str] = {}
        # Secciones con cifras → una llamada IA c/u, generadas en PARALELO (asyncio.gather):
        # antes era secuencial (~15s × N secciones). El cliente Anthropic ya libera el event
        # loop (asyncio.to_thread en claude_engine); aquí solo falta lanzar las llamadas juntas.
        pending: List = []   # (section, kwargs de generate)
        for section in sections:
            if section == "limitations":
                out["limitations"] = _LIMITATIONS
                continue
            ctx = dict(base_ctx)
            if section == "recommendation":
                ctx["enfoque"] = ("Cierre ACCIONABLE: la palanca de mayor retorno sobre la "
                                  "coyuntura del sector construcción, dado el cuadro anterior.")
            pending.append((section, dict(
                context=ctx, template=templates.get(section, "construction_outlook"),
                mode=section_mode(tier, section, sections),
                axis="construction_intel", audience=audience)))

        async def _gen(section: str, kwargs: Dict) -> tuple:
            res = await narrative_engine.generate(**kwargs)
            return section, res.text

        for section, text in await asyncio.gather(*(_gen(s, k) for s, k in pending)):
            out[section] = text
        return out

    # ── Render (sin DB, renderer genérico) ──
    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None, fmt: str = "pdf") -> str:
        level = self.product_manifest().require_level(tier)
        title = {"pulse": "Pulse Construcción", "insight": "Insight Construcción",
                 "deep_dive": "Deep Dive Construcción"}.get(tier.value, "Construcción")
        display = ("Sector Construcción · RD" if tier == ProductTier.pulse else DISPLAY)
        tables: List = []
        charts: List = []
        index = (snapshot.payload or {}).get("index") or {}
        dims = index.get("dimensions") or {}
        if dims:
            labels = {"production": "Producción (PIB)", "pipeline": "Flujo de permisos",
                      "typology_diversification": "Divers. tipológica",
                      "geographic_breadth": "Amplitud geográfica"}
            rows = [["Dimensión", "Score", "Peso"]] + [
                [labels.get(k, k), _fmt((d or {}).get("score")), _fmt((d or {}).get("weight"))]
                for k, d in dims.items()]
            tables.append(("Dimensiones del ICC", rows))
            items = [(labels.get(k, k), (d or {}).get("score")) for k, d in dims.items()]
            charts.append({"title": "Dimensiones del ICC (score 0-100)", "items": items})
        sc = index.get("icc_score")
        headline = (f"ICC {_fmt(sc)} · {index.get('band')}" if sc is not None else None)
        return render_product_pdf(
            sector_key=SECTOR_KEY, display_name=display, title=title,
            period=snapshot.period, narratives=narratives,
            section_titles=_SECTION_TITLES, tables=tables, charts=charts, headline=headline,
            subtitle=None, watermark=level.watermark, sample=sample,
            output_dir=output_dir, fmt=fmt)


register_product(SECTOR_KEY, lambda db: ConstructionProduct(db))
