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

import asyncio
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.products import (
    CanonicalForecast,
    CanonicalScore,
    CanonicalSeries,
    DataHealth,
    Granularity,
    ProductSnapshot,
    ProductTier,
    ForecastObservation,
    ScoreObservation,
    SectorProductManifest,
    SeriesObservation,
    SignalItem,
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
    "governance": "Gobernanza Institucional (WGI 2025)",
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
    "governance": (
        "El perfil de gobernanza institucional, medido sobre los **Worldwide Governance "
        "Indicators 2025 del Banco Mundial** (escala absoluta 0-100, donde un valor más "
        "alto indica mejor gobernanza), muestra un cuadro de fortalezas y rezagos "
        "definidos. La **estabilidad política (76.0)** es el ancla del perfil, mientras que "
        "el **control de la corrupción (42.5)** es la dimensión más rezagada y el principal "
        "foco de atención. El **estado de derecho (53.8)** se ubica en una franja "
        "intermedia, respaldado por 12 fuentes independientes, lo que confiere solidez a la "
        "lectura. La dimensión temporal es la más reveladora: el estado de derecho **mejoró "
        "de 45.6 en 2010 a 53.8 en 2024**, una trayectoria sostenida de fortalecimiento "
        "institucional a lo largo de tres lustros. El intervalo de confianza acotado en "
        "cada dimensión refleja la convergencia entre fuentes y respalda la fiabilidad del "
        "diagnóstico. En conjunto, las instituciones dominicanas se consolidan de forma "
        "gradual, con la integridad pública como la brecha pendiente."
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
                sections=("risk_assessment", "peer_position", "governance"),
                narrative_templates=("risk_assessment",),
                audience="cliente / comité", cadence="recurring", price_band="suscripción"),
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=("risk_assessment", "peer_position", "governance",
                          "recommendation", "limitations"),
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
            # `key` = clave estable del factor en la doctrina (p.ej. "policy_rate" = TPM). Se
            # propaga para que la síntesis del research pueda reconciliar variables compartidas
            # entre motores (la TPM la cita también monetary_policy) sin string-matching frágil.
            return [{"key": f.key, "label": f.label, "value": f.value, "unit": f.unit,
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

    # ── Series canónicas para la Data API (contrato OPCIONAL) ──
    def canonical_series(self) -> List[CanonicalSeries]:
        """Series normalizadas del monitor macro (BCRD y equivalentes).

        Delega en el módulo dueño del dato: el producto no consulta ``MacroSeries``, y la
        capa API no conoce ninguna serie por nombre. Una serie nueva en el ingestor
        aparece acá sola — que es la premisa de la auto-extensión."""
        from modules.macro_monitor import service as mm_svc

        return [
            CanonicalSeries(
                code=d["code"], label=d["label"], unit=d.get("unit"),
                frequency=d.get("frequency") or "unknown", source=d.get("source") or "",
                license=d.get("license"), period_first=d.get("period_first"),
                period_latest=d.get("period_latest"), n_obs=int(d.get("n_obs") or 0),
            )
            for d in mm_svc.canonical_series_for_api(self._require_db())
        ]

    def series_observations(
        self, code: str, *, start: Optional[str] = None, end: Optional[str] = None,
        as_of: Optional[str] = None, limit: Optional[int] = None,
    ) -> List[SeriesObservation]:
        """Observaciones de una serie, con linaje. ``as_of`` es point-in-time real:
        si el linaje no lo soporta, el módulo levanta ``ValueError`` (la API lo traduce
        a 422) en vez de devolver la serie de hoy con una etiqueta falsa."""
        from modules.macro_monitor import service as mm_svc

        return [
            SeriesObservation(
                period=o["period"], value=o["value"], unit=o.get("unit"),
                source=o.get("source"), published_at=o.get("published_at"),
                reason=o.get("reason"),
            )
            for o in mm_svc.series_observations_for_api(
                self._require_db(), code, start=start, end=end, as_of=as_of, limit=limit
            )
        ]

    # ── Scores y señales para la Data API (contrato OPCIONAL, Fase 2) ──
    def canonical_scores(self) -> List[CanonicalScore]:
        """El IRMP como score de panel por país. Delegado al módulo dueño del dato."""
        from modules.macro_political_risk import service as irmp_svc

        d = irmp_svc.describe_irmp_for_api(self._require_db())
        return [CanonicalScore(
            code=d["code"], label=d["label"], subject_kind=d["subject_kind"],
            direction=d["direction"], scale=d["scale"],
            method_version=d.get("method_version"), subjects=tuple(d.get("subjects", ())),
            period_latest=d.get("period_latest"), periods=tuple(d.get("periods", ())),
            n_obs=int(d.get("n_obs") or 0),
        )]

    def score_observations(
        self, code: str, *, subject: Optional[str] = None, start: Optional[str] = None,
        end: Optional[str] = None, limit: Optional[int] = None,
    ) -> List[ScoreObservation]:
        from modules.macro_political_risk import service as irmp_svc

        if code != "irmp":
            return []
        return [
            ScoreObservation(
                subject=o["subject"], period=o["period"], score=o["score"],
                band=o.get("band"), dimensions=o.get("dimensions"),
                model_version=o.get("model_version"),
            )
            for o in irmp_svc.irmp_observations_for_api(
                self._require_db(), subject=subject, start=start, end=end, limit=limit
            )
        ]

    def canonical_signals(self, limit: Optional[int] = None) -> List[SignalItem]:
        """Señales de alerta temprana del monitor macro (motor determinista)."""
        from modules.macro_monitor import service as mm_svc

        return [
            SignalItem(
                key=s["key"], label=s["label"], severity=s["severity"],
                period=s.get("period"), subject=s.get("subject"),
                detail=s.get("detail") or "",
            )
            for s in mm_svc.signals_for_api(self._require_db(), limit=limit)
        ]

    def canonical_forecasts(self) -> List[CanonicalForecast]:
        """El modelo de TPM con su track record verificable (Fase 3)."""
        from modules.macro_monitor.tpm_modeling.ledger import describe_forecast_for_api

        d = describe_forecast_for_api(self._require_db())
        return [CanonicalForecast(
            code=d["code"], label=d["label"], target=d["target"], horizon=d["horizon"],
            classes=tuple(d.get("classes", ())), model_version=d.get("model_version"),
            n_scored=int(d.get("n_scored") or 0), hit_rate=d.get("hit_rate"),
            brier=d.get("brier"), baseline=d.get("baseline"), note=d.get("note", ""),
        )]

    def forecast_observations(
        self, code: str, *, limit: Optional[int] = None,
    ) -> List[ForecastObservation]:
        from modules.macro_monitor.tpm_modeling.ledger import forecast_observations_for_api

        if code != "tpm":
            return []
        return [
            ForecastObservation(
                as_of=o["as_of"], status=o["status"], predicted=o.get("predicted"),
                probabilities=o.get("probabilities"), implied_level=o.get("implied_level"),
                realized=o.get("realized"), realized_level=o.get("realized_level"),
                realized_date=o.get("realized_date"), correct=o.get("correct"),
                brier=o.get("brier"), level_abs_error=o.get("level_abs_error"),
                model_version=o.get("model_version"),
            )
            for o in forecast_observations_for_api(self._require_db(), limit=limit)
        ]

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
        from shared.indices.panel import annotate_panel_position
        try:
            with db.begin_nested():
                panel = irmp_svc.get_panel(db, period_end)
        except Exception as e:  # noqa: BLE001
            logger.warning("Panel IRMP no disponible: %s", e)
            return {}
        scored = [s for s in panel if s.irmp_score is not None]
        # E2E-F4: un panel de <2 países no informa posición relativa (evita el falso
        # "rank 1 de 1" cuando el período del sujeto no tiene peers persistidos).
        if len(scored) < 2:
            return {}
        rank = next((i + 1 for i, s in enumerate(scored)
                     if s.country and s.country.iso_code == iso), None)
        vals = [s.irmp_score for s in scored]
        mean = round(sum(vals) / len(vals), 2)
        # E2E-SYS1: percentil dentro del panel (100 = tope; mayor IRMP = menor riesgo).
        subject = next((s.irmp_score for s in scored
                        if s.country and s.country.iso_code == iso), None)
        pos = annotate_panel_position(subject, vals)
        return {"rank": rank, "n_countries": len(scored),
                "percentile": (pos["percentile"] if pos else None),
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
            raise ValueError("Selecciona un país del panel para el Insight/Deep Dive de Macro.")
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
            # E2E-SYS2/F2: trayectoria multi-período. El histórico persistido ya existía
            # (IRMPSnapshot por país+período) pero el reporte solo leía UN corte. Serie
            # cronológica AS-OF el período del reporte (no muestra períodos futuros).
            payload["trajectory"] = self._trajectory(db, iso, snap.period_end)
            # Fase A (WGI 2025): perfil de gobernanza REAL — escala absoluta 0-100 con
            # intervalo de confianza, número de fuentes y trayectoria 1996-2024 por
            # dimensión. Dato de fuente, no rúbrica. En un SAVEPOINT: si la lectura
            # falla (tabla ausente, tx abortada) se revierte solo el savepoint y el
            # snapshot sale sin la sección, nunca roto.
            try:
                with db.begin_nested():
                    gov = irmp_svc.get_governance_profile(db, iso, str(snap.period_end.year))
            except Exception as e:  # noqa: BLE001
                logger.warning("Perfil de gobernanza no disponible: %s", e)
                gov = {}
            if gov.get("dimensions"):
                payload["governance"] = gov
        return ProductSnapshot(tier=tier, period=str(snap.period_end),
                               payload=payload, entity_name=country_name)

    # ── Trayectoria del IRMP del país (as-of el período) ──
    def _trajectory(self, db: Session, iso: str, period_end) -> Dict[str, Any]:
        """Serie cronológica del IRMP del país hasta *period_end* + delta punta a punta.
        ``{}`` si hay menos de 2 cortes (una sola foto no es trayectoria)."""
        from modules.macro_political_risk import service as irmp_svc
        try:
            with db.begin_nested():
                hist = irmp_svc.get_history(db, iso)
        except Exception as e:  # noqa: BLE001
            logger.warning("Historia IRMP no disponible: %s", e)
            return {}
        rows = [h for h in hist if h.period_end <= period_end and h.irmp_score is not None]
        if len(rows) < 2:
            return {}
        rows.sort(key=lambda h: h.period_end)  # cronológico (antiguo → reciente)
        series = [{"period": str(h.period_end), "irmp_score": h.irmp_score,
                   "risk_band": (h.risk_band.value if h.risk_band else None)} for h in rows]
        return {"series": series, "n_periods": len(series),
                "delta": round(series[-1]["irmp_score"] - series[0]["irmp_score"], 2)}

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
        # Muestra de gobernanza (WGI 2025) — cifras ilustrativas coherentes con RD real.
        payload["governance"] = {
            "country_code": COUNTRY_ISO, "period": "2024",
            "source": "WGI 2025 (World Bank, escala absoluta 0-100)",
            "dimensions": {
                "wgi_political_stability": {
                    "label": "Estabilidad política", "score": 76.0, "ci_lo": 71.2,
                    "ci_hi": 80.8, "n_sources": 9,
                    "trajectory": [{"year": "2010", "score": 70.1},
                                   {"year": "2024", "score": 76.0}]},
                "wgi_rule_of_law": {
                    "label": "Estado de derecho", "score": 53.8, "ci_lo": 49.5,
                    "ci_hi": 58.2, "n_sources": 12,
                    "trajectory": [{"year": "2010", "score": 45.6},
                                   {"year": "2024", "score": 53.8}]},
                "wgi_control_corruption": {
                    "label": "Control de la corrupción", "score": 42.5, "ci_lo": 37.9,
                    "ci_hi": 47.1, "n_sources": 10,
                    "trajectory": [{"year": "2010", "score": 40.2},
                                   {"year": "2024", "score": 42.5}]},
            },
        }
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
        # E2E-SYS2/F2: trayectoria precalculada disponible para todas las secciones (serie
        # + delta punta a punta). numeric_guard admite estas cifras porque están guardadas.
        trajectory = snapshot.payload.get("trajectory") or {}
        if trajectory:
            base_ctx["trayectoria"] = trajectory
        out: Dict[str, str] = {}
        pending: List = []   # (section, ctx) → se generan en paralelo (una llamada IA/sección)
        for section in sections:
            if section == "limitations":
                out["limitations"] = _LIMITATIONS
                continue
            ctx = dict(base_ctx)
            if section == "risk_assessment" and trajectory:
                ctx["enfoque"] = ("Incorporá la TRAYECTORIA del IRMP: usá la serie y el "
                                  "delta precalculado (punta a punta) para decir si el "
                                  "riesgo del país MEJORÓ o se DETERIORÓ en el tiempo y "
                                  "qué tan sostenido es; recordá mayor IRMP = menor riesgo. "
                                  "No inventes cifras: solo las de la serie guardada.")
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
            elif section == "governance":
                gov = snapshot.payload.get("governance") or {}
                gdims = gov.get("dimensions") or {}
                # Pre-digerir cifras EXACTAS (score, IC, n_fuentes, delta de trayectoria)
                # para que el modelo las cite sin derivarlas (regla del thin/numeric_guard).
                resumen = []
                for g in gdims.values():
                    traj = g.get("trajectory") or []
                    delta = (round(traj[-1]["score"] - traj[0]["score"], 1)
                             if len(traj) >= 2 and traj[0].get("score") is not None
                             and traj[-1].get("score") is not None else None)
                    resumen.append({
                        "dimension": g["label"], "score": g.get("score"),
                        "ic_90": [g.get("ci_lo"), g.get("ci_hi")],
                        "n_fuentes": g.get("n_sources"),
                        "delta_trayectoria": delta,
                        "desde": traj[0]["year"] if traj else None,
                        "hasta": traj[-1]["year"] if traj else None,
                    })
                ctx["gobernanza"] = {"fuente": gov.get("source"), "dimensiones": resumen}
                ctx["enfoque"] = (
                    "Gobernanza institucional sobre dato de fuente (WGI 2025, escala "
                    "absoluta 0-100, mayor = mejor). Narra: (a) el perfil por dimensión "
                    "citando score + intervalo de confianza 90% + n° de fuentes que lo "
                    "respaldan (señal de solidez del dato); (b) la TRAYECTORIA de largo "
                    "plazo usando delta_trayectoria (desde→hasta) — ¿las instituciones se "
                    "FORTALECIERON o DETERIORARON?; (c) qué dimensión es el ancla y cuál el "
                    "rezago. Solo cifras del contexto; no inventes.")
            elif section == "recommendation":
                ctx["enfoque"] = ("Cierre ACCIONABLE: prioriza la palanca de política o gestión "
                                  "de riesgo país con mayor retorno sobre la resiliencia macro, "
                                  "dado el cuadro anterior. No repitas el diagnóstico; recomienda.")
            pending.append((section, ctx))

        # TODAS las secciones con cifras narran por el thin del eje (risk_assessment, axis
        # macro_political_risk) → numeric_guard. El "foco" va por contexto, nunca por un
        # template homónimo no-thin (caería a la ruta legacy sin guard). Se generan en
        # PARALELO (asyncio.gather): antes era secuencial (~15s × 5-6 secciones ≈ 90s en el
        # deep dive); en paralelo tarda ~la sección más lenta. Baja mucho la descarga del PDF.
        mode = "detailed" if tier == ProductTier.deep_dive else "standard"

        async def _gen(section: str, ctx: Dict) -> tuple:
            res = await narrative_engine.generate(
                context=ctx, template="risk_assessment", mode=mode,
                axis="macro_political_risk", audience="inversionista")
            return section, res.text

        for section, text in await asyncio.gather(*(_gen(s, c) for s, c in pending)):
            out[section] = text
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
            # E2E-SYS2/F2: trayectoria del IRMP (tabla + gráfico) cuando hay ≥2 cortes.
            series = (snapshot.payload.get("trajectory") or {}).get("series") or []
            if len(series) >= 2:
                trows = [["Período", "IRMP", "Banda"]] + [
                    [p["period"],
                     (f"{p['irmp_score']:.1f}" if p.get("irmp_score") is not None else "—"),
                     p.get("risk_band") or "—"] for p in series]
                tables.append(("Trayectoria del IRMP", trows))
                charts.append({"title": "Trayectoria del IRMP (mayor = menor riesgo)",
                               "items": [(p["period"], p.get("irmp_score")) for p in series]})
            # Fase A (WGI 2025): perfil de gobernanza con escala absoluta, intervalo de
            # confianza y n° de fuentes por dimensión (dato de fuente, no rúbrica).
            gov = snapshot.payload.get("governance") or {}
            gdims = gov.get("dimensions") or {}
            if gdims:
                grows = [["Dimensión", "Score (0-100)", "IC 90%", "Fuentes"]]
                for g in gdims.values():
                    ci = ("—" if g.get("ci_lo") is None or g.get("ci_hi") is None
                          else f"{g['ci_lo']:.1f}–{g['ci_hi']:.1f}")
                    grows.append([
                        g["label"],
                        (f"{g['score']:.1f}" if g.get("score") is not None else "—"),
                        ci,
                        str(g.get("n_sources") or "—"),
                    ])
                tables.append(("Gobernanza · WGI 2025 (mayor = mejor)", grows))
                charts.append({
                    "title": "Gobernanza por dimensión · WGI 2025 (0-100)",
                    "items": [(g["label"], g.get("score")) for g in gdims.values()],
                })
                # Trayectoria de la dimensión insignia (Estado de derecho) — cuenta la
                # historia real de fortalecimiento/deterioro institucional de 1996-2024.
                flagship = gdims.get("wgi_rule_of_law")
                traj = (flagship or {}).get("trajectory") or []
                if len(traj) >= 2:
                    charts.append({
                        "title": "Estado de derecho · trayectoria WGI (0-100)",
                        "items": [(t["year"], t.get("score")) for t in traj],
                    })

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
