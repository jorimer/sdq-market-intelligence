"""Banca como sector de referencia del framework de productización.

Implementa el ``Protocol`` ``SectorProduct`` (shared/products) SIN tocar el framework:
manifiesto declarativo de los 3 niveles + señales de readiness + producción de reporte
por nivel reusando el generador y el motor de narrativa existentes.

Reparto de responsabilidades:
  - ``snapshot`` / ``data_signals`` / ``has_engine`` / ``validation_state`` leen la DB.
  - ``narratives`` / ``render`` operan SOBRE el snapshot (sin DB) → permiten muestras
    sintéticas (``Banco Demo, S.A.``) sin entidad real en la base.

Doctrina: Pulse es de sistema y nunca nombra entidad (el sensor del framework lo
verifica con el roster que ``snapshot`` adjunta).
"""
from __future__ import annotations

from datetime import date
from typing import Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from shared.products import (
    DataHealth,
    Granularity,
    ProductSnapshot,
    ProductTier,
    SectorProductManifest,
    TierLevelSpec,
    ValidationState,
)
from modules.banking_score.models.models import Bank, ModelType, RatingResult
from modules.banking_score.reports.narrative import generate_named_narratives
from modules.banking_score.reports.pdf_generator import generate_pdf_report
from modules.banking_score.scoring.market_concentration import compute_market_concentration
from modules.banking_score.scoring.system_aggregate import system_band_distribution

SECTOR_KEY = "banking"
SYSTEM_LABEL = "Sistema Bancario Dominicano"

# Datos demo SINTÉTICOS de la muestra de conversión (sin DB, sin entidad real). KPIs del
# Anexo del catálogo: CAR ~16.8%, morosidad ~1.9%, ROE ~19.4%, eficiencia ~56%, liquidez
# ~31%. Banda resultante ≈ SDQ-AA- (Fuerte). Fuente única de la muestra (la usa el
# producto y el script scripts/generate_tier_samples.py).
SAMPLE_NAME = "Banco Demo, S.A."
SAMPLE_PERIOD = "2024-12-31"
SAMPLE_SCORING = {
    "overall_score": 80.3, "rating_tier": "SDQ-AA-",
    "sub_components": {"solidez": 85, "calidad": 82, "eficiencia": 72,
                       "liquidez": 78, "diversificacion": 62},
    "indicators": {
        "solvencia": {"raw": 16.8, "score": 90, "available": True},
        "morosidad": {"raw": 1.9, "score": 85, "available": True},
        "roe": {"raw": 19.4, "score": 78, "available": True},
        "eficiencia": {"raw": 56.0, "score": 70, "available": True},
        "liquidez": {"raw": 31.0, "score": 80, "available": True},
    },
}
SAMPLE_SYSTEM = {"band_distribution": {"Fuerte": 6, "Adecuado": 8, "Vigilancia": 3, "Crítico": 1},
                 "n_entities": 18, "system_avg_score": 71.8, "period": SAMPLE_PERIOD}
SAMPLE_PEER = {"metric_label": "Activos", "cr5": 71.2, "cr10": 87.4, "hhi": 1380}

# Secciones por nivel (manifiesto). Insight = pilares + comparativo (monitoreo
# recurrente); Deep Dive añade riesgo/escenarios + recomendación + limitaciones.
_INSIGHT_SECTIONS = (
    "executive_summary", "solidez_financiera", "calidad_activos",
    "eficiencia_rentabilidad", "liquidez", "diversificacion", "comparative",
)
_DEEP_DIVE_SECTIONS = _INSIGHT_SECTIONS + ("risk_assessment", "recommendation", "limitations")

# Limitaciones: texto estático (sin cifras → guard anti-alucinación trivialmente limpio).
_LIMITATIONS_TEXT = (
    "Este análisis se basa en información pública supervisada a la fecha de corte "
    "indicada; no incorpora información material no pública ni eventos posteriores al "
    "período. Las calificaciones SDQ son opiniones independientes de SDQ Consulting y "
    "no constituyen una recomendación para comprar, vender o mantener instrumentos."
)


def banking_manifest() -> SectorProductManifest:
    """Manifiesto declarativo de los 3 niveles de Banca (única fuente de verdad)."""
    return SectorProductManifest(
        sector_key=SECTOR_KEY,
        display_name="SDQ Banking Intelligence",
        levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=("system_overview",), narrative_templates=("sector_outlook",),
                audience="mercado / abierto", cadence="periodic",
                watermark="Vista abierta · SDQMIP", base_report_type="sector_outlook",
                price_band="abierto",
            ),
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.named_entity,
                sections=_INSIGHT_SECTIONS,
                narrative_templates=("executive_summary", "subcomponent_focus", "comparative"),
                audience="cliente / comité", cadence="recurring",
                base_report_type="full_rating", price_band="suscripción",
            ),
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=_DEEP_DIVE_SECTIONS,
                narrative_templates=("executive_summary", "subcomponent_focus",
                                     "comparative", "risk_assessment", "recommendation"),
                audience="comité de crédito / contraparte", cadence="on_demand",
                base_report_type="full_rating", price_band="on-demand",
            ),
        },
    )


def _parse_period(period: Optional[str]) -> Optional[date]:
    """Convierte un período (``YYYY-MM-DD``) a date; None si no parsea (→ último)."""
    if not period:
        return None
    try:
        return date.fromisoformat(period)
    except ValueError:
        return None


class BankingProduct:
    """``SectorProduct`` de Banca. ``db`` es opcional: las muestras sintéticas usan
    solo ``narratives``/``render`` (sin DB)."""

    sector_key = SECTOR_KEY

    def __init__(self, db: Optional[Session] = None):
        self._db = db

    # ── Manifiesto ──
    def product_manifest(self) -> SectorProductManifest:
        return banking_manifest()

    # ── Señales de readiness (leen DB) ──
    def _require_db(self) -> Session:
        if self._db is None:
            raise RuntimeError("BankingProduct requiere una sesión de DB para esta operación.")
        return self._db

    def data_signals(self) -> DataHealth:
        db = self._require_db()
        latest = (
            db.query(func.max(RatingResult.period_end))
            .filter(RatingResult.model_type == ModelType.deterministic)
            .scalar()
        )
        if latest is None:
            return DataHealth(coverage=0.0, freshness_days=None,
                              sources=("SIB", "SIMBAD", "BCRD"), detail="Sin ratings deterministas.")
        n = (db.query(func.count(RatingResult.id))
             .filter(RatingResult.period_end == latest,
                     RatingResult.model_type == ModelType.deterministic).scalar() or 0)
        freshness = (date.today() - latest).days
        return DataHealth(
            coverage=1.0 if n > 0 else 0.0, freshness_days=freshness,
            sources=("SIB", "SIMBAD", "BCRD"),
            detail=f"{n} entidades calificadas en {latest}.",
        )

    def has_engine(self) -> bool:
        db = self._require_db()
        return (db.query(func.count(RatingResult.id)).scalar() or 0) > 0

    def validation_state(self) -> ValidationState:
        # Banca es el eje "Listo" (en producción, metodología de 19 indicadores
        # validada). Es el sector de referencia del framework.
        return ValidationState(approved=True, score=1.0,
                               notes="Eje 1 en producción; metodología determinista validada.")

    # ── Snapshot por nivel (lee DB) ──
    def snapshot(self, tier: ProductTier, period: str,
                 scope: Optional[str] = None) -> ProductSnapshot:
        db = self._require_db()
        if tier == ProductTier.pulse:
            agg = system_band_distribution(db, _parse_period(period))
            payload = {
                "band_distribution": agg["band_distribution"],
                "n_entities": agg["n_entities"],
                "period": agg["period"],
                "system_avg_score": agg["system_avg_score"],
            }
            return ProductSnapshot(
                tier=tier, period=agg["period"] or period, payload=payload,
                entity_name=None, entity_roster=tuple(agg["roster"]),
            )
        # Niveles nombrados: requiere identificar la entidad (scope = id o nombre).
        if not scope:
            raise ValueError("Se requiere 'scope' (entidad) para Insight/Deep Dive.")
        bank = (db.query(Bank).filter(Bank.id == scope).one_or_none()
                or db.query(Bank).filter(Bank.name == scope).one_or_none())
        if bank is None:
            raise ValueError(f"No se encontró la entidad '{scope}'.")
        q = db.query(RatingResult).filter(
            RatingResult.bank_id == bank.id,
            RatingResult.model_type == ModelType.deterministic)
        pe = _parse_period(period)
        rr = (q.filter(RatingResult.period_end == pe).one_or_none() if pe else None) \
            or q.order_by(RatingResult.period_end.desc()).first()
        if rr is None:
            raise ValueError(f"No hay calificación para '{bank.name}'.")
        scoring_result = {
            "overall_score": float(rr.overall_score),
            "rating_tier": rr.rating_tier,
            "sub_components": {
                "solidez": float(rr.solidez_score or 0), "calidad": float(rr.calidad_score or 0),
                "eficiencia": float(rr.eficiencia_score or 0), "liquidez": float(rr.liquidez_score or 0),
                "diversificacion": float(rr.diversificacion_score or 0),
            },
            "indicators": rr.indicator_details or {},
            "model_version": rr.model_version,
        }
        conc = compute_market_concentration(db, rr.period_end, "activos")
        peer_block = ({"metric_label": conc["metric_label"], "cr5": conc["cr5"],
                       "cr10": conc["cr10"], "hhi": conc["hhi"]} if conc.get("available") else None)
        return ProductSnapshot(
            tier=tier, period=str(rr.period_end),
            payload={"scoring_result": scoring_result, "peer_block": peer_block},
            entity_name=bank.name,
        )

    # ── Muestra sintética (sin DB — datos demo ilustrativos, para el PDF watermarked) ──
    def sample_snapshot(self, tier: ProductTier) -> ProductSnapshot:
        if tier == ProductTier.pulse:
            return ProductSnapshot(tier=tier, period=SAMPLE_PERIOD, payload=dict(SAMPLE_SYSTEM),
                                   entity_name=None, entity_roster=(SAMPLE_NAME,))
        return ProductSnapshot(
            tier=tier, period=SAMPLE_PERIOD,
            payload={"scoring_result": dict(SAMPLE_SCORING), "peer_block": dict(SAMPLE_PEER)},
            entity_name=SAMPLE_NAME)

    # ── Narrativas (sin DB — operan sobre el snapshot) ──
    async def narratives(self, tier: ProductTier, snapshot: ProductSnapshot,
                         lang: str = "es") -> Dict[str, str]:
        from shared.narrative.claude_engine import narrative_engine
        manifest = self.product_manifest().require_level(tier)
        if tier == ProductTier.pulse:
            ctx = {
                "period": snapshot.period,
                "distribucion_bandas": snapshot.payload.get("band_distribution", {}),
                "n_entidades": snapshot.payload.get("n_entities"),
                "score_promedio_sistema": snapshot.payload.get("system_avg_score"),
                "scope": "Sistema bancario dominicano (agregado, sin entidades nombradas)",
            }
            # axis="banking" → ruta cerebro con numeric_guard (G3). Pulse es el nivel
            # ABIERTO: jamás narra cifras sin gobernanza. Audiencia de mercado.
            res = await narrative_engine.generate(
                context=ctx, template="sector_outlook", mode="standard",
                axis="banking", audience="inversionista")
            return {"system_overview": res.text}

        scoring_result = snapshot.payload["scoring_result"]
        peer_block = snapshot.payload.get("peer_block")
        claude_sections = [s for s in manifest.sections if s != "limitations"]
        out = await generate_named_narratives(
            claude_sections, snapshot.entity_name or "Entidad", scoring_result,
            snapshot.period, benchmarks=peer_block,
            mode="detailed" if tier == ProductTier.deep_dive else "standard",
        )
        if "limitations" in manifest.sections:
            out["limitations"] = _LIMITATIONS_TEXT
        return out

    # ── Render (sin DB) ──
    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None) -> str:
        level = self.product_manifest().require_level(tier)
        if tier == ProductTier.pulse:
            scoring_result = {"overall_score": snapshot.payload.get("system_avg_score") or 0,
                              "rating_tier": "Sistema", "sub_components": {}, "indicators": {}}
            return await generate_pdf_report(
                level.base_report_type or "sector_outlook", SYSTEM_LABEL, scoring_result,
                snapshot.period, narratives=narratives, output_dir=output_dir,
                sections=list(level.sections), tier=tier.value, watermark=level.watermark,
                sample=sample, band_distribution=snapshot.payload.get("band_distribution"),
            )
        scoring_result = snapshot.payload["scoring_result"]
        return await generate_pdf_report(
            level.base_report_type or "full_rating", snapshot.entity_name or "Entidad",
            scoring_result, snapshot.period, narratives=narratives, output_dir=output_dir,
            sections=list(level.sections), tier=tier.value, watermark=level.watermark,
            sample=sample, peer_block=snapshot.payload.get("peer_block"),
        )


# Auto-registro en el catálogo de productos (anti-Frankenstein: el módulo se registra
# a sí mismo; shared/products nunca importa banking). Idempotente.
from shared.products.registry import register_product  # noqa: E402

register_product(SECTOR_KEY, lambda db: BankingProduct(db))
