"""Macro & Country Risk como SectorProduct — sector #2 (valida la receta de onboarding).

Macro abarca DOS módulos (``macro_monitor`` + ``macro_political_risk``); por la
independencia de módulos (no se importan entre sí), su producto se ensambla a nivel
**app** vía los **getters públicos** de cada módulo (mismo patrón que ``app/market_brief``),
y se auto-registra en ``shared.products``. NO modifica el framework: solo implementa el
``Protocol SectorProduct`` + su manifiesto + sus señales (la prueba de la receta).

Naturaleza MULTIPAÍS (re-encuadrado 2026-06-26). El producto tiene DOS lecturas:
  - **Pulse** = coyuntura macroeconómica NACIONAL (RD, series BCRD); agregado de sistema
    sin entidades (el sensor de anonimización pasa trivialmente con roster vacío).
  - **Insight / Deep Dive** = RIESGO-PAÍS por el país elegido del panel IRMP (score,
    banda, dimensiones y posición relativa). El nivel nombrado es el PAÍS del panel
    (no RD prestado): su lectura sale del ``IRMPSnapshot`` de ESE país, con su
    ``breakdown`` dimensional, vía ``irmp_ai_context`` (regla direccional: mayor IRMP =
    MENOR riesgo). Las series de coyuntura BCRD son RD-only y quedan SOLO en el Pulse.
"""
from __future__ import annotations

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
)
from shared.products.render import render_product_pdf

logger = logging.getLogger("sdq.products.macro")

SECTOR_KEY = "macro"
COUNTRY_NAME = "República Dominicana"
COUNTRY_ISO = "DO"

# Etiquetas en español de las dimensiones del IRMP (réplica local; ai_context las
# tiene private). Para la tabla del reporte de riesgo-país.
_DIM_LABELS = {
    "macro": "Macroeconómica",
    "external": "Externa",
    "political": "Político-institucional",
    "regulatory": "Regulatoria",
    "events": "Eventos",
}

# Región (display, ES) → slug canónico i18n del catálogo (compartido con ESG). El front
# resuelve ``platform.catalog.region.<slug>`` en ES/EN/FR.
_REGION_SLUG = {
    "Caribe": "caribe",
    "Centroamérica": "centroamerica",
    "Centroamerica": "centroamerica",
    "Sudamérica": "sudamerica",
    "Sudamerica": "sudamerica",
    "Norteamérica": "norteamerica",
    "Norteamerica": "norteamerica",
}


def _region_slug(region: Optional[str]) -> str:
    return _REGION_SLUG.get((region or "").strip(), "otros")


_SECTION_TITLES = {
    "macro_pulse": "Pulso Macroeconómico",
    "risk_assessment": "Evaluación de Riesgo-País (IRMP)",
    "peer_position": "Posición en el Panel Regional",
    "recommendation": "Lectura para Decisión",
    "limitations": "Limitaciones",
}
_LIMITATIONS = (
    "La lectura de riesgo-país se basa en el Índice de Riesgo Macro-Político (IRMP, fuentes "
    "WGI/WDI/IMF) del país a la fecha de corte; la coyuntura macroeconómica del Pulse usa "
    "las series oficiales publicadas (BCRD, DIGEPRES/Crédito Público) y es nacional (RD). "
    "El panel regional es un conjunto de pares y no anticipa choques no publicados ni "
    "decisiones de política posteriores al período."
)

# Narrativa CURADA tier-1 de la muestra (exemplar), riesgo-país de RD. Coherente con
# SAMPLE_* (IRMP 38.3 «Moderado», posición 3 de 5 en el panel, media 50.7).
# IRMP: mayor = MENOR riesgo (no invertir la lectura). Sin cursivas de un asterisco.
_SAMPLE_NARRATIVES = {
    "macro_pulse": (
        "La coyuntura macroeconómica dominicana cierra el período con señales ordenadas. "
        "El **crecimiento del PIB de 5.1% interanual** ubica a la República Dominicana "
        "entre las economías más dinámicas de la región, sostenido por turismo, remesas e "
        "inversión. La **inflación de 3.8%** se sitúa dentro del rango meta del Banco "
        "Central, lo que preserva margen para la política monetaria. Las **reservas "
        "internacionales (USD 14,200 millones)** ofrecen un colchón externo holgado frente "
        "a choques de balanza de pagos, y el **tipo de cambio (RD$ 59.8/US$)** registra una "
        "depreciación gradual y predecible. El contrapunto se ubica en el plano fiscal. El "
        "**déficit de -3.1% del PIB**, sin ser alarmante, exige disciplina para no "
        "erosionar la sostenibilidad de la deuda. En conjunto, la lectura corresponde a "
        "una economía en expansión, con anclas nominales bajo control y el frente fiscal "
        "como principal punto de atención."
    ),
    "risk_assessment": (
        "El riesgo macro-político de la República Dominicana se evalúa como **moderado** "
        "(IRMP 38.3, en una escala donde un valor más alto indica un MENOR nivel de "
        "riesgo). El índice integra gobernanza, estabilidad institucional, sostenibilidad "
        "fiscal y exposición externa, y ubica al país en una franja intermedia que combina "
        "fortalezas definidas con vulnerabilidades acotadas. Entre los factores favorables "
        "se cuentan la estabilidad política, la continuidad institucional y un historial "
        "de cumplimiento de obligaciones que ancla la percepción de riesgo soberano. Entre "
        "los factores de atención, la dependencia de ingresos externos —turismo, remesas e "
        "inversión extranjera— expone a la economía a choques globales, y el frente fiscal "
        "limita el margen de maniobra contracíclico. Ninguno configura un riesgo de cola "
        "elevado. En conjunto definen un perfil medio y gestionable, coherente con una "
        "economía emergente en consolidación."
    ),
    "peer_position": (
        "En el panel regional de referencia, la República Dominicana se ubica en una "
        "**posición intermedia (3.ª de 5)**, por encima de pares con mayor fragilidad "
        "institucional y por debajo de las economías de la región con marcos de gobernanza "
        "más consolidados. La lectura relativa resulta tan informativa como el nivel "
        "absoluto. El diferencial frente al líder del panel se explica, principalmente, "
        "por la dimensión político-institucional y por el espacio fiscal, y no por la "
        "trayectoria de crecimiento, en la que el país aventaja a la mayoría de sus pares. "
        "La distancia respecto de la media del panel es acotada y, en buena medida, "
        "gestionable por la vía de la política pública. Esa distinción separa lo "
        "estructural de lo atribuible a la gestión, y señala que la convergencia hacia el "
        "cuartil superior regional constituye un objetivo alcanzable."
    ),
    "recommendation": (
        "Para un comité de inversión o una contraparte con exposición a la República "
        "Dominicana, la recomendación corresponde a una **exposición constructiva con "
        "cobertura selectiva**. El perfil de alto crecimiento y estabilidad nominal "
        "justifica posiciones de mediano plazo. El riesgo no reside en los fundamentos, "
        "sino en la sensibilidad externa y fiscal. La principal palanca sobre la "
        "resiliencia del país es la **consolidación fiscal**. Un sendero creíble de "
        "reducción del déficit ampliaría el espacio de política y mejoraría el perfil "
        "soberano de forma estructural. Se recomienda dimensionar la exposición con base "
        "en el monitoreo de dos indicadores adelantados, la trayectoria del déficit y la "
        "evolución de las reservas, ante un eventual endurecimiento de las condiciones "
        "financieras globales. El país configura un crédito de mejora gradual, no de "
        "ruptura."
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
                sections=("risk_assessment", "peer_position"),
                narrative_templates=("risk_assessment",),
                audience="cliente / comité", cadence="recurring", price_band="suscripción"),
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=("risk_assessment", "peer_position", "recommendation", "limitations"),
                narrative_templates=("risk_assessment",),
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
    En SAVEPOINT (ver ``_macro_factors``). Alimenta SOLO las señales de readiness."""
    try:
        with db.begin_nested():
            from modules.macro_political_risk import service as irmp_svc
            return irmp_svc.get_latest(db, COUNTRY_ISO)
    except Exception as e:  # noqa: BLE001
        logger.warning("IRMP no disponible: %s", e)
        return None


def _parse_period(period: str) -> Optional[date]:
    """Período del topbar ('YYYY-MM-DD') → date, o None si no es resoluble."""
    try:
        return date.fromisoformat((period or "").strip()) if period else None
    except (ValueError, TypeError):
        return None


def _snapshot_result(snap) -> Dict[str, Any]:
    """``IRMPSnapshot`` persistido → dict con el shape de ``run_irmp`` (lo que espera
    ``irmp_ai_context``). El ``breakdown`` ya ES ``result['dimensions']``; no se
    re-corre el motor."""
    return {
        "country_code": (snap.country.iso_code if snap.country else None),
        "irmp_score": snap.irmp_score,
        "risk_band": (snap.risk_band.value if snap.risk_band else None),
        "dimensions": snap.breakdown or {},
        "peer_set_size": snap.peer_set_size,
    }


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

    def available_periods(self) -> List[str]:
        from modules.macro_political_risk.models.models import IRMPSnapshot
        return distinct_periods(self._require_db(), IRMPSnapshot.period_end)

    def validation_state(self) -> ValidationState:
        # IRMP con metodología validada (Eje 4 cerrado, Gate A-F); momentum macro operativo.
        return ValidationState(approved=True, score=0.85,
                               notes="IRMP validado (Gate A-F); momentum macro operativo.")

    # ── Universo de países del panel (alimenta el selector del catálogo) ──
    def scope_options(self) -> List[Dict[str, str]]:
        """Países elegibles para el Insight/Deep Dive de riesgo-país: ``value`` = ISO
        (lo que ``snapshot(scope=…)`` resuelve), ``label`` = nombre, ``group`` = slug de
        región. Solo países CON un ``IRMPSnapshot`` persistido (ofrecer únicamente los que
        producen reporte evita opciones que darían 422). Requiere DB."""
        from modules.macro_political_risk import service as irmp_svc
        db = self._require_db()
        return [{"value": c.iso_code, "label": c.name, "group": _region_slug(c.region)}
                for c in irmp_svc.get_scored_countries(db)]

    def scope_kind(self) -> str:
        return "country"

    # ── Posición relativa en el panel del período ──
    def _peer_position(self, db: Session, iso: str, period_end) -> Dict[str, Any]:
        """Rank del país y distribución del panel para su período, en SAVEPOINT."""
        from modules.macro_political_risk import service as irmp_svc
        try:
            with db.begin_nested():
                panel = irmp_svc.get_panel(db, period_end)
        except Exception as e:  # noqa: BLE001
            logger.warning("Panel IRMP no disponible: %s", e)
            return {}
        scored = [s for s in panel if s.irmp_score is not None]
        if not scored:
            return {}
        rank = next((i + 1 for i, s in enumerate(scored)
                     if s.country and s.country.iso_code == iso), None)
        vals = [s.irmp_score for s in scored]
        mean = round(sum(vals) / len(vals), 2)
        return {"rank": rank, "n_countries": len(scored),
                "distribution": {"mean": mean, "max": max(vals), "min": min(vals)}}

    # ── Snapshot ──
    def snapshot(self, tier: ProductTier, period: str,
                 scope: Optional[str] = None) -> ProductSnapshot:
        db = self._require_db()
        if tier == ProductTier.pulse:
            # Coyuntura NACIONAL (RD), sin entidades. Series BCRD agregadas.
            factors, snap = self._signals()
            per = (str(snap.period_end) if snap is not None
                   and getattr(snap, "period_end", None) else period)
            irmp_band = (snap.risk_band.value if snap is not None and snap.risk_band else None)
            payload = {"factors": factors, "n_factors": len(factors), "irmp_band": irmp_band}
            return ProductSnapshot(tier=tier, period=per, payload=payload, entity_name=None)

        # Niveles nombrados: riesgo-país del PAÍS elegido (no RD prestado).
        iso = (scope or "").strip().upper()
        if not iso:
            raise ValueError("Seleccioná un país del panel para el Insight/Deep Dive de Macro.")
        from modules.macro_political_risk import service as irmp_svc
        snap = irmp_svc.get_snapshot(db, iso, _parse_period(period))
        if snap is None:
            raise ValueError(f"No hay IRMP persistido para el país '{iso}'.")
        result = _snapshot_result(snap)
        country_name = (snap.country.name if snap.country else iso)
        payload: Dict[str, Any] = {
            "country_code": iso, "irmp_score": result["irmp_score"],
            "irmp_band": result["risk_band"], "dimensions": result["dimensions"],
            "peer_set_size": result["peer_set_size"],
        }
        # Posición en el panel del período. La sección ``peer_position`` está declarada
        # en el manifest tanto para Insight como para Deep Dive (macro_manifest), así que
        # se puebla para ambos: antes solo se poblaba en deep_dive y el Insight renderizaba
        # la sección "Posición en el Panel" hueca aunque el panel del período existiera.
        if tier in (ProductTier.insight, ProductTier.deep_dive):
            payload["peer_position"] = self._peer_position(db, iso, snap.period_end)
        return ProductSnapshot(tier=tier, period=str(snap.period_end),
                               payload=payload, entity_name=country_name)

    # ── Muestra sintética (datos demo ilustrativos, sin DB) ──
    def sample_snapshot(self, tier: ProductTier) -> ProductSnapshot:
        if tier == ProductTier.pulse:
            factors = [{"label": "Crecimiento del PIB", "reading": "5.1% interanual"},
                       {"label": "Inflación", "reading": "3.8%"},
                       {"label": "Reservas internacionales", "reading": "USD 14,200 MM"},
                       {"label": "Tipo de cambio", "reading": "RD$ 59.8 / US$"},
                       {"label": "Déficit fiscal", "reading": "-3.1% del PIB"}]
            payload = {"factors": factors, "n_factors": len(factors), "irmp_band": "Moderado"}
            return ProductSnapshot(tier=tier, period="2025-Q1", payload=payload, entity_name=None)
        dims = {"political": {"score": 32.0, "weight": 0.25, "contribution": 8.0},
                "regulatory": {"score": 36.0, "weight": 0.20, "contribution": 7.2},
                "macro": {"score": 52.0, "weight": 0.25, "contribution": 13.0},
                "external": {"score": 40.0, "weight": 0.20, "contribution": 8.0},
                "events": {"score": 30.0, "weight": 0.10, "contribution": 3.0}}
        payload = {"country_code": COUNTRY_ISO, "irmp_score": 38.3, "irmp_band": "Moderado",
                   "dimensions": dims, "peer_set_size": 5}
        if tier == ProductTier.deep_dive:
            payload["peer_position"] = {"rank": 3, "n_countries": 5,
                                        "distribution": {"mean": 50.7, "max": 64.9, "min": 36.3}}
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

        if tier == ProductTier.pulse:
            # Coyuntura BCRD nacional (RD) — eje macro_monitor.
            factors = snapshot.payload.get("factors", [])
            ctx = {"pais": COUNTRY_NAME, "period": snapshot.period, "factores": factors,
                   "irmp_band": snapshot.payload.get("irmp_band")}
            res = await narrative_engine.generate(
                context=ctx, template="macro_snapshot", mode="standard",
                axis="macro_monitor", audience="inversionista")
            return {"macro_pulse": res.text}

        # Niveles nombrados: riesgo-país (IRMP por país) — eje macro_political_risk.
        # Contexto compacto pre-digerido (dimensiones, fuerte/débil, cifras derivadas).
        from modules.macro_political_risk.ai_context import irmp_ai_context
        result = {
            "country_code": snapshot.payload.get("country_code"),
            "irmp_score": snapshot.payload.get("irmp_score"),
            "risk_band": snapshot.payload.get("irmp_band"),
            "dimensions": snapshot.payload.get("dimensions") or {},
            "peer_set_size": snapshot.payload.get("peer_set_size"),
        }
        base_ctx = irmp_ai_context(result, country_name=snapshot.entity_name)
        out: Dict[str, str] = {}
        for section in sections:
            if section == "limitations":
                out["limitations"] = _LIMITATIONS
                continue
            ctx = dict(base_ctx)
            if section == "peer_position":
                pos = dict(snapshot.payload.get("peer_position") or {})
                # Precalcular las distancias (media/líder) para que el modelo cite cifras
                # EXACTAS guardadas, no las derive (regla del thin: número solo si está
                # precalculado). El score del país es la referencia.
                dist = pos.get("distribution") or {}
                score = snapshot.payload.get("irmp_score")
                if score is not None and dist.get("mean") is not None:
                    pos["delta_vs_media"] = round(score - dist["mean"], 2)
                if score is not None and dist.get("max") is not None:
                    pos["delta_vs_lider"] = round(score - dist["max"], 2)
                ctx["posicion_panel"] = pos
                ctx["enfoque"] = ("Posición RELATIVA del país en el panel regional: usa el rank "
                                  "y las distancias precalculadas (delta_vs_media, delta_vs_lider; "
                                  "recordá: mayor IRMP = menor riesgo) para ubicarlo; qué dimensión "
                                  "explica el diferencial frente al líder. No repitas el score; ubícalo.")
            elif section == "recommendation":
                ctx["enfoque"] = ("Cierre ACCIONABLE: prioriza la palanca de política o gestión "
                                  "de riesgo país con mayor retorno sobre la resiliencia macro, "
                                  "dado el cuadro anterior. No repitas el diagnóstico; recomienda.")
            # TODAS las secciones con cifras narran por el thin del eje (risk_assessment,
            # axis macro_political_risk) → numeric_guard. El "foco" va por contexto, nunca
            # por un template homónimo no-thin (caería a la ruta legacy sin guard).
            res = await narrative_engine.generate(
                context=ctx, template="risk_assessment",
                mode="detailed" if tier == ProductTier.deep_dive else "standard",
                axis="macro_political_risk", audience="inversionista")
            out[section] = res.text
        return out

    # ── Render (sin DB, renderer genérico) ──
    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None, fmt: str = "pdf") -> str:
        level = self.product_manifest().require_level(tier)
        title = {"pulse": "Pulse Macro", "insight": "Insight Riesgo-País",
                 "deep_dive": "Deep Dive Riesgo-País"}.get(tier.value, "Macro")
        tables: List = []
        charts: List = []
        headline: Optional[str] = None
        if tier == ProductTier.pulse:
            display = "Sistema Macroeconómico · RD"
            # Tabla de factores BCRD (label · lectura) como contexto de datos.
            factors = snapshot.payload.get("factors", [])
            if factors:
                rows = [["Factor", "Lectura"]] + [[f["label"], f.get("reading") or "—"]
                                                  for f in factors[:10]]
                tables.append(("Factores macro (RD)", rows))
            band = snapshot.payload.get("irmp_band")
            if band:
                headline = f"Coyuntura macroeconómica · riesgo país {band}"
        else:
            display = snapshot.entity_name or COUNTRY_NAME
            # Tabla + gráfico de dimensiones del IRMP (label · score) del país.
            dims = snapshot.payload.get("dimensions") or {}
            if dims:
                rows = [["Dimensión", "Score"]] + [
                    [_DIM_LABELS.get(k, k),
                     (f"{d.get('score'):.1f}" if isinstance(d, dict) and d.get("score") is not None else "—")]
                    for k, d in dims.items()]
                tables.append(("Dimensiones del IRMP", rows))
                items = [(_DIM_LABELS.get(k, k),
                          d.get("score") if isinstance(d, dict) else None) for k, d in dims.items()]
                charts.append({"title": "Dimensiones del IRMP (score 0-100; mayor = menor riesgo)",
                               "items": items})
            sc = snapshot.payload.get("irmp_score")
            band = snapshot.payload.get("irmp_band")
            if isinstance(sc, (int, float)):
                headline = f"IRMP {sc:.1f}" + (f" · {band}" if band else "")
        return render_product_pdf(
            sector_key=SECTOR_KEY, display_name=display, title=title, period=snapshot.period,
            narratives=narratives, section_titles=_SECTION_TITLES, tables=tables,
            charts=charts, headline=headline, subtitle=None, watermark=level.watermark,
            sample=sample, output_dir=output_dir, fmt=fmt)


register_product(SECTOR_KEY, lambda db: MacroProduct(db))
