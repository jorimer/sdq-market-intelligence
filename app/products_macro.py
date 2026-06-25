"""Macro & Country Risk como SectorProduct — sector #2 (valida la receta de onboarding).

Macro abarca DOS módulos (``macro_monitor`` + ``macro_political_risk``); por la
independencia de módulos (no se importan entre sí), su producto se ensambla a nivel
**app** vía los **getters públicos** de cada módulo (mismo patrón que ``app/market_brief``),
y se auto-registra en ``shared.products``. NO modifica el framework: solo implementa el
``Protocol SectorProduct`` + su manifiesto + sus señales (la prueba de la receta).

Naturaleza nacional: Macro no tiene múltiples entidades. El nivel nombrado es el PAÍS
(República Dominicana); el Pulse es el pulso macro nacional (sin entidades → el sensor
de anonimización pasa trivialmente con roster vacío).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Dict, List, Optional

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

logger = logging.getLogger("sdq.products.macro")

SECTOR_KEY = "macro"
COUNTRY_NAME = "República Dominicana"
COUNTRY_ISO = "DO"

_SECTION_TITLES = {
    "macro_pulse": "Pulso Macroeconómico",
    "macro_trend": "Tendencia Macroeconómica",
    "risk_assessment": "Evaluación de Riesgos",
    "recommendation": "Lectura para Decisión",
    "limitations": "Limitaciones",
}
_LIMITATIONS = (
    "Lectura macro basada en las series oficiales publicadas a la fecha de corte (BCRD, "
    "DIGEPRES/Crédito Público) y en el índice de riesgo regulatorio-político (IRMP, "
    "fuentes WGI/WDI); no anticipa shocks no publicados ni decisiones de política "
    "posteriores al período."
)

# Narrativa CURADA tier-1 de la muestra (exemplar). Coherente con SAMPLE_* (PIB 5.1%,
# inflación 3.8%, reservas USD 14,200 MM, TC 59.8, déficit -3.1%, IRMP 38.3 «Moderado»).
# IRMP: mayor = MENOR riesgo (no invertir la lectura). Sin cursivas de un asterisco.
_SAMPLE_NARRATIVES = {
    "macro_pulse": (
        "La coyuntura macroeconómica dominicana cierra el período con señales ordenadas. "
        "El **crecimiento del PIB de 5.1% interanual** ubica a RD entre las economías más "
        "dinámicas de la región, sostenido por turismo, remesas e inversión. La "
        "**inflación de 3.8%** se sitúa dentro del rango meta del Banco Central, lo que "
        "da margen a la política monetaria. Las **reservas internacionales (USD 14,200 "
        "millones)** ofrecen un colchón externo cómodo frente a shocks de balanza de "
        "pagos, y el **tipo de cambio (RD$ 59.8/US$)** sigue una depreciación gradual y "
        "predecible. El contrapunto es fiscal: un **déficit de -3.1% del PIB** que, sin "
        "ser alarmante, exige disciplina para no erosionar la sostenibilidad de la deuda. "
        "La lectura de conjunto: una economía en expansión con anclas nominales bajo "
        "control y un frente fiscal como principal punto de atención."
    ),
    "macro_trend": (
        "La trayectoria macroeconómica de la República Dominicana describe una economía "
        "en fase expansiva con fundamentos sólidos. El crecimiento de 5.1% no es un "
        "repunte puntual sino la continuación de una de las tasas más altas y consistentes "
        "de América Latina, apoyada en una base diversificada —turismo, zonas francas, "
        "remesas y construcción— que reduce la dependencia de un solo motor. La inflación "
        "controlada en 3.8% y unas reservas robustas configuran un marco de estabilidad "
        "nominal que sostiene la confianza de inversión. El vector a vigilar es la "
        "consolidación fiscal: el déficit de -3.1% del PIB es manejable en un contexto de "
        "crecimiento, pero su trayectoria determina el espacio de política ante un "
        "eventual giro del ciclo. Para un inversionista, RD ofrece una combinación poco "
        "común —alto crecimiento con estabilidad macro— que premia la exposición de "
        "mediano plazo."
    ),
    "risk_assessment": (
        "El riesgo macro-político de la República Dominicana se evalúa como **moderado** "
        "(IRMP 38.3, escala donde un valor más alto indica MENOR riesgo). El índice "
        "integra gobernanza, estabilidad institucional, sostenibilidad fiscal y exposición "
        "externa, y ubica a RD en una franja intermedia que combina fortalezas claras con "
        "vulnerabilidades acotadas. Del lado positivo: estabilidad política, continuidad "
        "institucional y un historial de cumplimiento de obligaciones que anclan la "
        "percepción de riesgo soberano. Del lado de atención: la dependencia de ingresos "
        "externos —turismo, remesas, inversión extranjera— expone a la economía a shocks "
        "globales, y el frente fiscal limita el margen de maniobra contracíclico. Ninguno "
        "configura un riesgo de cola elevado; definen un perfil medio, gestionable, "
        "coherente con una economía emergente en consolidación."
    ),
    "recommendation": (
        "Para un comité de inversión o una contraparte con exposición a la República "
        "Dominicana, la recomendación es de **exposición constructiva con cobertura "
        "selectiva**. El perfil de alto crecimiento y estabilidad nominal justifica "
        "posiciones de mediano plazo; el riesgo no está en los fundamentos sino en la "
        "sensibilidad externa y fiscal. La palanca de mayor retorno sobre la resiliencia "
        "del país es la **consolidación fiscal**: un sendero creíble de reducción del "
        "déficit ampliaría el espacio de política y mejoraría el perfil soberano de forma "
        "estructural. Conviene dimensionar la exposición monitoreando dos indicadores "
        "adelantados: la trayectoria del déficit y la evolución de las reservas frente a "
        "un eventual endurecimiento de las condiciones financieras globales. RD es un "
        "crédito de mejora gradual, no de ruptura."
    ),
}


def macro_manifest() -> SectorProductManifest:
    return SectorProductManifest(
        sector_key=SECTOR_KEY, display_name="SDQ Macro & Country Risk", levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=("macro_pulse",), narrative_templates=("macro_snapshot",),
                audience="mercado / abierto", cadence="periodic",
                watermark="Vista abierta · SDQMIP", price_band="abierto"),
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.named_entity,
                sections=("macro_trend",), narrative_templates=("macro_trend",),
                audience="cliente / comité", cadence="recurring", price_band="suscripción"),
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=("macro_trend", "risk_assessment", "recommendation", "limitations"),
                narrative_templates=("macro_trend", "risk_assessment", "recommendation"),
                audience="comité / contraparte", cadence="on_demand", price_band="on-demand"),
        })


def _macro_factors(db: Session) -> List[Dict]:
    """Factores macro con dato (vía el getter público de macro_monitor).

    En un SAVEPOINT (``begin_nested``): si la lectura falla (p.ej. tabla ausente, o
    transacción abortada en Postgres) se revierte SOLO el savepoint, sin tumbar la
    transacción externa (el recompute escribe en la misma sesión)."""
    try:
        with db.begin_nested():
            from modules.macro_monitor.macro_context import build_macro_context
            ctx = build_macro_context(db)
            return [{"label": f.label, "value": f.value, "unit": f.unit,
                     "direction": f.direction, "reading": f.reading}
                    for f in (ctx.factors or []) if f.value is not None]
    except Exception as e:  # noqa: BLE001
        logger.warning("macro factors no disponibles: %s", e)
        return []


def _irmp(db: Session):
    """Snapshot IRMP de RD (vía el getter público de macro_political_risk), o None.
    En SAVEPOINT (ver ``_macro_factors``)."""
    try:
        with db.begin_nested():
            from modules.macro_political_risk import service as irmp_svc
            return irmp_svc.get_latest(db, COUNTRY_ISO)
    except Exception as e:  # noqa: BLE001
        logger.warning("IRMP no disponible: %s", e)
        return None


class MacroProduct:
    sector_key = SECTOR_KEY

    def __init__(self, db: Optional[Session] = None):
        self._db = db
        self._cache: Optional[tuple] = None  # (factors, irmp_snap) — 1 lectura por instancia

    def _require_db(self) -> Session:
        if self._db is None:
            raise RuntimeError("MacroProduct requiere una sesión de DB para esta operación.")
        return self._db

    def _signals(self) -> tuple:
        """(factores, snapshot IRMP) leídos UNA vez por instancia (evita 2-3 queries por
        ciclo de readiness)."""
        if self._cache is None:
            db = self._require_db()
            self._cache = (_macro_factors(db), _irmp(db))
        return self._cache

    def product_manifest(self) -> SectorProductManifest:
        return macro_manifest()

    # ── Señales de readiness ──
    def data_signals(self) -> DataHealth:
        factors, snap = self._signals()
        # Frescura: período del IRMP (date); cobertura: factores con dato.
        freshness = None
        if snap is not None and getattr(snap, "period_end", None):
            freshness = (date.today() - snap.period_end).days
        coverage = 1.0 if factors else (0.5 if snap is not None else 0.0)
        return DataHealth(coverage=coverage, freshness_days=freshness,
                          sources=("BCRD", "DIGEPRES", "WGI/WDI", "GDELT"),
                          detail=f"{len(factors)} factores con dato"
                                 + (f" · IRMP {snap.period_end}" if snap is not None else ""))

    def has_engine(self) -> bool:
        factors, snap = self._signals()
        return bool(factors) or snap is not None

    def validation_state(self) -> ValidationState:
        # IRMP con metodología validada (Eje 4 cerrado, Gate A-F); momentum macro operativo.
        return ValidationState(approved=True, score=0.85,
                               notes="IRMP validado (Gate A-F); momentum macro operativo.")

    # ── Snapshot ──
    def snapshot(self, tier: ProductTier, period: str,
                 scope: Optional[str] = None) -> ProductSnapshot:
        factors, snap = self._signals()
        irmp_score = float(snap.irmp_score) if snap is not None and snap.irmp_score is not None else None
        irmp_band = (snap.risk_band.value if snap is not None and snap.risk_band else None)
        per = (str(snap.period_end) if snap is not None and getattr(snap, "period_end", None) else period)
        if tier == ProductTier.pulse:
            # Nacional, sin entidades. Solo lecturas de factores agregados.
            payload = {"factors": factors, "n_factors": len(factors), "irmp_band": irmp_band}
            return ProductSnapshot(tier=tier, period=per, payload=payload, entity_name=None)
        payload = {"irmp_score": irmp_score, "irmp_band": irmp_band, "factors": factors}
        return ProductSnapshot(tier=tier, period=per, payload=payload, entity_name=COUNTRY_NAME)

    # ── Muestra sintética (datos demo ilustrativos, sin DB) ──
    def sample_snapshot(self, tier: ProductTier) -> ProductSnapshot:
        factors = [{"label": "Crecimiento del PIB", "reading": "5.1% interanual"},
                   {"label": "Inflación", "reading": "3.8%"},
                   {"label": "Reservas internacionales", "reading": "USD 14,200 MM"},
                   {"label": "Tipo de cambio", "reading": "RD$ 59.8 / US$"},
                   {"label": "Déficit fiscal", "reading": "-3.1% del PIB"}]
        if tier == ProductTier.pulse:
            payload = {"factors": factors, "n_factors": len(factors), "irmp_band": "Moderado"}
            return ProductSnapshot(tier=tier, period="2025-Q1", payload=payload, entity_name=None)
        payload = {"irmp_score": 38.3, "irmp_band": "Moderado", "factors": factors}
        return ProductSnapshot(tier=tier, period="2025-Q1", payload=payload, entity_name=COUNTRY_NAME)

    def sample_narratives(self, tier: ProductTier) -> Dict[str, str]:
        """Narrativa CURADA tier-1 de la muestra (exemplar). NO usa el motor IA."""
        sections = self.product_manifest().require_level(tier).sections
        return {sec: (_LIMITATIONS if sec == "limitations" else _SAMPLE_NARRATIVES[sec])
                for sec in sections}

    # ── Narrativas (sin DB) ──
    async def narratives(self, tier: ProductTier, snapshot: ProductSnapshot,
                         lang: str = "es") -> Dict[str, str]:
        from shared.narrative.claude_engine import narrative_engine
        sections = self.product_manifest().require_level(tier).sections
        factors = snapshot.payload.get("factors", [])
        base_ctx = {
            "pais": COUNTRY_NAME, "period": snapshot.period,
            "factores": factors, "irmp_score": snapshot.payload.get("irmp_score"),
            "irmp_band": snapshot.payload.get("irmp_band"),
        }
        # 'recommendation' NO es thin → narraría cifras por la ruta legacy SIN numeric_guard
        # (lección 2026-06-23). Se enruta por el thin del MISMO eje (risk_assessment, bajo
        # macro_political_risk) con un 'enfoque' accionable en el contexto (patrón trade),
        # nunca por un template no-thin.
        tmpl_for = {"macro_pulse": "macro_snapshot", "macro_trend": "macro_trend",
                    "risk_assessment": "risk_assessment", "recommendation": "risk_assessment"}
        # axis POR SECCIÓN: las secciones que leen el IRMP (riesgo país) usan la doctrina
        # macro_political_risk — su regla direccional es OPUESTA ("mayor IRMP = MENOR
        # riesgo"); enrutarlas por macro_monitor invertiría la lectura. La coyuntura BCRD
        # (pulse/trend) sí usa macro_monitor.
        axis_for = {"macro_pulse": "macro_monitor", "macro_trend": "macro_monitor",
                    "risk_assessment": "macro_political_risk",
                    "recommendation": "macro_political_risk"}
        out: Dict[str, str] = {}
        for section in sections:
            if section == "limitations":
                out["limitations"] = _LIMITATIONS
                continue
            ctx = dict(base_ctx)
            if section == "recommendation":
                ctx["enfoque"] = ("Cierre ACCIONABLE: prioriza la palanca de política o gestión "
                                  "de riesgo país con mayor retorno sobre la resiliencia macro, "
                                  "dado el cuadro anterior. No repitas el diagnóstico; recomienda.")
            res = await narrative_engine.generate(
                context=ctx, template=tmpl_for.get(section, "macro_trend"),
                mode="detailed" if tier == ProductTier.deep_dive else "standard",
                axis=axis_for.get(section, "macro_monitor"), audience="inversionista")
            out[section] = res.text
        return out

    # ── Render (sin DB, renderer genérico) ──
    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None) -> str:
        level = self.product_manifest().require_level(tier)
        title = {"pulse": "Pulse Macro", "insight": "Insight Macro",
                 "deep_dive": "Deep Dive Macro"}.get(tier.value, "Macro")
        display = "Sistema Macroeconómico · RD" if tier == ProductTier.pulse else COUNTRY_NAME
        # Tabla de factores (label · lectura) como contexto de datos.
        factors = snapshot.payload.get("factors", [])
        tables = []
        if factors:
            rows = [["Factor", "Lectura"]] + [[f["label"], f.get("reading") or "—"] for f in factors[:10]]
            tables.append(("Factores macro", rows))
        return render_product_pdf(
            sector_key=SECTOR_KEY, display_name=display, title=title, period=snapshot.period,
            narratives=narratives, section_titles=_SECTION_TITLES, tables=tables,
            subtitle=None, watermark=level.watermark, sample=sample, output_dir=output_dir)


register_product(SECTOR_KEY, lambda db: MacroProduct(db))
