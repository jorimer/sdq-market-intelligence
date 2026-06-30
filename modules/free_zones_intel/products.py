"""Free Zones Intelligence como ``SectorProduct`` — producto dedicado del sector ZF.

Mono-módulo (patrón Energy/Trade): ``free_zones_intel`` tiene conector real (CNZFE, datos
abiertos) + índice IZF (atractividad del sector de zonas francas). Implementa el
``Protocol`` ``SectorProduct`` SIN tocar el framework de productos, reusando el motor de
narrativa y los getters PÚBLICOS del módulo (``service``/``ai_context``).

Naturaleza NACIONAL: el "entity" es el sector de zonas francas de RD; no hay firmas →
``entity_roster=()``. El Pulse es el pulso del sector; el nivel nombrado nombra al sector.

REEMPLAZA en el catálogo el corte transversal de ``sector_intel`` para ``free_zones``:
el producto dedicado (fundamentos reales CNZFE) es más fiel al sector que el slice del
IAI transversal. El IAI transversal interno (peer set de 17 sectores) NO se toca — solo
cambia el producto consumible del slot ``free_zones``. Se importa DESPUÉS de
``sector_intel.products`` en ``app/main`` para sobreescribir el registro.
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
from modules.free_zones_intel.ai_context import free_zones_ai_context
from modules.free_zones_intel.models.models import FreeZoneScore
from modules.free_zones_intel.service import get_latest, get_scores

logger = logging.getLogger("sdq.products.free_zones")

SECTOR_KEY = "free_zones"
DISPLAY = "Sector de Zonas Francas · RD"
_UNSET = object()

_SECTION_TITLES = {
    "free_zones_pulse": "Pulso del Sector de Zonas Francas",
    "free_zones_assessment": "Evaluación de Atractividad (IZF)",
    "recommendation": "Lectura para Decisión",
    "limitations": "Limitaciones",
}
_LIMITATIONS = (
    "Índice de Atractividad de Zonas Francas (IZF) sobre datos abiertos de la CNZFE "
    "(datos.gob.do): dinamismo exportador, atracción de inversión, generación de empleo y "
    "productividad (exportaciones por empresa), cada dimensión por su CAGR a 3 años vs un "
    "objetivo. Dato ANUAL AGREGADO NACIONAL del sector — sin desglose por sub-sector "
    "industrial (textil, tabaco, médica, calzado), que vive en el informe estadístico "
    "anual de la CNZFE. Índice PRELIMINAR (sin backtest de outcomes)."
)
_NO_DATA = (
    "No hay IZF persistido: el producto está cableado pero su cobertura es insuficiente "
    "para publicar. No se fabrican cifras."
)

# Narrativa CURADA tier-1 de la muestra (exemplar), coherente con el dato real 2025
# (IZF 49.2 «Vigilancia», ~858 empresas, ~200 mil empleos, US$8,549M export, US$8,170M
# inversión; CAGR export 3.0%, inversión 4.5%, empleo 1.3%, productividad −0.5%).
_SAMPLE_NARRATIVES = {
    "free_zones_pulse": (
        "El sector de zonas francas dominicano cierra el período con un **Índice de "
        "Atractividad de Zonas Francas de 49.2/100 —banda Vigilancia—**, un perfil de "
        "expansión en escala pero con dinamismo moderándose. La fortaleza es la "
        "**atracción de inversión**: la inversión acumulada crece a 4.5% anual y se acerca "
        "a los **US$8,170 millones**, señal de confianza de capital sostenida. Las "
        "**exportaciones** (~US$8,549 millones) avanzan a 3.0% anual y el **empleo** "
        "(~200 mil puestos) a 1.3% —positivos, pero por debajo de un ritmo de plena "
        "atractividad—. El lastre es la **productividad**: las exportaciones por empresa "
        "operando caen levemente (−0.5%), porque el número de empresas (~858) crece más "
        "rápido que el valor exportado. La lectura de mercado: el régimen sigue captando "
        "capital y empresas, pero el valor por firma no está escalando —la frontera está "
        "en subir la productividad y el valor agregado por operación, no solo el conteo."
    ),
    "free_zones_assessment": (
        "La atractividad del sector de zonas francas se evalúa en **49.2/100 (banda "
        "Vigilancia)**, sostenida por la inversión y limitada por la productividad. Los "
        "~858 establecimientos y ~200 mil empleos configuran un sector de escala "
        "relevante y en expansión; la inversión acumulada (US$8,170M, +4.5% anual) "
        "confirma el atractivo del régimen para capital exportador. El contrapunto es la "
        "eficiencia: con exportaciones (~US$8,549M) creciendo a 3.0% —por debajo de la "
        "expansión de empresas— la productividad por firma se estanca. Para un "
        "inversionista, la oportunidad está menos en sumar presencia y más en segmentos "
        "de mayor valor agregado (manufactura médica, dispositivos, servicios) que "
        "levanten el valor exportado por operación."
    ),
    "recommendation": (
        "Para un inversionista o comité con exposición al sector de zonas francas "
        "dominicano, la palanca de mayor retorno sobre la atractividad no está en sumar "
        "empresas —el conteo ya crece— sino en la **productividad y el valor agregado por "
        "operación**: migrar hacia segmentos de mayor valor (manufactura médica, "
        "electrónica, servicios) donde el valor exportado por firma es más alto. La "
        "inversión y el empleo confirman un régimen sano y en expansión; la frontera "
        "estructural es la calidad —no la cantidad— de la actividad. Recomendación: "
        "priorizar tesis de upgrade de valor agregado sobre expansión horizontal, y "
        "vigilar que el crecimiento de empresas se acompañe de crecimiento del valor "
        "exportado por firma."
    ),
}


def free_zones_manifest() -> SectorProductManifest:
    return SectorProductManifest(
        sector_key=SECTOR_KEY, display_name="SDQ Free Zones & Manufacturing", levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=("free_zones_pulse",), narrative_templates=("free_zones_outlook",),
                audience="mercado / abierto", cadence="periodic",
                watermark="Vista abierta · SDQMIP", price_band="abierto"),
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.named_entity,
                sections=("free_zones_assessment",), narrative_templates=("free_zones_outlook",),
                audience="cliente / comité", cadence="recurring", price_band="suscripción"),
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=("free_zones_assessment", "recommendation", "limitations"),
                narrative_templates=("free_zones_outlook",),
                audience="comité / contraparte", cadence="on_demand", price_band="on-demand"),
        })


def _latest_score(db: Session, period: Optional[str] = None) -> Optional[FreeZoneScore]:
    try:
        with db.begin_nested():
            row = get_latest(db, period or None)
            # Producto ANUAL: el selector de período de la UI es trimestral (p.ej.
            # "2026-Q1") y nunca casa con el año del IZF → caer al último año disponible
            # en vez de quedar en blanco. Un período anual que SÍ existe se respeta.
            if row is None and period:
                row = get_latest(db, None)
            return row
    except Exception as e:  # noqa: BLE001
        logger.warning("IZF no disponible: %s", e)
        return None


def _index_dict(s: FreeZoneScore) -> Dict[str, Any]:
    bd = s.breakdown or {}
    return {"fz_score": s.fz_score, "band": s.band, "coverage": s.coverage,
            "dimensions": bd.get("dimensions", {}), "exports": bd.get("exports", {}),
            "investment": bd.get("investment", {}), "employment": bd.get("employment", {}),
            "productivity": bd.get("productivity", {}), "levels": bd.get("levels", {})}


def _fmt(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.1f}"


def _trend_series(db: Optional[Session]):
    """``[(period, fz_score), …]`` ascendente para la línea de tendencia. Best-effort:
    sin DB (muestra) o ante cualquier fallo devuelve [] y el reporte va sin la línea."""
    if db is None:
        return []
    try:
        rows = get_scores(db)
    except Exception:  # noqa: BLE001
        return []
    return [(r.period, r.fz_score) for r in reversed(rows) if r.fz_score is not None]


class FreeZoneProduct:
    sector_key = SECTOR_KEY

    def __init__(self, db: Optional[Session] = None):
        self._db = db
        self._cache: Any = _UNSET

    def _require_db(self) -> Session:
        if self._db is None:
            raise RuntimeError("FreeZoneProduct requiere una sesión de DB para esta operación.")
        return self._db

    def _latest(self) -> Optional[FreeZoneScore]:
        if self._cache is _UNSET:
            self._cache = _latest_score(self._require_db())
        return self._cache

    def product_manifest(self) -> SectorProductManifest:
        return free_zones_manifest()

    def data_signals(self) -> DataHealth:
        s = self._latest()
        if s is None:
            return DataHealth(coverage=0.0, freshness_days=None, cadence="annual",
                              sources=("CNZFE",), detail="Sin IZF persistido.")
        from datetime import date
        coverage = s.coverage if s.coverage is not None else 0.0
        freshness = None
        try:
            freshness = max(0, (date.today() - date(int(str(s.period)[:4]), 12, 31)).days)
        except (ValueError, TypeError):
            pass
        return DataHealth(coverage=coverage, freshness_days=freshness, cadence="annual",
                          sources=("CNZFE (datos.gob.do)",),
                          detail=f"IZF {_fmt(s.fz_score)} ({s.band}) en {s.period} · "
                                 f"{int(s.companies) if s.companies else '—'} empresas")

    def has_engine(self) -> bool:
        return self._latest() is not None

    def available_periods(self) -> List[str]:
        return distinct_periods(self._require_db(), FreeZoneScore.period)

    def validation_state(self) -> ValidationState:
        # Índice PRELIMINAR: 4 dimensiones sobre dato real CNZFE, pero SIN backtest de
        # outcomes → validación parcial honesta, no veredicto pleno.
        return ValidationState(approved=True, score=0.55,
                               notes="IZF preliminar (sin backtest de outcomes). Dinamismo "
                                     "exportador, inversión, empleo y productividad sobre "
                                     "dato real CNZFE (agregado nacional).")

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
        index = {"fz_score": 49.2, "band": "Vigilancia", "coverage": 1.0,
                 "dimensions": {
                     "export_dynamism": {"score": 59.6, "weight": 0.30,
                                         "provenance": "real", "contribution": 17.88},
                     "investment_attraction": {"score": 89.8, "weight": 0.25,
                                               "provenance": "real", "contribution": 22.45},
                     "employment": {"score": 44.33, "weight": 0.20,
                                    "provenance": "real", "contribution": 8.87},
                     "productivity": {"score": 0.0, "weight": 0.25,
                                      "provenance": "real", "contribution": 0.0}},
                 "exports": {"latest": 8548.6, "cagr": 2.98, "score": 59.6},
                 "investment": {"latest": 8169.8, "cagr": 4.49, "score": 89.8},
                 "employment": {"latest": 200237.0, "cagr": 1.33, "score": 44.33},
                 "productivity": {"latest": 9.96, "cagr": -0.49, "score": 0.0},
                 "levels": {"companies": 858.0, "jobs": 200237.0, "exports_musd": 8548.6,
                            "investment_musd": 8169.8, "parks": 98.0}}
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
        base_ctx = free_zones_ai_context(snapshot.payload["index"], snapshot.period)
        audience = "inversionista"
        out: Dict[str, str] = {}
        for section in sections:
            if section == "limitations":
                out["limitations"] = _LIMITATIONS
                continue
            ctx = dict(base_ctx)
            if section == "recommendation":
                ctx["enfoque"] = ("Cierre ACCIONABLE: la palanca de mayor retorno sobre la "
                                  "atractividad del sector de zonas francas, dado el cuadro anterior.")
            res = await narrative_engine.generate(
                context=ctx,
                template=("sector_decision" if section == "recommendation"
                          else "free_zones_outlook"),
                mode=section_mode(tier, section, sections),
                axis="free_zones_intel", audience=audience)
            out[section] = res.text
        return out

    # ── Render (sin DB, renderer genérico) ──
    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None, fmt: str = "pdf") -> str:
        level = self.product_manifest().require_level(tier)
        title = {"pulse": "Pulse Zonas Francas", "insight": "Insight Zonas Francas",
                 "deep_dive": "Deep Dive Zonas Francas"}.get(tier.value, "Zonas Francas")
        display = ("Sector de Zonas Francas · RD" if tier == ProductTier.pulse else DISPLAY)
        tables: List = []
        charts: List = []
        index = (snapshot.payload or {}).get("index") or {}
        dims = index.get("dimensions") or {}
        if dims:
            labels = {"export_dynamism": "Dinamismo exportador",
                      "investment_attraction": "Atracción de inversión",
                      "employment": "Empleo", "productivity": "Productividad"}
            rows = [["Dimensión", "Score", "Peso"]] + [
                [labels.get(k, k), _fmt((d or {}).get("score")), _fmt((d or {}).get("weight"))]
                for k, d in dims.items()]
            tables.append(("Dimensiones del IZF", rows))
            items = [(labels.get(k, k), (d or {}).get("score")) for k, d in dims.items()]
            charts.append({"title": "Dimensiones del IZF (score 0-100)", "items": items})
        trend = _trend_series(None if sample else self._db)
        if len(trend) >= 2:
            charts.append({"kind": "line", "title": "Tendencia del IZF (por año)", "items": trend})
        sc = index.get("fz_score")
        headline = (f"IZF {_fmt(sc)} · {index.get('band')}" if sc is not None else None)
        return render_product_pdf(
            sector_key=SECTOR_KEY, display_name=display, title=title,
            period=snapshot.period, narratives=narratives,
            section_titles=_SECTION_TITLES, tables=tables, charts=charts, headline=headline,
            subtitle=None, watermark=level.watermark, sample=sample,
            output_dir=output_dir, fmt=fmt)


register_product(SECTOR_KEY, lambda db: FreeZoneProduct(db))
