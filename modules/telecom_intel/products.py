"""Telecom Intelligence como ``SectorProduct`` — sector #7.

Mono-módulo (patrón Energy): ``telecom_intel`` tiene conector real (INDOTEL, boletín
trimestral XLSX) + índice IDT (desarrollo telecom). Implementa el ``Protocol``
``SectorProduct`` SIN tocar el framework de productos, reusando el motor de narrativa
y los getters PÚBLICOS del propio módulo (``service``/``ai_context``).

Naturaleza NACIONAL: el "entity" es el sector telecom de RD; no hay firmas →
``entity_roster=()``. El Pulse es el pulso nacional; el nivel nombrado nombra al sector.

Cobertura plena (3 dims reales: penetración móvil/internet + calidad banda ancha);
la ANTIGÜEDAD del boletín público (2022-Q1) la refleja la FRESCURA, no la cobertura →
honesto: cableado-pero-no-publicable hasta que INDOTEL actualice. NUNCA inventar data.

Eje doctrinal ÚNICO: ``telecom_intel`` + thin ``telecom_outlook`` → numeric_guard.
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
    register_product,
)
from shared.products.render import render_product_pdf
from modules.telecom_intel.ai_context import telecom_ai_context
from modules.telecom_intel.models.models import TelecomScore
from modules.telecom_intel.service import get_latest

logger = logging.getLogger("sdq.products.telecom")

SECTOR_KEY = "telecom"
DISPLAY = "Sector Telecomunicaciones · RD"
_UNSET = object()

_SECTION_TITLES = {
    "telecom_pulse": "Pulso del Sector Telecom",
    "telecom_assessment": "Evaluación de Desarrollo Telecom (IDT)",
    "recommendation": "Lectura para Decisión",
    "limitations": "Limitaciones",
}
_LIMITATIONS = (
    "Índice de Desarrollo Telecom (IDT) sobre los datos abiertos de INDOTEL (boletín "
    "trimestral de indicadores): penetración móvil/telefónica y de internet (por 100 "
    "habitantes, población censal ONE) y calidad vía banda ancha (% del internet). El "
    "boletín público más reciente es 2022-Q1, por lo que la lectura corresponde a esa "
    "fecha de corte (la frescura del producto lo refleja); no se proyectan cifras más "
    "recientes. Índice de alcance/calidad, no un veredicto financiero del sector."
)
_NO_DATA = (
    "No hay IDT persistido: el producto está cableado pero su cobertura (G1) es "
    "insuficiente para publicar. No se fabrican cifras."
)


def telecom_manifest() -> SectorProductManifest:
    return SectorProductManifest(
        sector_key=SECTOR_KEY, display_name="SDQ Telecom Intelligence", levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=("telecom_pulse",), narrative_templates=("telecom_outlook",),
                audience="mercado / abierto", cadence="periodic",
                watermark="Vista abierta · SDQMIP", price_band="abierto"),
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.named_entity,
                sections=("telecom_assessment",), narrative_templates=("telecom_outlook",),
                audience="cliente / comité", cadence="recurring", price_band="suscripción"),
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=("telecom_assessment", "recommendation", "limitations"),
                narrative_templates=("telecom_outlook",),
                audience="comité / contraparte", cadence="on_demand", price_band="on-demand"),
        })


def _latest_score(db: Session, period: Optional[str] = None) -> Optional[TelecomScore]:
    """Último IDT (o el del período) en SAVEPOINT: una lectura que falla no tumba el
    recompute compartido (que itera todos los sectores en una sesión)."""
    try:
        with db.begin_nested():
            return get_latest(db, period or None)
    except Exception as e:  # noqa: BLE001
        logger.warning("IDT no disponible: %s", e)
        return None


def _index_dict(s: TelecomScore) -> Dict[str, Any]:
    bd = s.breakdown or {}
    return {"telecom_score": s.telecom_score, "band": s.band, "coverage": s.coverage,
            "dimensions": bd.get("dimensions", {}), "metrics": bd.get("metrics", {})}


def _fmt(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.1f}"


def _period_year(period: str) -> Optional[int]:
    """Año del período ('2022-Q1' → 2022)."""
    try:
        return int(str(period)[:4])
    except (ValueError, TypeError):
        return None


class TelecomProduct:
    sector_key = SECTOR_KEY

    def __init__(self, db: Optional[Session] = None):
        self._db = db
        self._cache: Any = _UNSET

    def _require_db(self) -> Session:
        if self._db is None:
            raise RuntimeError("TelecomProduct requiere una sesión de DB para esta operación.")
        return self._db

    def _latest(self) -> Optional[TelecomScore]:
        if self._cache is _UNSET:
            self._cache = _latest_score(self._require_db())
        return self._cache

    def product_manifest(self) -> SectorProductManifest:
        return telecom_manifest()

    # ── Señales de readiness ──
    def data_signals(self) -> DataHealth:
        from datetime import date
        s = self._latest()
        if s is None:
            return DataHealth(coverage=0.0, freshness_days=None, cadence="quarterly",
                              sources=("INDOTEL",), detail="Sin IDT persistido.")
        coverage = s.coverage if s.coverage is not None else 0.0
        # Cadencia TRIMESTRAL: el boletín público más reciente (2022-Q1) está rezagado →
        # la frescura cae honestamente (cableado-pero-no-publicable hasta actualización).
        freshness = None
        yr = _period_year(s.period)
        if yr is not None:
            q = 1
            if "Q" in str(s.period):
                try:
                    q = int(str(s.period).split("Q")[1])
                except (ValueError, IndexError):
                    q = 1
            quarter_end = date(yr, min(3 * q, 12), 28)
            freshness = (date.today() - quarter_end).days
        return DataHealth(coverage=coverage, freshness_days=freshness, cadence="quarterly",
                          sources=("INDOTEL",),
                          detail=f"IDT {_fmt(s.telecom_score)} ({s.band}) en {s.period}")

    def has_engine(self) -> bool:
        return self._latest() is not None

    def validation_state(self) -> ValidationState:
        # Índice de alcance/calidad sobre dato real INDOTEL; sin backtest (no aplica un
        # outcome de shock como en otros ejes) → validación parcial honesta.
        return ValidationState(approved=True, score=0.55,
                               notes="IDT sobre dato real INDOTEL (penetración + banda ancha); "
                                     "sin backtest. Boletín público más reciente: 2022-Q1.")

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
        index = {"telecom_score": 91.7, "band": "Fuerte", "coverage": 1.0,
                 "dimensions": {
                     "mobile_penetration": {"score": 100.0, "weight": 0.30,
                                            "provenance": "real", "contribution": 30.0},
                     "internet_penetration": {"score": 89.1, "weight": 0.40,
                                              "provenance": "real", "contribution": 35.6},
                     "broadband_quality": {"score": 86.9, "weight": 0.30,
                                           "provenance": "real", "contribution": 26.1}},
                 "metrics": {"mobile_penetration": 104.7, "internet_penetration": 89.1,
                             "broadband_share": 86.9, "revenue_growth": 6.95,
                             "lines_total": 11265937, "internet_total": 9584953}}
        payload = {"has_score": True, "index": index}
        if tier == ProductTier.pulse:
            return ProductSnapshot(tier=tier, period="2022-Q1", payload=payload,
                                   entity_name=None, entity_roster=())
        return ProductSnapshot(tier=tier, period="2022-Q1", payload=payload, entity_name=DISPLAY)

    # ── Narrativas (sin DB) ──
    async def narratives(self, tier: ProductTier, snapshot: ProductSnapshot,
                         lang: str = "es") -> Dict[str, str]:
        sections = self.product_manifest().require_level(tier).sections
        if not snapshot.payload.get("has_score"):
            return {sec: (_LIMITATIONS if sec == "limitations" else _NO_DATA)
                    for sec in sections}

        from shared.narrative.claude_engine import narrative_engine
        base_ctx = telecom_ai_context(snapshot.payload["index"], snapshot.period)
        audience = "inversionista"
        mode = ("standard" if tier == ProductTier.pulse
                else "deep" if tier == ProductTier.deep_dive else "detailed")
        out: Dict[str, str] = {}
        for section in sections:
            if section == "limitations":
                out["limitations"] = _LIMITATIONS
                continue
            ctx = dict(base_ctx)
            if section == "recommendation":
                ctx["enfoque"] = ("Cierre ACCIONABLE: entre alcance (penetración de internet) y "
                                  "calidad (banda ancha), la palanca de conectividad con mayor "
                                  "retorno, dado el cuadro anterior.")
            res = await narrative_engine.generate(
                context=ctx, template="telecom_outlook", mode=mode,
                axis="telecom_intel", audience=audience)
            out[section] = res.text
        return out

    # ── Render (sin DB, renderer genérico) ──
    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None) -> str:
        level = self.product_manifest().require_level(tier)
        title = {"pulse": "Pulse Telecom", "insight": "Insight Telecom",
                 "deep_dive": "Deep Dive Telecom"}.get(tier.value, "Telecom")
        display = ("Sistema de Telecomunicaciones · RD" if tier == ProductTier.pulse else DISPLAY)
        tables: List = []
        index = (snapshot.payload or {}).get("index") or {}
        dims = index.get("dimensions") or {}
        if dims:
            rows = [["Dimensión", "Score", "Peso"]] + [
                [str(k), _fmt((d or {}).get("score")), _fmt((d or {}).get("weight"))]
                for k, d in dims.items()]
            tables.append(("Dimensiones del IDT", rows))
        return render_product_pdf(
            sector_key=SECTOR_KEY, display_name=display, title=title,
            period=snapshot.period, narratives=narratives,
            section_titles=_SECTION_TITLES, tables=tables, subtitle=None,
            watermark=level.watermark, sample=sample, output_dir=output_dir)


register_product(SECTOR_KEY, lambda db: TelecomProduct(db))
