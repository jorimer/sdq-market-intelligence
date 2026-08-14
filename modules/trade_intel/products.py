"""Trade & Logistics (Comercio Exterior) como ``SectorProduct`` — sector #3.

Mono-módulo (como Banca): ``trade_intel`` ya tiene módulo + dato real (DGA) +
scoring de resiliencia + validación (Gate E). Implementa el ``Protocol``
``SectorProduct`` (shared/products) SIN tocar el framework: manifiesto de 3 niveles
+ señales de readiness + producción de reporte por nivel, reusando el motor de
narrativa y los getters PÚBLICOS del propio módulo (``service``/``ai_context``/
``partners``) — nada de tablas ajenas en crudo.

Naturaleza NACIONAL/AGREGADA (como Macro): el comercio no tiene entidades-firma; el
dato es por capítulo arancelario (HS) y país socio. El nivel nombrado es el PAÍS
(República Dominicana); el Pulse es el pulso comercial nacional. Doctrina del dueño
(2026-06-23): el Pulse PUEDE nombrar capítulos HS (categorías de producto, no firmas)
→ sin bandas de anonimización; ``entity_roster=()`` y el sensor pasa trivialmente.

Eje doctrinal ÚNICO: ``trade_intel`` (a diferencia de Macro, que mezcla dos). Las
narrativas con cifras pasan ``axis="trade_intel"`` → numeric_guard (lección 2026-06-23).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any, Dict, List, Optional

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
    distinct_periods,
    register_product,
    section_mode,
)
from shared.products.render import render_product_pdf
from modules.trade_intel.ai_context import trade_ai_context
from modules.trade_intel.models.models import TradeFlow, TradeScore
from modules.trade_intel.service import get_latest_score

logger = logging.getLogger("sdq.products.trade")

SECTOR_KEY = "trade"
COUNTRY_NAME = "República Dominicana"
# G5 cuando el backtest no está persistido: Gate E firmado (metodología validada),
# sin la fuerza exacta del IC → valor conservador. Si el backtest está en DB, se
# recalcula desde su Gini/IC real (ver validation_state).
_DOCTRINE_VALIDATION_FALLBACK = 0.7

_SECTION_TITLES = {
    "trade_pulse": "Pulso de Comercio Exterior",
    "trade_assessment": "Evaluación de Resiliencia Comercial",
    "geographic_concentration": "Concentración Geográfica (Socios)",
    "recommendation": "Lectura para Decisión",
    "limitations": "Limitaciones",
}
_LIMITATIONS = (
    "La resiliencia comercial se construye sobre los flujos de comercio exterior "
    "publicados por la DGA (Aduanas), por capítulo arancelario (HS), a la fecha de corte; "
    "la concentración por país socio proviene de UN Comtrade (con la RD como reportante). "
    "La lectura no anticipa choques externos aún no materializados ni reclasificaciones "
    "arancelarias posteriores al período, y corresponde a una validación direccional "
    "(Gate E), no a una clasificación de grado-Basilea."
)
# Narrativa CURADA tier-1 de la muestra (exemplar). Coherente con los datos demo
# (resiliencia 60.6, diversificación 63%, dependencia importadora 0.475, HHI 0.37,
# exportaciones USD 4,200 MM, instrumentos médicos ~50% de la canasta).
_SAMPLE_NARRATIVES = {
    "trade_pulse": (
        "El comercio exterior dominicano cierra el período con un **índice de resiliencia "
        "de 60.6/100**, posición intermedia que refleja tanto la fortaleza de su "
        "inserción global como sus puntos de concentración. Las exportaciones (USD 4,200 "
        "millones) presentan una **diversificación de 63%**, sostenida por capítulos de "
        "alto valor agregado como instrumentos médicos, que no obstante concentran cerca "
        "de la mitad de la canasta. Dicha concentración —un HHI de 0.37— constituye la "
        "principal vulnerabilidad: un shock en un capítulo clave tendría un impacto "
        "desproporcionado. Por el lado importador, una **dependencia de 0.475** indica una "
        "economía abierta e integrada a cadenas globales, lo que aporta eficiencia pero "
        "también exposición a precios y disrupciones externas. En conjunto, se observa una "
        "plataforma comercial competitiva, cuya resiliencia depende de continuar ampliando "
        "la base de productos y destinos."
    ),
    "trade_assessment": (
        "La resiliencia comercial de la República Dominicana se evalúa en **60.6/100**, un "
        "perfil sólido pero con margen claro de mejora. La fortaleza reside en la calidad "
        "de su canasta exportadora: la presencia de instrumentos médicos y manufactura de "
        "zonas francas posiciona a RD en segmentos de alto valor y demanda estable, menos "
        "sensibles a los ciclos de commodities. La principal restricción es la "
        "**concentración**: con los principales capítulos cerca del 50% de las "
        "exportaciones, la economía queda expuesta a un shock sectorial o regulatorio en "
        "un destino clave. La **dependencia importadora (0.475)** completa el cuadro: "
        "insumos, energía y bienes de capital importados son la contraparte de una "
        "economía manufacturera integrada a cadenas globales. Para un exportador o "
        "inversionista, RD ofrece una plataforma comercial madura cuya próxima frontera de "
        "valor es la diversificación de canasta y mercados, no el aumento de volumen."
    ),
    "geographic_concentration": (
        "La dimensión geográfica concentra un riesgo distinto al de producto: la "
        "**dependencia de mercados de destino**. Una parte sustancial de las exportaciones "
        "se dirige a un número reducido de socios —Estados Unidos a la cabeza—, de modo "
        "que la resiliencia comercial está vinculada no solo a qué se exporta, sino "
        "también a quién lo compra. Dicha concentración amplifica la exposición a ciclos "
        "de demanda y a decisiones de política comercial en esos destinos. El factor "
        "compensatorio es que el acceso preferencial (acuerdos como DR-CAFTA) ancla esos "
        "flujos y reduce la fricción. Para una contraparte, se concluye que la "
        "diversificación de destinos —ampliar la presencia en mercados europeos y "
        "regionales— resulta tan relevante para la resiliencia como la diversificación de "
        "productos."
    ),
    "recommendation": (
        "Para un exportador, inversionista o comité con exposición al comercio exterior "
        "dominicano, la palanca de mayor retorno sobre la resiliencia es inequívoca: la "
        "**diversificación**, tanto de canasta como de destinos. Con una resiliencia de "
        "60.6, el sistema no presenta un problema de competitividad, sino de "
        "concentración. El refuerzo de los segmentos consolidados (instrumentos médicos, "
        "zonas francas) afianza la posición, si bien el salto de resiliencia provendrá de "
        "ampliar la base: nuevos capítulos exportables y nuevos mercados de destino que "
        "reduzcan la sensibilidad a un shock localizado. La reducción de la dependencia "
        "importadora en insumos críticos —vía sustitución selectiva o integración local— "
        "constituye la palanca secundaria. Se recomienda priorizar la diversificación "
        "sobre el volumen, con seguimiento del HHI de exportaciones y de la concentración "
        "por socio."
    ),
}
_NO_DATA = (
    "No hay dato comercial persistido para el período: el producto está cableado pero "
    "su cobertura (G1) es insuficiente para publicar. No se fabrican cifras."
)


def trade_manifest() -> SectorProductManifest:
    return SectorProductManifest(
        sector_key=SECTOR_KEY, display_name="SDQ Trade & Logistics", levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=("trade_pulse",), narrative_templates=("trade_outlook",),
                audience="mercado / abierto", cadence="periodic",
                watermark="Vista abierta · SDQMIP", price_band="abierto"),
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.named_entity,
                sections=("trade_assessment", "geographic_concentration"),
                narrative_templates=("trade_outlook",),
                audience="cliente / comité", cadence="recurring", price_band="suscripción"),
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=("trade_assessment", "geographic_concentration",
                          "recommendation", "limitations"),
                # Todas las secciones con cifras narran con el ÚNICO thin del eje
                # (trade_outlook) → numeric_guard. "recommendation" NO es thin (sería
                # ruta legacy sin guard); se enruta por trade_outlook con un foco
                # accionable que la distingue del assessment (lección 2026-06-23).
                narrative_templates=("trade_outlook",),
                audience="comité / contraparte", cadence="on_demand", price_band="on-demand"),
        })


def _score_dict(s: TradeScore) -> Dict[str, Any]:
    """Payload del score (mismo molde que ``/trade-intel/score``) para alimentar
    ``trade_ai_context`` — reúso del builder del propio módulo, sin duplicar."""
    bd = s.breakdown or {}
    return {
        "period": s.period,
        "hhi_exports": s.hhi_exports,
        "export_diversification": s.export_diversification,
        "import_dependency": s.import_dependency,
        "resilience_score": s.resilience_score,
        "total_exports": bd.get("total_exports"),
        "total_imports": bd.get("total_imports"),
        "n_products_export": bd.get("n_products_export"),
        "n_products_import": bd.get("n_products_import"),
        "top_export_products": bd.get("top_export_products", []),
    }


_UNSET = object()  # centinela "aún no leído" (distingue de None = leído y vacío)


def _latest_score(db: Session, period: Optional[str] = None) -> Optional[TradeScore]:
    """Último score (o el del período) en un SAVEPOINT: si la lectura falla (tabla
    ausente, o transacción abortada en Postgres) revierte SOLO el savepoint, sin
    tumbar el recompute compartido (que itera todos los sectores en una sesión)."""
    try:
        with db.begin_nested():
            return get_latest_score(db, period or None)
    except Exception as e:  # noqa: BLE001
        logger.warning("Score comercial no disponible: %s", e)
        return None


def _latest_published(db: Session, period: str):
    """Fecha de publicación más reciente de los flujos del período (frescura), o None.
    En SAVEPOINT (ver ``_latest_score``)."""
    try:
        with db.begin_nested():
            return (db.query(func.max(TradeFlow.published_at))
                    .filter(TradeFlow.period == period).scalar())
    except Exception as e:  # noqa: BLE001
        logger.warning("Frescura comercial no disponible: %s", e)
        return None


def _period_end_date(period: str):
    """Fin del período como fecha — fallback de frescura cuando los flujos no traen
    ``published_at``: ``'2026-Q1'``→2026-03-31, ``'2026-05'``→fin de mes, ``'2026'``→2026-12-31."""
    import calendar
    try:
        s = str(period)
        if "-Q" in s:
            y, q = s.split("-Q")
            m = int(q) * 3
            return date(int(y), m, calendar.monthrange(int(y), m)[1])
        if "-" in s:
            y, m = s.split("-")[:2]
            return date(int(y), int(m), calendar.monthrange(int(y), int(m))[1])
        if len(s) == 4 and s.isdigit():
            return date(int(s), 12, 31)
    except (ValueError, TypeError):
        return None
    return None


def _backtest_export_collapse(db: Session) -> Optional[Dict[str, Any]]:
    """Bloque ``export_collapse`` del backtest persistido (Gate E), o None. SAVEPOINT."""
    import json
    from shared.settings.models import AppSetting
    try:
        with db.begin_nested():
            row = (db.query(AppSetting)
                   .filter(AppSetting.key == "trade_backtest_report").first())
        if not row:
            return None
        return (json.loads(row.value) or {}).get("export_collapse") or None
    except Exception as e:  # noqa: BLE001
        logger.warning("Backtest comercio no leído (uso doctrina firmada): %s", e)
        return None


def _partners() -> Optional[Dict[str, Any]]:
    """Concentración por país socio (dimensión geográfica, UN Comtrade), o None.
    Getter público del propio módulo; best-effort (fixture commiteado)."""
    try:
        from modules.trade_intel.partners import partner_concentration_report
        rep = partner_concentration_report()
        return rep if rep.get("has_data") else None
    except Exception as e:  # noqa: BLE001
        logger.warning("Concentración por socio no disponible: %s", e)
        return None


def _pct(share: Optional[float]) -> str:
    return "—" if share is None else f"{share * 100:.1f}%"

def _socios_por_capitulo(max_socios: int = 15, top_capitulos: int = 12) -> Dict[str, Any]:
    """``{socio: {period, total_usd_mm, capitulos:[{capitulo, usd_mm, pct}]}}``.

    Acotado y DECLARADO en las DOS dimensiones, porque el contexto del modelo no puede cargar
    192 socios × 95 capítulos: se sirven los socios de mayor valor y, dentro de cada uno, sus
    primeros capítulos. `truncado` dice cuántos capítulos quedaron fuera y `socios_omitidos`
    cuántos socios — un top-N silencioso se lee como si fuera todo. La INGESTA sí trae todos:
    el recorte es de presentación, no de dato.
    """
    from modules.trade_intel.models.models import TradePartnerChapter
    from modules.trade_intel.partner_chapters_sync import importaciones_por_capitulo
    from shared.database.session import SessionLocal

    db = SessionLocal()
    try:
        # Por VALOR, no por orden de inserción: los que pesan son los que deben llegar.
        from sqlalchemy import func
        rank = (db.query(TradePartnerChapter.partner,
                         func.sum(TradePartnerChapter.value).label("v"))
                .group_by(TradePartnerChapter.partner)
                .order_by(func.sum(TradePartnerChapter.value).desc()).all())
        socios = [r[0] for r in rank[:max_socios]]
        out: Dict[str, Any] = {}
        for s in socios:
            d = importaciones_por_capitulo(db, partner=s)
            if not d.get("capitulos"):
                continue
            caps = d["capitulos"]
            out[s] = {
                "period": d["period"], "total_usd_mm": d["total_usd_mm"],
                "n_capitulos": d["n_capitulos"],
                "capitulos_top": caps[:top_capitulos],
                "truncado": max(0, len(caps) - top_capitulos),
                "fuente": d["fuente"],
            }
        if out:
            # RECONCILIACIÓN EXPLÍCITA con el bloque `partners`, que publica
            # `import.n_partners` (193). Sin esto el modelo ve 193 allá y 12 acá, hace la
            # resta y publica "181 socios no tienen desglose por capítulo" — que es falso y
            # además le resta confianza al dato. No es que ignore una frase: es que el payload
            # se contradecía y resolvió la contradicción con aritmética. Los tres conteos van
            # SERVIDOS para que no haya nada que derivar.
            out["_cobertura"] = {
                "socios_con_desglose_computado": len(rank),
                "socios_listados_en_este_payload": len(socios),
                "nota": ("`partners.import.n_partners` cuenta el panel de socios con flujo; "
                         "este bloque cubre TODOS los que tienen desglose computado. La "
                         "diferencia entre ambos conteos NO es una brecha de dato: los que no "
                         "aparecen listados acá están en el sistema y se consultan por socio."),
            }
        return out
    except Exception:  # noqa: BLE001 — el snapshot nunca se cae por esta lectura
        return {}
    finally:
        db.close()



    # ── Snapshot por nivel ──




class TradeProduct:
    """``SectorProduct`` de Comercio. ``db`` opcional: las muestras sintéticas usan
    solo ``narratives``/``render`` (sin DB)."""

    sector_key = SECTOR_KEY

    def __init__(self, db: Optional[Session] = None):
        self._db = db
        self._cache: Any = _UNSET  # último score leído UNA vez por instancia

    def _require_db(self) -> Session:
        if self._db is None:
            raise RuntimeError("TradeProduct requiere una sesión de DB para esta operación.")
        return self._db

    def _latest(self) -> Optional[TradeScore]:
        """Último score, leído una sola vez por instancia (las 3 señales lo comparten)."""
        if self._cache is _UNSET:
            self._cache = _latest_score(self._require_db())
        return self._cache

    def product_manifest(self) -> SectorProductManifest:
        return trade_manifest()

    # ── Señales de readiness ──
    def data_signals(self) -> DataHealth:
        s = self._latest()
        if s is None:
            return DataHealth(coverage=0.0, freshness_days=None,
                              sources=("DGA", "UN Comtrade", "BCRD"),
                              detail="Sin score de resiliencia comercial persistido.")
        # Cobertura: fracción de las 3 métricas núcleo con dato (sin hardcode; DB vacía → 0).
        core = [s.resilience_score, s.export_diversification, s.import_dependency]
        coverage = sum(1 for v in core if v is not None) / len(core)
        # Frescura: published_at de los flujos; si no lo traen, se deriva del PERÍODO
        # (señal real de recencia del dato, no None → evita penalizar G1 con factor 0.5).
        latest_pub = _latest_published(self._require_db(), s.period) or _period_end_date(s.period)
        freshness = max(0, (date.today() - latest_pub).days) if latest_pub else None
        n_ch = (s.breakdown or {}).get("n_products_export")
        return DataHealth(coverage=coverage, freshness_days=freshness,
                          sources=("DGA", "UN Comtrade", "BCRD"),
                          detail=f"Resiliencia {s.resilience_score} en {s.period}"
                                 + (f" · {n_ch} capítulos export" if n_ch else ""))

    def has_engine(self) -> bool:
        return self._latest() is not None

    def available_periods(self) -> List[str]:
        return distinct_periods(self._require_db(), TradeScore.period)

    def validation_state(self) -> ValidationState:
        # G5 anclado al backtest real (Gate E) si está persistido; si no, doctrina firmada.
        notes = "Gate E validado (colapso-export, panel regional LatAm+Caribe)."
        score = _DOCTRINE_VALIDATION_FALLBACK
        ec = _backtest_export_collapse(self._require_db())
        if ec:
            gini, ci = ec.get("gini"), ec.get("gini_ci") or [None, None]
            if gini is not None:
                sig = ci[0] is not None and ci[0] > 0
                score = 0.75 if sig else 0.6
                notes = (f"Gate E: colapso-export Gini {gini} IC{ci}"
                         + (" (significativo)." if sig else " (inconcluso)."))
        return ValidationState(approved=True, score=score, notes=notes)

    def snapshot(self, tier: ProductTier, period: str,
                 scope: Optional[str] = None) -> ProductSnapshot:
        s = _latest_score(self._require_db(), period or None)
        if s is None:
            entity = None if tier == ProductTier.pulse else COUNTRY_NAME
            return ProductSnapshot(tier=tier, period=period or "—",
                                   payload={"has_score": False}, entity_name=entity,
                                   entity_roster=())
        payload: Dict[str, Any] = {"has_score": True, "score": _score_dict(s)}
        if tier == ProductTier.pulse:
            # Nacional/agregado: NO hay entidades-firma → roster vacío (el sensor de
            # anonimización pasa trivialmente). Los capítulos HS del payload son
            # categorías de producto, no firmas (doctrina del dueño 2026-06-23).
            return ProductSnapshot(tier=tier, period=s.period, payload=payload,
                                   entity_name=None, entity_roster=())
        if tier == ProductTier.deep_dive:
            payload["partners"] = _partners()  # dimensión geográfica (UN Comtrade)
            # Cruce socio × capítulo: QUÉ bienes vienen de cada socio. Va en el payload
            # porque es lo que lee el motor de Research (`shared/research/data_pull`), que
            # sólo ve el snapshot del producto. Sin esto el dato vive en la base y en su
            # endpoint, pero el motor sigue respondiendo que no lo tiene — que es justo lo
            # que hizo con "¿qué le importamos a China, desglosado?".
            payload["socios_por_capitulo"] = _socios_por_capitulo()
        return ProductSnapshot(tier=tier, period=s.period, payload=payload,
                               entity_name=COUNTRY_NAME)

    # ── Muestra sintética (datos demo ilustrativos, sin DB) ──
    def sample_snapshot(self, tier: ProductTier) -> ProductSnapshot:
        score = {"period": "2025", "resilience_score": 60.6, "export_diversification": 63.0,
                 "import_dependency": 0.475, "hhi_exports": 0.37, "total_exports": 4200.0,
                 "total_imports": 3800.0, "n_products_export": 3, "n_products_import": 5,
                 "top_export_products": [{"product": "instrumentos médicos", "share": 0.5}]}
        payload: Dict[str, Any] = {"has_score": True, "score": score}
        if tier == ProductTier.pulse:
            return ProductSnapshot(tier=tier, period="2025", payload=payload,
                                   entity_name=None, entity_roster=())
        if tier == ProductTier.deep_dive:
            payload["partners"] = None
        return ProductSnapshot(tier=tier, period="2025", payload=payload, entity_name=COUNTRY_NAME)

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
            # Honesto: sin dato no se narra cifra alguna (G1 baja, no publicable).
            return {sec: (_LIMITATIONS if sec == "limitations" else _NO_DATA)
                    for sec in sections}

        from shared.narrative.claude_engine import narrative_engine
        base_ctx = trade_ai_context(snapshot.payload["score"])
        # Audiencia: Pulse abierto = inversionista (lector de mercado); niveles
        # nombrados = exportador (la audiencia de decisión primaria del eje).
        audience = "inversionista" if tier == ProductTier.pulse else "exportador"
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
            # Único template thin del eje (guarded). El "foco" por sección lo entrega
            # el contexto, no un template distinto (recommendation no es thin → sin guard).
            if section == "geographic_concentration":
                ctx["partners"] = snapshot.payload.get("partners")
                ctx["enfoque"] = ("Concentración GEOGRÁFICA por país socio (no por producto): "
                                  "dónde está la dependencia de mercado de destino/origen.")
            elif section == "recommendation":
                ctx["enfoque"] = ("Cierre ACCIONABLE: prioriza la palanca (diversificación de "
                                  "canasta o reducción de dependencia importadora) con mayor "
                                  "retorno sobre la resiliencia, dado el cuadro anterior.")
            pending.append((section, dict(
                context=ctx,
                template="sector_decision" if section == "recommendation" else "trade_outlook",
                mode=section_mode(tier, section, sections),
                axis="trade_intel", audience=audience)))

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
        title = {"pulse": "Pulse Comercio", "insight": "Insight Comercio",
                 "deep_dive": "Deep Dive Comercio"}.get(tier.value, "Comercio")
        display = ("Sistema de Comercio Exterior · RD" if tier == ProductTier.pulse
                   else COUNTRY_NAME)
        tables: List = []
        charts: List = []
        sd = (snapshot.payload or {}).get("score") or {}
        top = sd.get("top_export_products") or []
        if top:
            rows = [["Capítulo (HS)", "Participación"]] + [
                [str(p.get("product")), _pct(p.get("share"))] for p in top[:8]]
            tables.append(("Concentración exportadora (top capítulos)", rows))
        if tier == ProductTier.deep_dive:
            partners = (snapshot.payload or {}).get("partners") or {}
            exp_top = (partners.get("export") or {}).get("top") or []
            if exp_top:
                rows = [["País socio", "Participación export"]] + [
                    [str(t.get("partner")), _pct(t.get("share"))] for t in exp_top[:8]]
                tables.append(("Concentración geográfica (top socios)", rows))
        # Composición de la resiliencia (0-100): sus dos palancas explicables + el índice.
        div = sd.get("export_diversification")
        dep = sd.get("import_dependency")
        res = sd.get("resilience_score")
        comp = [("Diversificación export.", div),
                ("Independencia import.", (1 - dep) * 100 if isinstance(dep, (int, float)) else None),
                ("Resiliencia comercial", res)]
        if any(isinstance(v, (int, float)) for _, v in comp):
            charts.append({"title": "Composición de la resiliencia comercial (0-100)",
                           "items": comp})
        headline = (f"Resiliencia comercial {res:.1f}/100" if isinstance(res, (int, float))
                    else None)
        return render_product_pdf(
            sector_key=SECTOR_KEY, display_name=display, title=title,
            period=snapshot.period, narratives=narratives,
            section_titles=_SECTION_TITLES, tables=tables, charts=charts, headline=headline,
            subtitle=None, watermark=level.watermark, sample=sample,
            output_dir=output_dir, fmt=fmt)


register_product(SECTOR_KEY, lambda db: TradeProduct(db))
