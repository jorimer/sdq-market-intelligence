"""ESG & Climate (IRC) como ``SectorProduct`` — sector #10.

Mono-módulo (como Banca/Trade): ``esg_climate`` ya tiene módulo + dato real (IRC
nacional 100% dato real: HURDAT2/NOAA + ND-GAIN + Ember) + backtest validado
(Gate E). Implementa el ``Protocol`` ``SectorProduct`` SIN tocar el framework:
manifiesto de 3 niveles + señales + producción por nivel, reusando el motor de
narrativa y los getters PÚBLICOS del propio módulo (``service``/``ai_context``).

Naturaleza NACIONAL (como Macro): el IRC es un índice por país sobre un panel
Caribe/LatAm. El foco del producto es RD (ISO3 ``DOM``); el panel es el conjunto de
pares que da sentido al ranking. El nivel nombrado es el PAÍS; el Pulse es el pulso
de resiliencia climática nacional (sin nombrar pares → ``entity_roster=()``).

Eje doctrinal ÚNICO: ``esg_climate`` + thin ``climate_outlook`` → numeric_guard.
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
    section_mode,
)
from shared.products.render import render_product_pdf
from modules.esg_climate.ai_context import climate_ai_context
from modules.esg_climate.models.models import ESGScore
from modules.esg_climate.service import (
    IRC_PANEL,
    IRC_REGION,
    get_for_entity_period,
    get_latest,
    get_scored_entities,
    get_scores,
)

logger = logging.getLogger("sdq.products.esg")

SECTOR_KEY = "esg"
COUNTRY_ISO = "DOM"
COUNTRY_NAME = "República Dominicana"
# G5 cuando el backtest no está persistido: Gate E firmado (Spearman significativo,
# monótono) → valor conservador. Si el backtest está en DB, se recalcula de su IC real.
_DOCTRINE_VALIDATION_FALLBACK = 0.75

_SECTION_TITLES = {
    "irc_pulse": "Pulso de Resiliencia Climática",
    "irc_assessment": "Evaluación de Resiliencia Climática (IRC)",
    "panel_position": "Posición en el Panel Caribe/LatAm",
    "recommendation": "Lectura para Decisión",
    "limitations": "Limitaciones",
}
_LIMITATIONS = (
    "Índice de Resiliencia Climática (IRC) sobre dato real a la fecha de corte: riesgo "
    "físico de huracán (HURDAT2/NOAA) + exposición/adaptación/gobernanza (ND-GAIN) + "
    "transición eléctrica (Ember: fósil/carbono); cuando Ember no cubre el panel, la "
    "transición cae a rúbrica declarada (G1 lo refleja). Validación direccional (Gate E, "
    "mortalidad por desastre vs IRC en panel Caribe/LatAm), no grado-Basilea. El panel "
    "es conjunto de pares; no anticipa eventos climáticos no realizados."
)
_NO_DATA = (
    "No hay IRC persistido para el período: el producto está cableado pero su cobertura "
    "(G1) es insuficiente para publicar. No se fabrican cifras."
)

# Narrativa CURADA tier-1 de la muestra (exemplar). Coherente con los datos demo
# (IRC 35.65 «Baja», riesgo físico 40, gobernanza 50, puesto 22 de 24; media del panel
# 48, máx 70). IRC bajo = MENOR resiliencia = MAYOR vulnerabilidad (lectura de riesgo).
_SAMPLE_NARRATIVES = {
    "irc_pulse": (
        "El Índice de Resiliencia Climática de la República Dominicana cierra el período "
        "en **35.65/100 —banda Baja—**, una lectura que sitúa al país en posición de "
        "vulnerabilidad relativa. A diferencia de los índices donde un valor alto es "
        "deseable, aquí el dato es una señal de alerta: RD enfrenta una exposición física "
        "elevada (huracanes, eventos extremos, riesgo costero) que su capacidad adaptativa "
        "e institucional aún no compensa del todo. En el panel de referencia Caribe/LatAm "
        "se ubica en el **puesto 22 de 24**, entre los más expuestos. La gobernanza "
        "climática (50) es el componente más maduro y la principal vía de mejora; el "
        "riesgo físico (40) es el factor estructural que pesa sobre el índice. La lectura "
        "de mercado: el clima es un riesgo material para la economía dominicana, y su "
        "gestión —adaptación, infraestructura resiliente, marco institucional— es una "
        "variable de inversión, no un asunto reputacional."
    ),
    "irc_assessment": (
        "La resiliencia climática de la República Dominicana se evalúa en **35.65/100 "
        "(banda Baja)**, un perfil que refleja la tensión entre una exposición física alta "
        "y una capacidad de respuesta en construcción. La condición de Estado insular "
        "caribeño impone una vulnerabilidad estructural —temporada ciclónica, erosión "
        "costera, estrés hídrico— que sitúa al riesgo físico (40) como el principal lastre "
        "del índice. El contrapeso es la gobernanza (50): un marco institucional climático "
        "que avanza, pero que aún no traduce intención en resiliencia medible. Para un "
        "inversionista o financiador la lectura es doble: el riesgo climático es material "
        "y debe incorporarse al costo de capital de proyectos expuestos; pero también "
        "define una agenda de inversión —adaptación, infraestructura, energía limpia— con "
        "respaldo institucional creciente. RD es un caso donde la resiliencia climática es, "
        "a la vez, el riesgo y la oportunidad."
    ),
    "panel_position": (
        "En el panel de referencia Caribe/LatAm de 24 países, la República Dominicana se "
        "ubica en el **puesto 22**, por debajo de la media del panel (48.0) y lejos del "
        "líder (70.0). La posición no es anecdótica: confirma que la vulnerabilidad "
        "climática de RD no es solo absoluta sino relativa. Varios pares de la región —con "
        "exposición física comparable— han logrado índices más altos, lo que indica que el "
        "gap es, en parte, gestionable vía política e inversión, no únicamente geográfico. "
        "La distancia a la media (≈12 puntos) cuantifica el espacio de mejora; la brecha "
        "frente al máximo (≈34 puntos) marca el techo de ambición. Para un comité, esta "
        "posición relativa es la métrica más útil: separa lo que es destino geográfico de "
        "lo que es resultado de política, y señala que converger hacia la media del panel "
        "es un objetivo alcanzable."
    ),
    "recommendation": (
        "Para un inversionista, financiador o comité con exposición a la República "
        "Dominicana, la resiliencia climática debe tratarse como un riesgo material de "
        "mediano plazo —incorporado al costo de capital de activos expuestos— y, a la vez, "
        "como una agenda de inversión con respaldo institucional. La palanca de mayor "
        "retorno sobre el índice es la **capacidad adaptativa e institucional**: a "
        "diferencia del riesgo físico, estructural, la gobernanza y la inversión en "
        "infraestructura resiliente son dimensiones donde una agenda deliberada puede "
        "cerrar la brecha frente a la media del panel. La recomendación operativa: ponderar "
        "el riesgo físico en la selección y el dimensionamiento de proyectos, y favorecer "
        "exposiciones alineadas con la agenda de adaptación y transición —energía limpia, "
        "infraestructura costera, gestión hídrica— donde el riesgo climático se convierte "
        "en tesis de inversión."
    ),
}


def esg_manifest() -> SectorProductManifest:
    return SectorProductManifest(
        sector_key=SECTOR_KEY, display_name="SDQ ESG & Climate", levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=("irc_pulse",), narrative_templates=("climate_outlook",),
                audience="mercado / abierto", cadence="periodic",
                watermark="Vista abierta · SDQMIP", price_band="abierto"),
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.named_entity,
                sections=("irc_assessment",), narrative_templates=("climate_outlook",),
                audience="cliente / comité", cadence="recurring", price_band="suscripción"),
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=("irc_assessment", "panel_position", "recommendation", "limitations"),
                # Único thin del eje (climate_outlook) en TODAS las secciones con cifras
                # → numeric_guard; el "foco" por sección va por contexto, no por template
                # no-thin (recommendation no es thin → ruta legacy sin guard).
                narrative_templates=("climate_outlook",),
                audience="comité / contraparte", cadence="on_demand", price_band="on-demand"),
        })


_UNSET = object()  # centinela "aún no leído" (distingue de None = leído y vacío)


def _latest_irc(db: Session) -> Optional[ESGScore]:
    """IRC más reciente de RD en SAVEPOINT: una lectura que falla (tabla ausente, o
    transacción abortada en Postgres) revierte SOLO el savepoint, sin tumbar el
    recompute compartido (que itera todos los sectores en una sesión)."""
    try:
        with db.begin_nested():
            return get_latest(db, COUNTRY_ISO)
    except Exception as e:  # noqa: BLE001
        logger.warning("IRC no disponible: %s", e)
        return None


def _panel_position(db: Session, period: str, iso3: str = COUNTRY_ISO) -> Dict[str, Any]:
    """Rank de *iso3* y distribución del panel para el período, en SAVEPOINT."""
    try:
        with db.begin_nested():
            rows = get_scores(db, period)
    except Exception as e:  # noqa: BLE001
        logger.warning("Panel IRC no disponible: %s", e)
        return {}
    scored = [r for r in rows if r.esg_score is not None]
    if not scored:
        return {}
    ordered = sorted(scored, key=lambda r: r.esg_score, reverse=True)
    rank = next((i + 1 for i, r in enumerate(ordered) if r.entity_key == iso3), None)
    vals = [r.esg_score for r in ordered]
    mean = round(sum(vals) / len(vals), 2)
    return {"rank": rank, "n_countries": len(ordered),
            "distribution": {"mean": mean, "max": max(vals), "min": min(vals)}}


def _backtest_spearman(db: Session) -> Optional[Dict[str, Any]]:
    """Bloque del backtest IRC persistido (Gate E), o None. SAVEPOINT."""
    import json
    from shared.settings.models import AppSetting
    try:
        with db.begin_nested():
            row = (db.query(AppSetting)
                   .filter(AppSetting.key == "esg_backtest_report").first())
        if not row:
            return None
        rep = json.loads(row.value) or {}
        return rep if rep.get("spearman") is not None else None
    except Exception as e:  # noqa: BLE001
        logger.warning("Backtest ESG no leído (uso doctrina firmada): %s", e)
        return None


def _score_dict(s: ESGScore) -> Dict[str, Any]:
    return {"entity_key": s.entity_key, "period": s.period, "esg_score": s.esg_score,
            "band": s.band, "breakdown": s.breakdown or {}}


def _live_fraction(breakdown: Dict[str, Any]) -> float:
    """Fracción de variables con fuente 'live' (vs rúbrica declarada) — cobertura real."""
    sources = (breakdown or {}).get("sources") or {}
    if not sources:
        return 1.0  # sin mapa de fuentes → el IRC se computó sobre dato real
    live = sum(1 for v in sources.values() if v == "live")
    return live / len(sources)


def _pct(share: Optional[float]) -> str:
    return "—" if share is None else f"{share:.1f}"


class ESGProduct:
    """``SectorProduct`` de ESG & Climate. ``db`` opcional: las muestras sintéticas
    usan solo ``narratives``/``render`` (sin DB)."""

    sector_key = SECTOR_KEY

    def __init__(self, db: Optional[Session] = None):
        self._db = db
        self._cache: Any = _UNSET

    def _require_db(self) -> Session:
        if self._db is None:
            raise RuntimeError("ESGProduct requiere una sesión de DB para esta operación.")
        return self._db

    def _latest(self) -> Optional[ESGScore]:
        if self._cache is _UNSET:
            self._cache = _latest_irc(self._require_db())
        return self._cache

    def product_manifest(self) -> SectorProductManifest:
        return esg_manifest()

    # ── Señales de readiness ──
    def data_signals(self) -> DataHealth:
        s = self._latest()
        if s is None:
            return DataHealth(coverage=0.0, freshness_days=None, cadence="annual",
                              sources=("ND-GAIN", "HURDAT2/NOAA", "Ember"),
                              detail="Sin IRC persistido.")
        coverage = _live_fraction(s.breakdown)
        # Frescura: fin del año de referencia ND-GAIN (period es un año, p.ej. "2023").
        # Cadencia ANUAL: ND-GAIN/Ember publican con ~1-2 años de rezago por naturaleza,
        # así que la curva trimestral los marcaría falsamente obsoletos.
        freshness = None
        try:
            freshness = (date.today() - date(int(str(s.period)[:4]), 12, 31)).days
        except (ValueError, TypeError):
            pass
        return DataHealth(coverage=coverage, freshness_days=freshness, cadence="annual",
                          sources=("ND-GAIN", "HURDAT2/NOAA", "Ember"),
                          detail=f"IRC {s.esg_score} ({s.band}) en {s.period}")

    def has_engine(self) -> bool:
        return self._latest() is not None

    def available_periods(self) -> List[str]:
        return distinct_periods(self._require_db(), ESGScore.period,
                                where=ESGScore.entity_key == COUNTRY_ISO)

    def validation_state(self) -> ValidationState:
        notes = "Gate E validado (mortalidad por desastre vs IRC, panel Caribe/LatAm)."
        score = _DOCTRINE_VALIDATION_FALLBACK
        rep = _backtest_spearman(self._require_db())
        if rep:
            rho, ci = rep.get("spearman"), rep.get("spearman_ci") or [None, None]
            # IRC: mayor resiliencia = MENOR mortalidad → Spearman negativo; significativo
            # si el IC queda enteramente bajo 0 (hi < 0).
            sig = ci[1] is not None and ci[1] < 0
            score = 0.8 if sig else 0.6
            notes = (f"Gate E: Spearman {rho} IC{ci}"
                     + (" (significativo)." if sig else " (inconcluso)."))
        return ValidationState(approved=True, score=score, notes=notes)

    # ── Universo de países del panel (alimenta el selector del catálogo) ──
    def scope_options(self) -> List[Dict[str, str]]:
        """Países elegibles para el Insight/Deep Dive de resiliencia climática: ``value`` =
        ISO3 (lo que ``snapshot(scope=…)`` resuelve), ``label`` = nombre del panel, ``group``
        = slug de región. Solo países CON un IRC persistido (ofrecer únicamente los que
        producen reporte evita opciones que darían 422). Requiere DB."""
        db = self._require_db()
        return [{"value": iso, "label": IRC_PANEL.get(iso, iso),
                 "group": IRC_REGION.get(iso, "otros")}
                for iso in get_scored_entities(db)]

    def scope_kind(self) -> str:
        return "country"

    # ── Snapshot por nivel ──
    def snapshot(self, tier: ProductTier, period: str,
                 scope: Optional[str] = None) -> ProductSnapshot:
        db = self._require_db()
        # Pulse = resiliencia climática NACIONAL (RD), sin elegir país. Niveles nombrados =
        # el país del panel elegido (no RD prestado).
        if tier == ProductTier.pulse:
            s = get_for_entity_period(db, COUNTRY_ISO, period) if period else _latest_irc(db)
            if s is None:
                return ProductSnapshot(tier=tier, period=period or "—",
                                       payload={"has_score": False}, entity_name=None,
                                       entity_roster=())
            # Nacional/agregado: NO se nombran países pares → roster vacío (sensor de
            # anonimización trivial). Solo el headline de RD + su posición.
            pos = _panel_position(db, s.period)
            payload: Dict[str, Any] = {"has_score": True, "score": _score_dict(s),
                                       "rank": pos.get("rank"), "n_countries": pos.get("n_countries")}
            return ProductSnapshot(tier=tier, period=s.period, payload=payload,
                                   entity_name=None, entity_roster=())

        iso3 = (scope or "").strip().upper()
        if not iso3:
            raise ValueError("Seleccioná un país del panel para el Insight/Deep Dive de ESG.")
        s = get_for_entity_period(db, iso3, period)
        country_name = IRC_PANEL.get(iso3, iso3)
        if s is None:
            return ProductSnapshot(tier=tier, period=period or "—",
                                   payload={"has_score": False}, entity_name=country_name,
                                   entity_roster=())
        payload = {"has_score": True, "score": _score_dict(s)}
        if tier == ProductTier.deep_dive:
            payload["position"] = _panel_position(db, s.period, iso3)
        return ProductSnapshot(tier=tier, period=s.period, payload=payload,
                               entity_name=country_name)

    # ── Muestra sintética (datos demo ilustrativos, sin DB) ──
    def sample_snapshot(self, tier: ProductTier) -> ProductSnapshot:
        score = {"entity_key": "DOM", "period": "2023", "esg_score": 35.65, "band": "Baja",
                 "breakdown": {"dimensions": {
                     "physical_risk": {"score": 40.0, "weight": 0.3, "contribution": 12.0},
                     "governance": {"score": 50.0, "weight": 0.2, "contribution": 10.0}},
                     "sources": {"governance_quality": "live"}}}
        payload: Dict[str, Any] = {"has_score": True, "score": score}
        if tier == ProductTier.pulse:
            payload["rank"] = 22
            payload["n_countries"] = 24
            return ProductSnapshot(tier=tier, period="2023", payload=payload,
                                   entity_name=None, entity_roster=())
        if tier == ProductTier.deep_dive:
            payload["position"] = {"rank": 22, "n_countries": 24,
                                   "distribution": {"mean": 48.0, "max": 70.0, "min": 20.0}}
        return ProductSnapshot(tier=tier, period="2023", payload=payload, entity_name=COUNTRY_NAME)

    def sample_narratives(self, tier: ProductTier) -> Dict[str, str]:
        """Narrativa CURADA tier-1 de la muestra (exemplar). NO usa el motor IA."""
        sections = self.product_manifest().require_level(tier).sections
        return {sec: (_LIMITATIONS if sec == "limitations" else _SAMPLE_NARRATIVES[sec])
                for sec in sections}

    # ── Narrativas (sin DB — operan sobre el snapshot) ──
    async def narratives(self, tier: ProductTier, snapshot: ProductSnapshot,
                         lang: str = "es") -> Dict[str, str]:
        sections = self.product_manifest().require_level(tier).sections
        if not snapshot.payload.get("has_score"):
            return {sec: (_LIMITATIONS if sec == "limitations" else _NO_DATA)
                    for sec in sections}

        from shared.narrative.claude_engine import narrative_engine
        score = snapshot.payload["score"]
        pos = snapshot.payload.get("position") or {}
        # País del snapshot (Pulse = RD nacional; niveles nombrados = país elegido).
        entity_key = score.get("entity_key", COUNTRY_ISO)
        country_name = snapshot.entity_name or COUNTRY_NAME
        base_ctx = climate_ai_context(
            entity_key, score, country_name=country_name,
            rank=snapshot.payload.get("rank") or pos.get("rank"),
            n_countries=snapshot.payload.get("n_countries") or pos.get("n_countries"),
            distribution=pos.get("distribution"))
        audience = "inversionista"
        out: Dict[str, str] = {}
        for section in sections:
            if section == "limitations":
                out["limitations"] = _LIMITATIONS
                continue
            ctx = dict(base_ctx)
            if section == "panel_position":
                # Precalcular las distancias (media/líder) para que el modelo cite cifras
                # EXACTAS guardadas, no las derive (regla del thin: número solo si está
                # precalculado). Mayor IRC = mayor resiliencia.
                dist = pos.get("distribution") or {}
                sc = score.get("esg_score")
                if sc is not None and dist.get("mean") is not None:
                    ctx["delta_vs_media"] = round(sc - dist["mean"], 2)
                if sc is not None and dist.get("max") is not None:
                    ctx["delta_vs_lider"] = round(sc - dist["max"], 2)
                ctx["enfoque"] = (f"Posición RELATIVA de {country_name} en el panel Caribe/LatAm: "
                                  "rank y distancias precalculadas (delta_vs_media, delta_vs_lider); "
                                  "qué pares la superan y por qué.")
            elif section == "recommendation":
                ctx["enfoque"] = ("Cierre ACCIONABLE: la dimensión con mayor brecha "
                                  "(físico/transición/adaptativa/gobernanza) y la palanca de "
                                  "resiliencia con mayor retorno, dado el cuadro anterior.")
            res = await narrative_engine.generate(
                context=ctx,
                template="sector_decision" if section == "recommendation" else "climate_outlook",
                mode=section_mode(tier, section, sections),
                axis="esg_climate", audience=audience)
            out[section] = res.text
        return out

    # ── Render (sin DB, renderer genérico) ──
    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None, fmt: str = "pdf") -> str:
        level = self.product_manifest().require_level(tier)
        title = {"pulse": "Pulse ESG & Clima", "insight": "Insight ESG & Clima",
                 "deep_dive": "Deep Dive ESG & Clima"}.get(tier.value, "ESG & Clima")
        display = ("Resiliencia Climática Nacional · RD" if tier == ProductTier.pulse
                   else (snapshot.entity_name or COUNTRY_NAME))
        tables: List = []
        charts: List = []
        score = (snapshot.payload or {}).get("score") or {}
        dims = (score.get("breakdown") or {}).get("dimensions") or {}
        _labels = {"physical_risk": "Riesgo físico", "transition_risk": "Riesgo transición",
                   "adaptive_capacity": "Cap. adaptativa", "governance": "Gobernanza"}
        if dims:
            rows = [["Dimensión", "Score"]] + [
                [_labels.get(k, str(k)), _pct((d or {}).get("score"))] for k, d in dims.items()]
            tables.append(("Dimensiones del IRC", rows))
            items = [(_labels.get(k, str(k)), (d or {}).get("score")) for k, d in dims.items()]
            charts.append({"title": "Dimensiones del IRC (score 0-100)", "items": items})
        sc = score.get("esg_score")
        headline = (f"IRC {sc:.1f} · {score.get('band')}" if isinstance(sc, (int, float))
                    else None)
        return render_product_pdf(
            sector_key=SECTOR_KEY, display_name=display, title=title,
            period=snapshot.period, narratives=narratives,
            section_titles=_SECTION_TITLES, tables=tables, charts=charts, headline=headline,
            subtitle=None, watermark=level.watermark, sample=sample,
            output_dir=output_dir, fmt=fmt)


register_product(SECTOR_KEY, lambda db: ESGProduct(db))
