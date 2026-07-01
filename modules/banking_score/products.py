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
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from shared.contracts import load_macro_contract
from shared.products import (
    DataHealth,
    Granularity,
    ProductSnapshot,
    ProductTier,
    SectorProductManifest,
    TierLevelSpec,
    ValidationState,
    distinct_periods,
)
from modules.banking_score.models.models import Bank, ModelType, RatingResult
from modules.banking_score.reports.narrative import generate_named_narratives
from modules.banking_score.reports.pdf_generator import generate_pdf_report
from modules.banking_score.scoring.amplitude import entity_trajectories, period_percentiles
from modules.banking_score.scoring.market_concentration import compute_market_concentration
from modules.banking_score.scoring.sensitivity import sensitivity_table
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
        "71.8/100**, situado en la franja alta de la banda Adecuado y próximo al umbral de "
        "Fuerte. La distribución evidencia una dispersión material: de las **18 entidades** "
        "evaluadas, **6 califican como Fuerte** (≥80) y **8 como Adecuado**, mientras **3 "
        "permanecen en Vigilancia** y **1 en estado Crítico**. El sistema presenta una "
        "estructura heterogénea, en la que un núcleo sólido y bien capitalizado coexiste "
        "con un conjunto de entidades cuya solvencia o calidad de activos requiere "
        "monitoreo activo. La concentración refuerza esta lectura: los cinco mayores "
        "actores controlan cerca del **71% de los activos**, de modo que la estabilidad "
        "agregada depende, en medida considerable, de la disciplina de ese núcleo. Para un "
        "inversionista o contraparte, el promedio agregado contiene una dispersión "
        "significativa entre entidades, por lo que la selección de la entidad pondera más "
        "que la exposición al sistema en su conjunto."
    ),
    "executive_summary": (
        "**Banco Demo, S.A. obtiene una calificación SDQ-AA- (score 80.3/100)**, ubicada en "
        "la banda Fuerte y entre las entidades mejor calificadas del sistema. El rating se "
        "sostiene sobre dos pilares de calidad sobresaliente —**solidez financiera (85)** y "
        "**calidad de activos (82)**—, que describen una entidad bien capitalizada y con una "
        "cartera sana. El perfil presenta, no obstante, áreas de mejora: la "
        "**diversificación (62)** constituye el componente más rezagado y, por lo tanto, la "
        "principal vía de fortalecimiento del rating. En síntesis, Banco Demo es una entidad "
        "de riesgo crediticio bajo, con holgura de capital para absorber shocks y una "
        "morosidad contenida, cuya próxima frontera de valor no reside en reforzar sus "
        "fortalezas consolidadas, sino en ampliar la base de ingresos y exposiciones. La "
        "valoración de cierre la posiciona como contraparte de alta calidad, con un techo de "
        "calificación alcanzable en la medida en que ejecute su agenda de diversificación."
    ),
    "solidez_financiera": (
        "La solidez financiera constituye el principal soporte del perfil de Banco Demo "
        "(**score 85/100**). El índice de solvencia se ubica en **16.8%**, holgadamente por "
        "encima del mínimo regulatorio (10%) y del promedio del sistema, lo que otorga a la "
        "entidad un colchón de capital equivalente a varios años de pérdidas esperadas. "
        "Dicha holgura no tiene carácter coyuntural: habilita el sostenimiento del "
        "crecimiento, la absorción de un deterioro de cartera y la resistencia a un "
        "escenario de estrés sin comprometer la viabilidad. Para un comité de crédito, una "
        "solvencia de este orden distingue a una contraparte que mitiga un ciclo adverso de "
        "una que lo amplifica. La lectura es de fortaleza estructural, no coyuntural."
    ),
    "calidad_activos": (
        "Con un **score de 82/100**, la calidad de activos confirma una gestión de riesgo "
        "crediticio disciplinada. La morosidad se sitúa en **1.9%**, reducida tanto en "
        "términos absolutos como frente a la media del sistema, lo que sugiere una "
        "originación prudente y un seguimiento efectivo de la cartera vencida. La relevancia "
        "del indicador trasciende el dato puntual y se extiende a sus implicaciones: una "
        "cartera de bajo deterioro reduce la presión sobre provisiones, libera resultado "
        "para capitalización y abarata el fondeo al señalar un menor riesgo a depositantes y "
        "acreedores. El punto de atención, de naturaleza prospectiva, reside en la "
        "sensibilidad de esa morosidad ante un giro del ciclo; con la solvencia que exhibe, "
        "la entidad dispone de margen para absorber un repunte sin tensionar su calificación."
    ),
    "eficiencia_rentabilidad": (
        "La eficiencia y la rentabilidad (**score 72/100**) son sólidas, si bien se sitúan "
        "por debajo de los pilares de capital y activos. El **ROE de 19.4%** resulta "
        "atractivo y supera el costo de capital habitual del sector, lo que evidencia "
        "generación de valor para los accionistas. El índice de eficiencia de **56%** "
        "—costos sobre ingresos— es razonable, aunque conserva recorrido: cada punto de "
        "mejora operativa se traduce de forma directa en rentabilidad y en capitalización "
        "orgánica. Para un inversionista, la lectura corresponde a una entidad rentable que "
        "aún no ha materializado plenamente su apalancamiento operativo; esta palanca, a "
        "diferencia de la diversificación, depende en mayor grado de la ejecución interna "
        "que de las condiciones de mercado."
    ),
    "liquidez": (
        "La liquidez obtiene un **score de 78/100**, con un ratio de activos líquidos del "
        "**31%**. La posición es holgada: la entidad puede honrar retiros y vencimientos sin "
        "recurrir a fondeo de emergencia ni liquidar activos a descuento, atributo "
        "particularmente valioso en un sistema concentrado y sensible a la confianza. El "
        "equilibrio es estrecho —un exceso de liquidez deprime el margen y una posición "
        "insuficiente expone a riesgo de refinanciación— y el 31% sugiere una tesorería bien "
        "calibrada, defensiva sin resultar improductiva. Para una contraparte, este perfil "
        "reduce de forma material el riesgo de incumplimiento de corto plazo."
    ),
    "diversificacion": (
        "La diversificación constituye el componente más rezagado del perfil (**score "
        "62/100**) y, por ello, la oportunidad de mayor retorno sobre la calificación. Un "
        "score en este rango suele indicar una base de ingresos o de cartera más concentrada "
        "de lo óptimo —por segmento de cliente, por producto o por geografía—, lo que "
        "incrementa la sensibilidad de la entidad ante un shock localizado. La oportunidad "
        "es asimétrica: mientras capital y activos se aproximan a su techo y ofrecen escaso "
        "margen, la diversificación es la dimensión en la que una agenda deliberada —ampliar "
        "fuentes de ingreso y equilibrar la cartera— puede incidir de forma significativa "
        "sobre el rating. Representa, en síntesis, la frontera de creación de valor de Banco "
        "Demo."
    ),
    "comparative": (
        "Frente al sistema, Banco Demo se ubica con claridad en el grupo de cabeza: su score "
        "de 80.3 supera el promedio del sistema (71.8) y lo posiciona entre las 6 entidades "
        "en banda Fuerte de un universo de 18. El contexto competitivo resulta relevante: "
        "los cinco mayores bancos concentran el **71.2% de los activos** (CR5) y los diez "
        "mayores el **87.4%** (CR10), con un HHI de **1.380** que describe un mercado "
        "moderadamente concentrado. En ese entorno, Banco Demo compite en el segmento "
        "premium por calidad crediticia y no por tamaño. La implicación estratégica es "
        "doble: dispone del perfil de riesgo para captar negocio de contrapartes exigentes, "
        "si bien opera en un mercado donde el núcleo concentrado determina el ritmo. La "
        "diferenciación por solidez, antes que por volumen, constituye su ventaja sostenible."
    ),
    "risk_assessment": (
        "El perfil de riesgo de Banco Demo se clasifica como **bajo**. Los dos vectores que "
        "dominan la calificación —capital y calidad de activos— operan como amortiguadores: "
        "una solvencia de 16.8% y una morosidad de 1.9% configuran una entidad con amplia "
        "capacidad de absorción de pérdidas y baja probabilidad de deterioro abrupto. Los "
        "riesgos materiales son de segundo orden y, predominantemente, de naturaleza "
        "prospectiva. En primer término, la **concentración**: la diversificación rezagada "
        "(62) implica que un shock sectorial tendría un impacto desproporcionado sobre la "
        "cartera. En segundo término, la **sensibilidad cíclica de la morosidad**: el 1.9% "
        "corresponde a un período benigno y un giro del ciclo lo presionaría, aunque la "
        "solvencia ofrece margen para absorberlo. En tercer término, la **eficiencia**: un "
        "índice de 56% mantiene la rentabilidad expuesta a presiones de costos. Ninguno de "
        "estos factores compromete la viabilidad; definen la agenda de gestión, no la "
        "solvencia."
    ),
    "entorno_operativo": (
        "El entorno operativo macroeconómico ofrece, en el período, un **telón favorable "
        "con matices** para la solidez bancaria dominicana. La **actividad económica** en "
        "expansión sostiene la demanda de crédito y la capacidad de pago de los deudores, el "
        "factor que más directamente protege la calidad de cartera de una entidad como Banco "
        "Demo. La **inflación**, contenida cerca de la meta del BCRD, permite una política "
        "monetaria menos restrictiva: una **tasa de política** a la baja alivia el costo de "
        "fondeo y descomprime el margen de intermediación. El punto de atención es el **tipo "
        "de cambio**: una depreciación más rápida presionaría la cartera en moneda extranjera "
        "y las expectativas de inflación, con transmisión indirecta a la morosidad. Conviene "
        "subrayar que este entorno es un **telón sistémico común a todo el sistema** —no forma "
        "parte de la calificación standalone de Banco Demo, que mide su fortaleza financiera "
        "propia—; su relevancia es encuadrar la dirección del viento macro que enfrentan por "
        "igual todas las entidades. La señal adelantada a vigilar es la trayectoria del tipo "
        "de cambio y de las reservas internacionales del BCRD."
    ),
    "recommendation": (
        "Para una contraparte o comité de crédito, Banco Demo amerita una **aprobación "
        "clara** dentro de su segmento de riesgo: un capital holgado, una cartera sana y una "
        "liquidez holgada lo sitúan entre las contrapartes de mayor calidad del sistema. La "
        "decisión operativa no se refiere a la conveniencia de la exposición, sino a su "
        "dimensionamiento; dada su concentración de negocio, resulta recomendable monitorear "
        "la evolución de su diversificación como indicador adelantado de resiliencia. Para la "
        "propia entidad, la palanca de mayor retorno sobre la calificación es la "
        "**diversificación**: con capital y activos próximos a su techo, constituye la única "
        "dimensión en la que una agenda deliberada puede elevar el rating desde SDQ-AA- hacia "
        "la franja superior. La eficiencia operativa representa la palanca secundaria, de "
        "ejecución interna, y concentra el potencial de creación de valor remanente."
    ),
}

# Secciones por nivel (manifiesto). Insight = pilares + comparativo (monitoreo
# recurrente); Deep Dive añade riesgo/escenarios + recomendación + limitaciones.
_INSIGHT_SECTIONS = (
    "executive_summary", "solidez_financiera", "calidad_activos",
    "eficiencia_rentabilidad", "liquidez", "diversificacion", "comparative",
)
# Deep Dive añade (Fase 4) el ENTORNO OPERATIVO macro (telón sistémico BCRD, tras el
# comparativo y antes del riesgo forward que encuadra) + riesgo/escenarios +
# recomendación + limitaciones. Entorno operativo es exclusivo del Deep Dive.
_DEEP_DIVE_SECTIONS = _INSIGHT_SECTIONS + (
    "entorno_operativo", "risk_assessment", "recommendation", "limitations")

# Limitaciones: texto estático (sin cifras → guard anti-alucinación trivialmente limpio).
# Incluye el ENCUADRE del score (Fase 3, portado de pensiones): la calificación SDQ es
# fortaleza financiera standalone sobre dato público real — NO un rating de crédito, y no
# incorpora soporte soberano ni techo país. Evita que el lector confunda la escala
# SDQ-AAA…D (nomenclatura tipo calificadora) con un rating crediticio comparable.
_LIMITATIONS_TEXT = (
    "La calificación SDQ es una medida de FORTALEZA FINANCIERA STANDALONE, construida "
    "íntegramente sobre información pública supervisada real (SIB/SIMBAD/BCRD) a la fecha "
    "de corte indicada; no incorpora información material no pública ni eventos "
    "posteriores al período. NO es un rating de crédito y no mide probabilidad de "
    "incumplimiento. En particular, no incorpora soporte soberano, importancia sistémica "
    "ni el techo soberano del país, por lo que no es directamente comparable con las "
    "escalas de las calificadoras internacionales: la solvencia efectiva de una entidad "
    "estatal o sistémica puede diferir de su perfil standalone —el soporte la eleva; el "
    "techo soberano la acota—. La escala SDQ-AAA…D ordena fortaleza financiera relativa "
    "dentro del sistema dominicano, no riesgo de crédito absoluto. Las calificaciones SDQ "
    "son opiniones independientes de SDQ Consulting y no constituyen una recomendación "
    "para comprar, vender o mantener instrumentos."
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

    def available_periods(self) -> List[str]:
        return distinct_periods(self._require_db(), RatingResult.period_end)

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
        # Amplitud (Fase 4): trayectoria multi-período + percentil vs el sistema por
        # indicador. Se calculan aquí (con DB) y viajan en el scoring_result porque
        # narratives()/render() operan sin DB. Degradan con gracia (dicts vacíos) para
        # entidades con un solo período o sin pares.
        scoring_result["trayectorias"] = entity_trajectories(db, bank)
        scoring_result["percentiles"] = period_percentiles(db, bank, rr.period_end)
        entity_type = bank.bank_type.value if bank.bank_type else None
        # Entorno Operativo + Sensibilidades (Fase 4) son amplitud EXCLUSIVA del Deep Dive
        # (Insight se queda con trayectoria+percentil). Se gatean por nivel aquí.
        if tier == ProductTier.deep_dive:
            # Telón macro del BCRD vía el contrato compartido (sin importar macro_monitor).
            # Solo factores con dato real; si no hay contrato, se omite (no se fabrica).
            macro = load_macro_contract(db)
            factors = [f for f in (macro.get("factors") or []) if f.get("direction") != "n/d"]
            if factors:
                scoring_result["entorno_macro"] = {"period": macro.get("period"), "factors": factors}
            # Sensibilidades: qué sube / qué baja el score, con umbral en valor crudo.
            scoring_result["sensibilidades"] = sensitivity_table(
                scoring_result["indicators"], entity_type)
        conc = compute_market_concentration(db, rr.period_end, "activos")
        peer_block = ({"metric_label": conc["metric_label"], "cr5": conc["cr5"],
                       "cr10": conc["cr10"], "hhi": conc["hhi"]} if conc.get("available") else None)
        return ProductSnapshot(
            tier=tier, period=str(rr.period_end),
            payload={"scoring_result": scoring_result, "peer_block": peer_block},
            entity_name=bank.name,
        )

    # ── Entidades elegibles de los niveles nombrados (alimenta el selector del catálogo) ──
    def scope_options(self) -> list[Dict[str, str]]:
        """Entidades para el selector de Insight/Deep Dive: ``value`` = id (lo que
        ``snapshot(scope=…)`` resuelve), ``label`` = nombre, ``group`` = tipo de entidad.
        Ordenadas por nombre. Requiere DB (catálogo real).

        Solo se ofrecen entidades activas CON una calificación determinista: ``snapshot``
        de un nivel nombrado exige un ``RatingResult`` (si no, 422). Ofrecer únicamente las
        que producen reporte evita opciones que fallarían al elegirlas."""
        db = self._require_db()
        banks = (db.query(Bank)
                 .filter(Bank.is_active.is_(True),
                         Bank.id.in_(db.query(RatingResult.bank_id)
                                     .filter(RatingResult.model_type == ModelType.deterministic)))
                 .order_by(Bank.name).all())
        return [{"value": b.id, "label": b.name,
                 "group": b.bank_type.value if b.bank_type else ""} for b in banks]

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
        # Entorno Operativo (Fase 4): se genera solo si el snapshot trajo factores macro
        # reales; sin contrato macro la sección no se emite (nunca vacía/fabricada).
        if not scoring_result.get("entorno_macro"):
            claude_sections = [s for s in claude_sections if s != "entorno_operativo"]
        out = await generate_named_narratives(
            claude_sections, snapshot.entity_name or "Entidad", scoring_result,
            snapshot.period, benchmarks=peer_block,
            # Base 'detailed' en niveles nombrados; _section_mode pone el riesgo en 'deep' y
            # el cierre en 'standard' (profundidad por sección, no un mode único por tier).
            mode="detailed",
        )
        if "limitations" in manifest.sections:
            out["limitations"] = _LIMITATIONS_TEXT
        return out

    # ── Render (sin DB) ──
    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None, fmt: str = "pdf") -> str:
        level = self.product_manifest().require_level(tier)
        if fmt == "docx":
            # Banking usa su generador PDF propio (radar); para Word cae al renderer de marca
            # genérico con las mismas narrativas (layout estándar, editable).
            from shared.products.render import render_product_pdf
            display = SYSTEM_LABEL if tier == ProductTier.pulse else (snapshot.entity_name or "Entidad")
            ttl = {"pulse": "Pulse Banca", "insight": "Insight Banca",
                   "deep_dive": "Deep Dive Banca"}.get(tier.value, "Banca")
            return render_product_pdf(
                sector_key=SECTOR_KEY, display_name=display, title=ttl, period=snapshot.period,
                narratives=narratives, watermark=level.watermark, sample=sample,
                output_dir=output_dir, fmt="docx")
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
