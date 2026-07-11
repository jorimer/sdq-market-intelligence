"""Energy Intelligence como ``SectorProduct`` — sector #6.

Mono-módulo (patrón Trade/ESG): ``energy_intel`` tiene conector real (SIE, datos
abiertos) + índice IRSE (resiliencia del sector eléctrico). Implementa el
``Protocol`` ``SectorProduct`` SIN tocar el framework de productos, reusando el
motor de narrativa y los getters PÚBLICOS del propio módulo (``service``/``ai_context``).

Naturaleza NACIONAL: el "entity" es el sector eléctrico de RD; no hay firmas →
``entity_roster=()`` (el sensor de anonimización pasa trivialmente). El Pulse es el
pulso nacional; el nivel nombrado nombra al sector.

Cobertura HONESTA: el índice cubre 2 de 3 dimensiones con dato real (capacidad +
servicio); la TRANSICIÓN energética es brecha declarada (dato confiable de
generación renovable está en OC-SENI, pendiente) → G1 parcial. NUNCA inventar data.

Eje doctrinal ÚNICO: ``energy_intel`` + thin ``energy_outlook`` → numeric_guard.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
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
from modules.energy_intel.ai_context import energy_ai_context
from modules.energy_intel.models.models import EnergyScore
from modules.energy_intel.service import get_latest, get_scores

logger = logging.getLogger("sdq.products.energy")

SECTOR_KEY = "energy"
DISPLAY = "Sector Eléctrico Nacional · RD"
_UNSET = object()

_SECTION_TITLES = {
    "energy_pulse": "Pulso del Sector Eléctrico",
    "energy_assessment": "Evaluación de Resiliencia Eléctrica (IRSE)",
    "positioning": "Posición y Trayectoria",
    "recommendation": "Lectura para Decisión",
    "limitations": "Limitaciones",
}
_LIMITATIONS = (
    "El Índice de Resiliencia del Sector Eléctrico (IRSE) se construye sobre datos abiertos: "
    "adecuación de capacidad (parque instalado del SENI, SIE), calidad de servicio "
    "(reclamaciones acumuladas, SIE) y transición energética (penetración renovable de la "
    "matriz de generación, ONE), las tres dimensiones con dato real. La penetración "
    "renovable se mide sobre la meta nacional de la Ley 57-07 (25 %); el consumo de "
    "combustible (CKAN) se mantiene excluido por el quiebre de unidades de 2018, para no "
    "introducir una precisión que el dato no respalda. Índice preliminar, aún sin validación "
    "retrospectiva."
)
_NO_DATA = (
    "No hay IRSE persistido: el producto está cableado pero su cobertura (G1) es "
    "insuficiente para publicar. No se fabrican cifras."
)

# Narrativa CURADA tier-1 de la muestra (exemplar). Coherente con los datos demo
# (IRSE 63.08 «Adecuado», ~7,054 MW, CAGR 7.9%, capacidad score 100, servicio backlog
# 7.8 meses score 20, transición = brecha declarada).
_SAMPLE_NARRATIVES = {
    "energy_pulse": (
        "El sistema eléctrico dominicano cierra el período con un **Índice de Resiliencia "
        "del Sector Eléctrico de 63.08/100 —banda Adecuado—**, perfil que combina una "
        "fortaleza marcada con una debilidad de igual magnitud. La dimensión más sólida es "
        "la **adecuación de capacidad**: con cerca de **7,054 MW instalados** "
        "y un crecimiento anual de 7.9%, la oferta de generación supera holgadamente la "
        "demanda y se expande a buen ritmo (score 100 en esta dimensión). La principal "
        "restricción es la **calidad de servicio**: un backlog de reclamaciones de 7.8 meses "
        "(score 20) evidencia cuellos de botella en distribución y atención que la capacidad "
        "instalada no resuelve por sí sola. La transición energética se registra como "
        "**brecha declarada** —el dato de generación renovable por tecnología no está "
        "disponible con la granularidad necesaria y no se estima—. La lectura de mercado es "
        "que la República Dominicana tiene resuelta su suficiencia de generación, mientras "
        "su frontera de resiliencia se ubica en la confiabilidad de la entrega y en la "
        "descarbonización de la matriz."
    ),
    "energy_assessment": (
        "La resiliencia del sector eléctrico dominicano se evalúa en **63.08/100 (banda "
        "Adecuado)**, sostenida por una holgura de capacidad notable y limitada por la "
        "calidad del servicio. Los ~7,054 MW instalados, creciendo a 7.9% anual, "
        "configuran un sistema con margen de reserva amplio, un activo en una economía en "
        "expansión que demanda energía creciente. El contrapunto es operativo: un backlog "
        "de reclamaciones de 7.8 meses indica que la distribución y los procesos de "
        "atención no acompañan a la generación, lo que se traduce en pérdidas, "
        "interrupciones y un costo implícito para la actividad productiva. La transición "
        "energética constituye la dimensión no medida, una brecha de información y no un "
        "valor nulo: la descarbonización de la matriz es la variable estructural pendiente. "
        "Para un inversionista, el sector presenta oportunidad tanto en generación (incluida "
        "renovable) como, de manera prioritaria, en la modernización de la distribución."
    ),
    "positioning": (
        "**El IRSE se ubica en banda Adecuado con trayectoria ascendente, impulsada por la "
        "capacidad y no por el servicio.** La trayectoria aporta una señal que el nivel por "
        "sí solo no transmite: el índice se incrementó de forma sostenida en los últimos "
        "períodos, traccionado por la expansión del parque "
        "instalado (CAGR ~7.9%), mientras la calidad de servicio se mantiene estancada en la "
        "parte baja de la escala. En contexto, ello ubica a la República Dominicana en una "
        "posición de **fortaleza estructural con progreso asimétrico**: la dimensión que más "
        "incide en la posición es la adecuación de capacidad —que ya alcanzó su aporte "
        "máximo— mientras la distribución permanece como principal restricción. Para el "
        "inversionista, la lectura de trayectoria es tan relevante como la de nivel: el "
        "margen de mejora futura no se encuentra donde se concentró el progreso reciente. "
        "(Sin panel regional, esta es una posición frente a la propia historia del sector y "
        "no un ordenamiento entre países.)"
    ),
    "recommendation": (
        "Para un inversionista o comité con exposición al sector eléctrico dominicano, la "
        "palanca de mayor retorno sobre la resiliencia no se encuentra en sumar capacidad "
        "—que ya es holgada— sino en la **calidad de servicio**: la modernización de la "
        "distribución y la reducción del backlog de reclamaciones es donde convergen el "
        "score más bajo (20) y el mayor impacto sobre la actividad productiva. La segunda "
        "frontera, de carácter estructural, es la **transición energética**: avanzar en "
        "generación renovable y en la medición de la matriz mejora la resiliencia ambiental "
        "y, a la vez, reduce la exposición a precios de combustibles importados. La "
        "recomendación es priorizar inversión y supervisión en distribución y confiabilidad "
        "por encima de nueva capacidad térmica, y tratar la renovable como tesis de mediano "
        "plazo con doble retorno: resiliencia operativa y descarbonización."
    ),
}


def energy_manifest() -> SectorProductManifest:
    return SectorProductManifest(
        sector_key=SECTOR_KEY, display_name="SDQ Energy Intelligence", levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=("energy_pulse",), narrative_templates=("energy_outlook",),
                audience="mercado / abierto", cadence="periodic",
                watermark="Vista abierta · SDQMIP", price_band="abierto"),
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.named_entity,
                sections=("energy_assessment", "positioning"),
                narrative_templates=("energy_outlook", "sector_positioning"),
                audience="cliente / comité", cadence="recurring", price_band="suscripción"),
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=("energy_assessment", "positioning", "recommendation", "limitations"),
                narrative_templates=("energy_outlook", "sector_positioning"),
                audience="comité / contraparte", cadence="on_demand", price_band="on-demand"),
        })


def _latest_score(db: Session, period: Optional[str] = None) -> Optional[EnergyScore]:
    """Último IRSE (o el del período) en SAVEPOINT: una lectura que falla no tumba el
    recompute compartido (que itera todos los sectores en una sesión)."""
    try:
        with db.begin_nested():
            return get_latest(db, period or None)
    except Exception as e:  # noqa: BLE001
        logger.warning("IRSE no disponible: %s", e)
        return None


def _index_dict(s: EnergyScore) -> Dict[str, Any]:
    bd = s.breakdown or {}
    return {"energy_score": s.energy_score, "band": s.band, "coverage": s.coverage,
            "dimensions": bd.get("dimensions", {}), "capacity": bd.get("capacity", {}),
            "service": bd.get("service", {}), "transition": bd.get("transition", {})}


def _fmt(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.1f}"


def _trend_series(db: Optional[Session]):
    """``[(period, energy_score), …]`` ascendente para la línea de tendencia. Best-effort."""
    if db is None:
        return []
    try:
        rows = get_scores(db)
    except Exception:  # noqa: BLE001
        return []
    return [(r.period, r.energy_score) for r in reversed(rows) if r.energy_score is not None]


class EnergyProduct:
    sector_key = SECTOR_KEY

    def __init__(self, db: Optional[Session] = None):
        self._db = db
        self._cache: Any = _UNSET

    def _require_db(self) -> Session:
        if self._db is None:
            raise RuntimeError("EnergyProduct requiere una sesión de DB para esta operación.")
        return self._db

    def _latest(self) -> Optional[EnergyScore]:
        if self._cache is _UNSET:
            self._cache = _latest_score(self._require_db())
        return self._cache

    def product_manifest(self) -> SectorProductManifest:
        return energy_manifest()

    # ── Señales de readiness ──
    def data_signals(self) -> DataHealth:
        s = self._latest()
        if s is None:
            return DataHealth(coverage=0.0, freshness_days=None, cadence="annual",
                              sources=("SIE",), detail="Sin IRSE persistido.")
        # Cobertura honesta: la del índice. Cadencia anual (capacidad SIE).
        coverage = s.coverage if s.coverage is not None else 0.0
        freshness = None
        try:
            # Dato anual: fin de año del período. Si el año aún no cierra (período actual),
            # la frescura es 0 (es el dato más reciente disponible), no negativa.
            freshness = max(0, (date.today() - date(int(str(s.period)[:4]), 12, 31)).days)
        except (ValueError, TypeError):
            pass
        tr = (s.breakdown or {}).get("transition") or {}
        transition_txt = (
            f"transición = renovable {_fmt(tr.get('renewable_share'))}%"
            if s.transition_score is not None else "transición = brecha")
        sources = ["SIE (capacidad)", "SIE (reclamaciones)"]
        if s.transition_score is not None:
            sources.append("ONE (generación por tecnología)")
        return DataHealth(coverage=coverage, freshness_days=freshness, cadence="annual",
                          sources=tuple(sources),
                          detail=f"IRSE {_fmt(s.energy_score)} ({s.band}) en {s.period} · "
                                 f"{transition_txt}")

    def has_engine(self) -> bool:
        return self._latest() is not None

    def available_periods(self) -> List[str]:
        return distinct_periods(self._require_db(), EnergyScore.period)

    def validation_state(self) -> ValidationState:
        # Índice PRELIMINAR: las 3 dimensiones sobre dato real, pero SIN backtest de
        # outcomes (Gate E) → validación parcial honesta, no veredicto pleno.
        s = self._latest()
        full = s is not None and s.transition_score is not None
        score = 0.55 if full else 0.45
        notes = ("IRSE preliminar (sin validación retrospectiva de resultados). Las 3 dimensiones "
                 "—capacidad, servicio (SIE) y transición renovable (ONE)— sobre dato real."
                 if full else
                 "IRSE preliminar (sin validación retrospectiva); transición declarada como brecha. "
                 "Capacidad y servicio sobre dato real SIE.")
        return ValidationState(approved=True, score=score, notes=notes)

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
        index = {"energy_score": 63.08, "band": "Adecuado", "coverage": 0.65,
                 "dimensions": {
                     "capacity_adequacy": {"score": 100.0, "weight": 0.35,
                                           "provenance": "real", "contribution": 35.0},
                     "service_quality": {"score": 20.0, "weight": 0.30,
                                         "provenance": "real", "contribution": 6.0},
                     "energy_transition": {"score": None, "weight": 0.35,
                                           "provenance": "brecha", "contribution": None}},
                 "capacity": {"capacity_mw": 7054.05, "cagr_3y": 7.9, "score": 100.0},
                 "service": {"backlog_months": 7.8, "score": 20.0}}
        payload = {"has_score": True, "index": index}
        if tier == ProductTier.pulse:
            return ProductSnapshot(tier=tier, period="2026", payload=payload,
                                   entity_name=None, entity_roster=())
        return ProductSnapshot(tier=tier, period="2026", payload=payload, entity_name=DISPLAY)

    def sample_narratives(self, tier: ProductTier) -> Dict[str, str]:
        """Narrativa CURADA tier-1 de la muestra (exemplar). NO usa el motor IA."""
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
        base_ctx = energy_ai_context(snapshot.payload["index"], snapshot.period)
        audience = "inversionista"
        trend = _trend_series(self._db)  # trayectoria para la sección de posición (best-effort)
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
                ctx["enfoque"] = ("Cierre ACCIONABLE: entre adecuación de capacidad y calidad de "
                                  "servicio, la palanca con mayor retorno sobre la resiliencia "
                                  "eléctrica, dado el cuadro anterior.")
            elif section == "positioning" and trend:
                ctx["trayectoria"] = [{"periodo": p, "score": v} for p, v in trend]
            pending.append((section, dict(
                context=ctx, template=templates.get(section, "energy_outlook"),
                mode=section_mode(tier, section, sections),
                axis="energy_intel", audience=audience)))

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
        title = {"pulse": "Pulse Energía", "insight": "Insight Energía",
                 "deep_dive": "Deep Dive Energía"}.get(tier.value, "Energía")
        display = ("Sistema Eléctrico Nacional · RD" if tier == ProductTier.pulse else DISPLAY)
        tables: List = []
        charts: List = []
        index = (snapshot.payload or {}).get("index") or {}
        dims = index.get("dimensions") or {}
        if dims:
            labels = {"capacity_adequacy": "Adecuación de capacidad",
                      "service_quality": "Calidad de servicio",
                      "energy_transition": "Transición energética"}
            rows = [["Dimensión", "Score", "Peso"]] + [
                [labels.get(k, k), _fmt((d or {}).get("score")), _fmt((d or {}).get("weight"))]
                for k, d in dims.items()]
            tables.append(("Dimensiones del IRSE", rows))
            items = [(labels.get(k, k), (d or {}).get("score")) for k, d in dims.items()]
            charts.append({"title": "Dimensiones del IRSE (score 0-100)", "items": items})
        trend = _trend_series(None if sample else self._db)
        if len(trend) >= 2:
            charts.append({"kind": "line", "title": "Tendencia del IRSE (por año)", "items": trend})
        sc = index.get("energy_score")
        headline = (f"IRSE {_fmt(sc)} · {index.get('band')}" if sc is not None else None)
        return render_product_pdf(
            sector_key=SECTOR_KEY, display_name=display, title=title,
            period=snapshot.period, narratives=narratives,
            section_titles=_SECTION_TITLES, tables=tables, charts=charts, headline=headline,
            subtitle=None, watermark=level.watermark, sample=sample,
            output_dir=output_dir, fmt=fmt)


register_product(SECTOR_KEY, lambda db: EnergyProduct(db))
