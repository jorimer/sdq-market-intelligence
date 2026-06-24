"""Sectores económicos como ``SectorProduct`` — sectores #4,#5,#8,#9.

Mono-módulo PARAMETRIZADO: ``sector_intel`` scorea los 17 sectores económicos (IAI
atractividad + SGPS momentum) sobre dato real BCRD (valor agregado por sector) +
contrato macro→sectorial. Un mismo ``SectorIntelProduct(product_key, sector_code)``
sirve a varios productos del catálogo, cada uno = un sector económico, registrándose
bajo su propia ``product_key``:

    tourism      → turismo            (Hoteles/Bares/Restaurantes)
    free_zones   → zonas_francas      (Manufactura Zonas Francas)
    construction → construccion
    agribusiness → agropecuario

Implementa el ``Protocol`` ``SectorProduct`` SIN tocar el framework, reusando el
motor de narrativa y los getters PÚBLICOS del propio módulo (``service``/``ai_context``).

Naturaleza NACIONAL/AGREGADA: el "entity" es el SECTOR económico de RD; no hay
firmas → ``entity_roster=()`` (el sensor de anonimización pasa trivialmente). El
Pulse es el pulso del sector; el nivel nombrado nombra al sector (no a una empresa).

Cobertura HONESTA: hoy solo 2 de 5 dimensiones del IAI son dato real (sector + macro);
negocios/talento/regulatoria son rúbrica declarada → G1 parcial. Estos productos
quedan **cableados pero no publicables** hasta ampliar la fuente. NUNCA inventar data.

Eje doctrinal ÚNICO: ``sector_intel`` + thin ``sector_outlook`` → numeric_guard.
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
    register_product,
)
from shared.products.render import render_product_pdf
from modules.sector_intel.ai_context import sector_ai_context
from modules.sector_intel.models.models import SectorScore
from modules.sector_intel.service import get_latest

logger = logging.getLogger("sdq.products.sector")

# product_key (catálogo) → (sector_code BCRD, display_name). Mapeo declarativo de los
# productos sectoriales servidos por sector_intel.
SECTOR_PRODUCTS: Dict[str, tuple] = {
    "tourism": ("turismo", "Turismo (Hoteles/Bares/Rest.) · RD"),
    "free_zones": ("zonas_francas", "Manufactura Zonas Francas · RD"),
    "construction": ("construccion", "Construcción · RD"),
    "agribusiness": ("agropecuario", "Agropecuario · RD"),
}
# Dimensiones del IAI con dato real hoy (espeja ai_context._LIVE_DIMS). El resto es
# rúbrica declarada → la cobertura (G1) cuenta solo el peso respaldado por dato real.
_REAL_DIMS = ("sector", "macro")
_UNSET = object()  # centinela "aún no leído" (distingue de None = leído y vacío)

_SECTION_TITLES = {
    "sector_pulse": "Pulso del Sector",
    "sector_assessment": "Evaluación de Atractividad (IAI)",
    "momentum": "Momentum del Sector (SGPS)",
    "recommendation": "Lectura para Decisión",
    "limitations": "Limitaciones",
}
_LIMITATIONS = (
    "Índice de Atractividad de Inversión (IAI) + momentum (SGPS) por sector, a la fecha "
    "de corte. Dato real: tamaño y crecimiento del sector (valor agregado BCRD) y "
    "exposición macro (contrato macro→sectorial). Las dimensiones de negocios, talento y "
    "regulatoria son rúbrica declarada (suben a real con WGI/estudios ONE), por lo que el "
    "IAI es una lectura PRELIMINAR de atractividad, no un veredicto sobre cobertura completa."
)
_NO_DATA = (
    "No hay score persistido para este sector: el producto está cableado pero su "
    "cobertura (G1) es insuficiente para publicar. No se fabrican cifras."
)


def sector_manifest(product_key: str, display_name: str) -> SectorProductManifest:
    return SectorProductManifest(
        sector_key=product_key, display_name=display_name, levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=("sector_pulse",), narrative_templates=("sector_outlook",),
                audience="mercado / abierto", cadence="periodic",
                watermark="Vista abierta · SDQMIP", price_band="abierto"),
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.named_entity,
                sections=("sector_assessment",), narrative_templates=("sector_outlook",),
                audience="cliente / comité", cadence="recurring", price_band="suscripción"),
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=("sector_assessment", "momentum", "recommendation", "limitations"),
                narrative_templates=("sector_outlook",),
                audience="comité / contraparte", cadence="on_demand", price_band="on-demand"),
        })


def _latest_score(db: Session, sector_code: str) -> Optional[SectorScore]:
    """Último score del sector en SAVEPOINT: una lectura que falla (tabla ausente, o
    transacción abortada en Postgres) revierte SOLO el savepoint, sin tumbar el
    recompute compartido (que itera todos los sectores en una sesión)."""
    try:
        with db.begin_nested():
            return get_latest(db, sector_code)
    except Exception as e:  # noqa: BLE001
        logger.warning("Score de '%s' no disponible: %s", sector_code, e)
        return None


def _score_for_period(db: Session, sector_code: str, period: str) -> Optional[SectorScore]:
    try:
        with db.begin_nested():
            return (db.query(SectorScore)
                    .filter_by(sector_code=sector_code, period=period).first())
    except Exception as e:  # noqa: BLE001
        logger.warning("Score de '%s' (%s) no disponible: %s", sector_code, period, e)
        return None


def _latest_dict(s: SectorScore) -> Dict[str, Any]:
    return {"sector_code": s.sector_code, "period": s.period, "iai_score": s.iai_score,
            "iai_band": s.iai_band, "sgps_score": s.sgps_score,
            "iai_breakdown": s.iai_breakdown or {}}


def _real_coverage(breakdown: Dict[str, Any]) -> float:
    """Fracción del PESO del IAI respaldado por dimensiones con dato real (sector+macro).
    Cobertura honesta: hoy ~0.4 (no se acredita la rúbrica declarada)."""
    dims = breakdown or {}
    total = sum((d or {}).get("weight") or 0.0 for d in dims.values())
    if total <= 0:
        return 0.0
    real = sum((d or {}).get("weight") or 0.0 for k, d in dims.items()
               if k in _REAL_DIMS and (d or {}).get("score") is not None)
    return real / total


def _fmt(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.1f}"


class SectorIntelProduct:
    """``SectorProduct`` de un sector económico (parametrizado). ``db`` opcional: las
    muestras sintéticas usan solo ``narratives``/``render`` (sin DB)."""

    def __init__(self, db: Optional[Session], product_key: str):
        if product_key not in SECTOR_PRODUCTS:
            raise ValueError(f"'{product_key}' no es un producto de sector_intel.")
        self._db = db
        self.sector_key = product_key
        self._sector_code, self._display = SECTOR_PRODUCTS[product_key]
        self._cache: Any = _UNSET

    def _require_db(self) -> Session:
        if self._db is None:
            raise RuntimeError("SectorIntelProduct requiere una sesión de DB para esta operación.")
        return self._db

    def _latest(self) -> Optional[SectorScore]:
        if self._cache is _UNSET:
            self._cache = _latest_score(self._require_db(), self._sector_code)
        return self._cache

    def product_manifest(self) -> SectorProductManifest:
        return sector_manifest(self.sector_key, self._display)

    # ── Señales de readiness ──
    def data_signals(self) -> DataHealth:
        s = self._latest()
        if s is None:
            return DataHealth(coverage=0.0, freshness_days=None, cadence="annual",
                              sources=("BCRD",), detail=f"Sin score de '{self._sector_code}'.")
        coverage = _real_coverage(s.iai_breakdown)
        # Cadencia ANUAL: el valor agregado BCRD por sector es la cifra de año completo.
        freshness = None
        try:
            freshness = (date.today() - date(int(str(s.period)[:4]), 12, 31)).days
        except (ValueError, TypeError):
            pass
        return DataHealth(coverage=coverage, freshness_days=freshness, cadence="annual",
                          sources=("BCRD", "contrato macro→sectorial"),
                          detail=f"IAI {_fmt(s.iai_score)} ({s.iai_band}) en {s.period} · "
                                 f"{len(_REAL_DIMS)}/5 dims reales")

    def has_engine(self) -> bool:
        return self._latest() is not None

    def validation_state(self) -> ValidationState:
        # Gate E sectorial DEFERIDO (lo desbloquea dato por sector, no backtest); el IAI
        # corre sobre 2/5 dims reales → validación parcial honesta, no veredicto pleno.
        return ValidationState(approved=True, score=0.5,
                               notes="Gate E sectorial diferido; IAI sobre 2/5 dims reales "
                                     "(sector+macro). SGPS (momentum) sobre crecimiento real BCRD.")

    # ── Snapshot por nivel ──
    def snapshot(self, tier: ProductTier, period: str,
                 scope: Optional[str] = None) -> ProductSnapshot:
        db = self._require_db()
        s = (_score_for_period(db, self._sector_code, period) if period else None) \
            or _latest_score(db, self._sector_code)
        if s is None:
            entity = None if tier == ProductTier.pulse else self._display
            return ProductSnapshot(tier=tier, period=period or "—",
                                   payload={"has_score": False}, entity_name=entity,
                                   entity_roster=())
        payload: Dict[str, Any] = {"has_score": True, "latest": _latest_dict(s)}
        if tier == ProductTier.deep_dive:
            payload["sgps_detail"] = s.sgps_breakdown or {}
        if tier == ProductTier.pulse:
            # Nacional/agregado: el sector ES el sujeto, no hay firmas → roster vacío.
            return ProductSnapshot(tier=tier, period=s.period, payload=payload,
                                   entity_name=None, entity_roster=())
        return ProductSnapshot(tier=tier, period=s.period, payload=payload,
                               entity_name=self._display)

    # ── Narrativas (sin DB — operan sobre el snapshot) ──
    async def narratives(self, tier: ProductTier, snapshot: ProductSnapshot,
                         lang: str = "es") -> Dict[str, str]:
        sections = self.product_manifest().require_level(tier).sections
        if not snapshot.payload.get("has_score"):
            return {sec: (_LIMITATIONS if sec == "limitations" else _NO_DATA)
                    for sec in sections}

        from shared.narrative.claude_engine import narrative_engine
        base_ctx = sector_ai_context(
            snapshot.payload["latest"], sector_name=self._display,
            sgps_detail=snapshot.payload.get("sgps_detail"))
        audience = "inversionista"
        mode = ("standard" if tier == ProductTier.pulse
                else "deep" if tier == ProductTier.deep_dive else "detailed")
        out: Dict[str, str] = {}
        for section in sections:
            if section == "limitations":
                out["limitations"] = _LIMITATIONS
                continue
            ctx = dict(base_ctx)
            if section == "momentum":
                ctx["enfoque"] = ("Momentum del sector (SGPS): aceleración/desaceleración del "
                                  "crecimiento real reciente, separada del nivel de atractividad.")
            elif section == "recommendation":
                ctx["enfoque"] = ("Cierre ACCIONABLE: la dimensión real con mayor brecha y la "
                                  "palanca de atractividad con mayor retorno, dado el cuadro anterior.")
            res = await narrative_engine.generate(
                context=ctx, template="sector_outlook", mode=mode,
                axis="sector_intel", audience=audience)
            out[section] = res.text
        return out

    # ── Render (sin DB, renderer genérico) ──
    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None) -> str:
        level = self.product_manifest().require_level(tier)
        title = {"pulse": "Pulse Sectorial", "insight": "Insight Sectorial",
                 "deep_dive": "Deep Dive Sectorial"}.get(tier.value, "Sectorial")
        display = (f"Sector {self._display}" if tier == ProductTier.pulse else self._display)
        tables: List = []
        latest = (snapshot.payload or {}).get("latest") or {}
        dims = latest.get("iai_breakdown") or {}
        if dims:
            rows = [["Dimensión", "Score", "Peso"]] + [
                [str(k), _fmt((d or {}).get("score")), _fmt((d or {}).get("weight"))]
                for k, d in dims.items()]
            tables.append(("Dimensiones del IAI", rows))
        return render_product_pdf(
            sector_key=self.sector_key, display_name=display, title=title,
            period=snapshot.period, narratives=narratives,
            section_titles=_SECTION_TITLES, tables=tables, subtitle=None,
            watermark=level.watermark, sample=sample, output_dir=output_dir)


# Auto-registro de cada producto sectorial (idempotente). Cada factory captura su
# product_key; shared/products nunca importa este módulo (anti-Frankenstein).
for _pk in SECTOR_PRODUCTS:
    register_product(_pk, lambda db, pk=_pk: SectorIntelProduct(db, pk))
