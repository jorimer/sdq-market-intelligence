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
from modules.banking_score.scoring.system_aggregate import system_pulse_aggregate

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

# Narrativa CURADA tier-1 de la muestra (exemplar, no generada al vuelo). Es la pieza de
# conversión: su calidad no depende del motor IA en runtime. Coherente con los SAMPLE_*.
SAMPLE_NARRATIVES = {
    "system_overview": (
        "El sistema bancario dominicano cierra el período con un **score promedio de "
        "71.8/100**, en la franja alta de la banda Adecuado y a las puertas de Fuerte. "
        "La distribución es reveladora: de las **18 entidades** evaluadas, **6 califican "
        "como Fuerte** (≥80) y **8 como Adecuado**, mientras **3 permanecen en Vigilancia** "
        "y **1 en estado Crítico**. Es un sistema de dos velocidades — un núcleo sólido y "
        "bien capitalizado convive con una cola de entidades cuya solvencia o calidad de "
        "activos exige monitoreo activo. La concentración refuerza la lectura: los cinco "
        "mayores actores controlan cerca del **71% de los activos**, de modo que la "
        "estabilidad agregada depende, en buena medida, de la disciplina de ese núcleo. "
        "Para un inversionista o contraparte, el mensaje es claro: el promedio esconde "
        "dispersión, y la selección de entidad pesa más que la exposición al sistema."
    ),
    "executive_summary": (
        "**Banco Demo, S.A. obtiene una calificación SDQ-AA- (score 80.3/100)**, en la "
        "banda Fuerte y entre las entidades mejor calificadas del sistema. El rating se sostiene "
        "sobre dos pilares de calidad excepcional —**solidez financiera (85)** y **calidad "
        "de activos (82)**—, que describen un banco bien capitalizado y con una cartera "
        "sana. El perfil no está exento de matices: la **diversificación (62)** es el "
        "componente más rezagado y, por lo tanto, la principal vía de mejora del rating. "
        "En términos llanos, Banco Demo es una entidad de riesgo crediticio bajo, con "
        "holgura de capital para absorber shocks y una morosidad contenida, cuya próxima "
        "frontera de valor no está en reforzar lo que ya hace bien, sino en ampliar la "
        "base de ingresos y exposiciones. El veredicto: contraparte de alta calidad, con "
        "un techo de calificación alcanzable si ejecuta su agenda de diversificación."
    ),
    "solidez_financiera": (
        "La solidez financiera es el ancla del perfil de Banco Demo (**score 85/100**). El "
        "índice de solvencia se ubica en **16.8%**, holgadamente por encima del mínimo "
        "regulatorio (10%) y del promedio del sistema, lo que otorga al banco un colchón de "
        "capital equivalente a varios años de pérdidas esperadas. No es una holgura "
        "cosmética: es lo que le permite sostener crecimiento, absorber un deterioro de "
        "cartera y resistir un escenario de estrés sin comprometer su viabilidad. Para un "
        "comité de crédito, una solvencia de este orden marca la diferencia entre una "
        "contraparte que «aguanta» un ciclo adverso y una que lo «amplifica». La lectura es "
        "de fortaleza estructural, no coyuntural."
    ),
    "calidad_activos": (
        "Con un **score de 82/100**, la calidad de activos confirma una gestión de riesgo "
        "crediticio disciplinada. La morosidad se sitúa en **1.9%**, baja tanto en términos "
        "absolutos como frente a la media del sistema, y sugiere originación prudente y "
        "seguimiento efectivo de la cartera vencida. Lo relevante no es solo el dato puntual "
        "sino lo que implica: una cartera de bajo deterioro reduce la presión sobre "
        "provisiones, libera resultado para capitalización y abarata el fondeo al señalar "
        "menor riesgo a depositantes y acreedores. El punto de atención —más prospectivo "
        "que actual— es la sensibilidad de esa morosidad a un giro del ciclo; con la "
        "solvencia que exhibe, el banco tiene margen para absorber un repunte sin tensionar "
        "su calificación."
    ),
    "eficiencia_rentabilidad": (
        "La eficiencia y rentabilidad (**score 72/100**) son sólidas, aunque marcan el "
        "contraste con los pilares de capital y activos. El **ROE de 19.4%** es atractivo y "
        "supera el costo de capital típico del sector: el banco crea valor para sus "
        "accionistas. El índice de eficiencia de **56%** —costos sobre ingresos— es "
        "razonable pero deja recorrido: cada punto de mejora operativa se traduce directo "
        "en rentabilidad y en capitalización orgánica. La lectura para un inversionista es "
        "la de un banco rentable que aún no ha exprimido del todo su apalancamiento "
        "operativo; esta palanca, a diferencia de la diversificación, depende más de "
        "ejecución interna que de condiciones de mercado."
    ),
    "liquidez": (
        "La liquidez obtiene un **score de 78/100**, con un ratio de activos líquidos del "
        "**31%**. Es una posición cómoda: el banco puede honrar retiros y vencimientos sin "
        "recurrir a fondeo de emergencia ni liquidar activos a descuento, lo que en un "
        "sistema concentrado y sensible a la confianza es un activo en sí mismo. El "
        "equilibrio es fino —demasiada liquidez deprime el margen, demasiado poca expone a "
        "riesgo de refinanciación— y el 31% sugiere una tesorería bien calibrada: defensiva "
        "sin ser improductiva. Para una contraparte, este perfil reduce materialmente el "
        "riesgo de incumplimiento de corto plazo."
    ),
    "diversificacion": (
        "La diversificación es el componente más rezagado del perfil (**score 62/100**) y, "
        "por eso, la oportunidad de mayor retorno sobre la calificación. Un score en este "
        "rango suele apuntar a una base de ingresos o de cartera más concentrada de lo "
        "óptimo —por segmento de cliente, por producto o por geografía—, lo que aumenta la "
        "sensibilidad del banco a un shock localizado. La oportunidad es asimétrica: "
        "mientras capital y activos ya están cerca de su techo y ofrecen poco margen, la "
        "diversificación es la dimensión donde una agenda deliberada —ampliar fuentes de "
        "ingreso, equilibrar la cartera— puede mover la aguja del rating. Es, en síntesis, "
        "la frontera de creación de valor de Banco Demo."
    ),
    "comparative": (
        "Frente al sistema, Banco Demo se ubica con claridad en el grupo de cabeza: su "
        "score de 80.3 supera el promedio del sistema (71.8) y lo coloca entre las 6 "
        "entidades en banda Fuerte de un universo de 18. El contexto competitivo importa: "
        "los cinco mayores bancos concentran el **71.2% de los activos** (CR5) y los diez "
        "mayores el **87.4%** (CR10), con un HHI de **1.380** que describe un mercado "
        "moderadamente concentrado. En ese tablero, Banco Demo compite en el segmento "
        "premium por calidad crediticia, no por tamaño. La implicación estratégica es "
        "doble: tiene el perfil de riesgo para ganar negocio de contrapartes exigentes, "
        "pero crece en un mercado donde el núcleo concentrado fija el ritmo. Diferenciarse "
        "por solidez —no por volumen— es su ventaja sostenible."
    ),
    "risk_assessment": (
        "El perfil de riesgo de Banco Demo se clasifica como **bajo**. Los dos vectores que "
        "dominan la calificación —capital y calidad de activos— actúan como amortiguadores: "
        "una solvencia de 16.8% y una morosidad de 1.9% configuran una entidad con amplia "
        "capacidad de absorción de pérdidas y baja probabilidad de deterioro abrupto. Los "
        "riesgos materiales son de segundo orden y, sobre todo, prospectivos. Primero, "
        "**concentración**: la diversificación rezagada (62) implica que un shock sectorial "
        "tendría un impacto desproporcionado sobre la cartera. Segundo, **sensibilidad "
        "cíclica de la morosidad**: el 1.9% es un dato de período benigno; un giro del "
        "ciclo lo presionaría, aunque la solvencia da margen para absorberlo. Tercero, "
        "**eficiencia**: un índice de 56% deja la rentabilidad expuesta a presiones de "
        "costos. Ninguno amenaza la viabilidad; definen la agenda de gestión, no la solvencia."
    ),
    "recommendation": (
        "Para una contraparte o comité de crédito, Banco Demo es una **aprobación clara** "
        "dentro de su segmento de riesgo: capital holgado, cartera sana y liquidez cómoda "
        "lo sitúan entre las contrapartes de mayor calidad del sistema. La decisión "
        "operativa no es «si» exponerse, sino «cómo» dimensionar: dada su concentración de "
        "negocio, conviene monitorear la evolución de su diversificación como indicador "
        "adelantado de resiliencia. Para el propio banco, la palanca de mayor retorno sobre "
        "la calificación es inequívoca —**diversificación**—: con capital y activos cerca de "
        "su techo, es la única dimensión donde una agenda deliberada puede elevar el rating "
        "desde SDQ-AA- hacia la franja superior. La eficiencia operativa es la palanca "
        "secundaria, de ejecución interna. Ahí está el valor."
    ),
}

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
                sections=("system_overview",), narrative_templates=("system_pulse",),
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
            agg = system_pulse_aggregate(db, _parse_period(period))
            payload = {
                "band_distribution": agg["band_distribution"],
                "n_entities": agg["n_entities"],
                "period": agg["period"],
                "system_avg_score": agg["system_avg_score"],
            }
            # Cifras derivadas de sistema (anonimizadas) para que el Pulse ancle su lectura.
            if agg.get("cifras_derivadas"):
                payload["cifras_derivadas"] = agg["cifras_derivadas"]
            if agg.get("tendencia_score"):
                payload["tendencia_score"] = agg["tendencia_score"]
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

    def sample_narratives(self, tier: ProductTier) -> Dict[str, str]:
        """Narrativa CURADA tier-1 de la muestra (exemplar). Devuelve las secciones del
        nivel; ``limitations`` reusa el disclaimer estático. NO usa el motor IA."""
        sections = self.product_manifest().require_level(tier).sections
        return {sec: (_LIMITATIONS_TEXT if sec == "limitations" else SAMPLE_NARRATIVES[sec])
                for sec in sections}

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
            # Cifras derivadas de sistema (share por banda, cola de riesgo, concentración,
            # trayectoria) cuando el snapshot las trae: dan al modelo de qué agarrarse en
            # lugar de enumerar lo que falta. Degradan con gracia si no están (muestras/tests).
            if snapshot.payload.get("cifras_derivadas"):
                ctx["cifras_derivadas"] = snapshot.payload["cifras_derivadas"]
            if snapshot.payload.get("tendencia_score"):
                ctx["tendencia_score"] = snapshot.payload["tendencia_score"]
            # axis="banking" + thin "system_pulse" (agregado de sistema, NO el IAI de
            # sector_intel) → ruta cerebro con numeric_guard (G3). Pulse es el nivel ABIERTO:
            # jamás narra cifras sin gobernanza. Audiencia de mercado.
            res = await narrative_engine.generate(
                context=ctx, template="system_pulse", mode="standard",
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
