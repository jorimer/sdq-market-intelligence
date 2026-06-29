"""Estructura Sectorial de la Economía como ``SectorProduct`` — producto AGREGADO.

A diferencia de los productos por-sector (free_zones, tourism) o del corte transversal del
IAI, este producto consume la VISTA AGREGADA de los 17 sectores: peso en el Valor Agregado
+ contribución al crecimiento (peso × crecimiento). Responde "¿qué mueve la economía?" —
pensado para clientes institucionales (Min. Economía, BCRD, multilaterales).

Mono-módulo: vive en ``sector_intel`` (dueño del dato de los 17 sectores) y reusa
``service.get_economic_structure`` + el motor de narrativa (eje ``economic_structure``).
Producto DESCRIPTIVO: no hay índice 0-100; el "score" headline es el crecimiento agregado
del Valor Agregado. Naturaleza NACIONAL → ``entity_roster=()``.
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
    distinct_periods,
    register_product,
)
from shared.products.render import render_product_pdf
from modules.sector_intel.ai_context import economic_structure_ai_context
from modules.sector_intel.models.models import SectorVariable
from modules.sector_intel.service import SECTOR_DIMENSION, get_economic_structure

logger = logging.getLogger("sdq.products.economic_structure")

SECTOR_KEY = "economic_structure"
DISPLAY = "Economía Dominicana · Estructura Sectorial"
_UNSET = object()

_SECTION_TITLES = {
    "structure_overview": "Estructura de la Economía",
    "structure_assessment": "Importancia Sectorial y Contribución al Crecimiento",
    "recommendation": "Lectura para Decisión",
    "limitations": "Limitaciones",
}
_LIMITATIONS = (
    "Estructura sectorial sobre datos del BCRD (PIB por sectores de origen, base 2018): peso "
    "de cada sector en el Valor Agregado y su crecimiento real. La métrica de importancia es "
    "la CONTRIBUCIÓN al crecimiento (peso × crecimiento) — distinta del valor EXPORTADO (donde "
    "lideran joyería/oro por ser export-intensivos, no por su peso en el PIB) y de la "
    "ATRACTIVIDAD de inversión (IAI). Dato ANUAL AGREGADO NACIONAL; sin desglose subsectorial. "
    "Producto descriptivo (sin score sintético ni proyección): expone la estructura real."
)
_NO_DATA = (
    "No hay estructura sectorial persistida: corre `bcrd-sectores-sync` para ingerir el PIB "
    "por sectores de origen. No se fabrican cifras."
)

# Narrativa CURADA tier-1 (exemplar), coherente con el dato real 2025 (crecimiento VAB
# 2.03%; motores: financiero +0.34pp, transporte +0.32, turismo +0.32, comercio +0.26;
# lastre: construcción −0.24pp pese a ser el sector más grande, 13.5% del VAB).
_SAMPLE_NARRATIVES = {
    "structure_overview": (
        "La economía dominicana crece **2.0% en Valor Agregado** en el período, sostenida por "
        "una base sectorial diversificada (HHI ~807) donde ningún sector domina. Los pilares "
        "por **tamaño** son **Construcción (13.5% del PIB)**, **Comercio (12.6%)**, "
        "**Manufactura Local (9.9%)** y **Turismo (8.9%)**. Pero tamaño no es lo mismo que "
        "tracción: el crecimiento lo **mueven** hoy el sector **financiero** (+0.34 pp, ~17% de "
        "todo el crecimiento, creciendo 7.5%), **transporte** (+0.32 pp), **turismo** (+0.32 "
        "pp) y **comercio** (+0.26 pp). El gran **lastre** es la **Construcción**: el sector "
        "más grande de la economía, pero contrayéndose 1.8% y restando 0.24 pp al crecimiento. "
        "La lectura: una economía de demanda interna y servicios en expansión, con la "
        "inversión en construcción como el freno a revertir."
    ),
    "structure_assessment": (
        "La importancia de cada sector se lee en dos planos. **Estructural** (peso en el Valor "
        "Agregado): Construcción 13.5%, Comercio 12.6%, Manufactura Local 9.9%, Turismo 8.9%, "
        "Inmobiliario 8.1%, Transporte 7.9% — esos seis concentran ~61% de la economía. "
        "**Dinámico** (contribución al crecimiento = peso × crecimiento): el financiero, pese a "
        "pesar solo 4.6%, es el primer motor (+0.34 pp) por su expansión de 7.5%; le siguen "
        "transporte, turismo y comercio. El contraste lo da la Construcción: primer sector por "
        "tamaño, pero su contracción (−1.8%) la convierte en el principal lastre (−0.24 pp). "
        "Para una institución, esto separa los sectores que SOSTIENEN la economía de los que la "
        "EMPUJAN —o la frenan— hoy, que es donde la política y la inversión rinden más."
    ),
    "recommendation": (
        "Para una institución del Estado o un comité con visión macro-sectorial, la lectura "
        "accionable es doble. (1) El crecimiento se concentra en **servicios** (financiero, "
        "transporte, turismo, comercio): apuntalar su dinamismo —conectividad, formalización, "
        "promoción— protege el motor actual. (2) El mayor retorno está en **revertir el lastre "
        "de la Construcción**: por su peso (13.5%), pasar de −1.8% a crecimiento positivo "
        "aportaría más al PIB que cualquier otra palanca individual —ahí pesan la inversión "
        "pública, el crédito hipotecario y los permisos—. Recomendación: sostener los motores "
        "de servicios y priorizar la reactivación de la construcción como la intervención de "
        "mayor impacto agregado. (Lente de importancia/contribución; el valor exportado y la "
        "atractividad de inversión son análisis complementarios, no sustitutos.)"
    ),
}


def economic_structure_manifest() -> SectorProductManifest:
    return SectorProductManifest(
        sector_key=SECTOR_KEY, display_name="SDQ Sectoral Structure · Estructura de la Economía",
        levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=("structure_overview",),
                narrative_templates=("economic_structure_outlook",),
                audience="mercado / institucional", cadence="periodic",
                watermark="Vista abierta · SDQMIP", price_band="abierto"),
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.named_entity,
                sections=("structure_assessment",),
                narrative_templates=("economic_structure_outlook",),
                audience="institución / comité", cadence="recurring", price_band="suscripción"),
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=("structure_assessment", "recommendation", "limitations"),
                narrative_templates=("economic_structure_outlook",),
                audience="institución / contraparte", cadence="on_demand", price_band="on-demand"),
        })


def _latest_structure(db: Session, period: Optional[str] = None) -> Optional[Dict[str, Any]]:
    try:
        with db.begin_nested():
            st = get_economic_structure(db, period)
        return st if st.get("has_data") else None
    except Exception as e:  # noqa: BLE001
        logger.warning("Estructura sectorial no disponible: %s", e)
        return None


def _fmt(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.1f}"


class EconomicStructureProduct:
    sector_key = SECTOR_KEY

    def __init__(self, db: Optional[Session] = None):
        self._db = db
        self._cache: Any = _UNSET

    def _require_db(self) -> Session:
        if self._db is None:
            raise RuntimeError("EconomicStructureProduct requiere una sesión de DB.")
        return self._db

    def _latest(self) -> Optional[Dict[str, Any]]:
        if self._cache is _UNSET:
            self._cache = _latest_structure(self._require_db())
        return self._cache

    def product_manifest(self) -> SectorProductManifest:
        return economic_structure_manifest()

    def data_signals(self) -> DataHealth:
        st = self._latest()
        if st is None:
            return DataHealth(coverage=0.0, freshness_days=None, cadence="annual",
                              sources=("BCRD",), detail="Sin estructura sectorial persistida.")
        from datetime import date
        coverage = st.get("coverage") or 0.0
        freshness = None
        try:
            freshness = max(0, (date.today() - date(int(str(st.get("period"))[:4]), 12, 31)).days)
        except (ValueError, TypeError):
            pass
        td = st.get("top_driver") or {}
        return DataHealth(coverage=coverage, freshness_days=freshness, cadence="annual",
                          sources=("BCRD · PIB por sectores de origen",),
                          detail=f"VAB +{st.get('total_va_growth')}% en {st.get('period')} · "
                                 f"{st.get('n_sectors')} sectores · motor: {td.get('sector', '—')}")

    def has_engine(self) -> bool:
        return self._latest() is not None

    def available_periods(self) -> List[str]:
        # Períodos anuales con dato del PIB por sectores de origen (si_variables).
        return distinct_periods(self._require_db(), SectorVariable.period,
                                where=SectorVariable.dimension == SECTOR_DIMENSION)

    def validation_state(self) -> ValidationState:
        # Producto DESCRIPTIVO sobre dato real BCRD (no un índice predictivo) → no requiere
        # backtest; la "validación" es la identidad contable (Σ contribuciones = crec. VAB) +
        # la cobertura de la partición (suma a Valor Agregado, verificada en el conector).
        return ValidationState(approved=True, score=0.65,
                               notes="Vista descriptiva sobre dato real BCRD (PIB por sectores "
                                     "de origen). Sin score sintético ni proyección; la suma de "
                                     "contribuciones reconcilia con el crecimiento del VAB.")

    # ── Snapshot por nivel ──
    def snapshot(self, tier: ProductTier, period: str,
                 scope: Optional[str] = None) -> ProductSnapshot:
        st = _latest_structure(self._require_db(), period or None)
        if st is None:
            entity = None if tier == ProductTier.pulse else DISPLAY
            return ProductSnapshot(tier=tier, period=period or "—",
                                   payload={"has_data": False}, entity_name=entity,
                                   entity_roster=())
        payload = {"has_data": True, "structure": st}
        if tier == ProductTier.pulse:
            return ProductSnapshot(tier=tier, period=st.get("period") or "—", payload=payload,
                                   entity_name=None, entity_roster=())
        return ProductSnapshot(tier=tier, period=st.get("period") or "—", payload=payload,
                               entity_name=DISPLAY)

    # ── Muestra sintética (datos demo ilustrativos, sin DB) ──
    def sample_snapshot(self, tier: ProductTier) -> ProductSnapshot:
        def row(slug, name, w, g):
            return {"slug": slug, "sector": name, "weight": w, "growth": g,
                    "contribution": round(w * g / 100, 3),
                    "contribution_share": round((w * g / 100) / 2.03, 4)}
        sectors = [
            row("construccion", "Construcción", 13.45, -1.8),
            row("comercio", "Comercio", 12.65, 2.06),
            row("manufactura_local", "Manufactura Local", 9.91, 1.4),
            row("turismo", "Turismo (Hoteles/Bares/Rest.)", 8.94, 3.52),
            row("inmobiliario", "Inmobiliario y Alquiler", 8.10, 3.14),
            row("transporte", "Transporte y Almacenamiento", 7.93, 4.06),
            row("financiero", "Intermediación Financiera", 4.585, 7.45),
        ]
        drivers = sorted([s for s in sectors if s["contribution"] > 0],
                         key=lambda s: s["contribution"], reverse=True)
        drags = sorted([s for s in sectors if s["contribution"] < 0],
                       key=lambda s: s["contribution"])
        st = {"period": "2025", "has_data": True, "total_va_growth": 2.03, "coverage": 1.0,
              "contribution_coverage": 1.0, "concentration_hhi": 806.8, "n_sectors": 17,
              "source": "BCRD · PIB por sectores de origen (Valor Agregado)",
              "sectors": sorted(sectors, key=lambda s: s["weight"], reverse=True),
              "drivers": drivers, "drags": drags,
              "top_weight": max(sectors, key=lambda s: s["weight"]),
              "top_driver": drivers[0], "top_drag": drags[0] if drags else None}
        payload = {"has_data": True, "structure": st}
        if tier == ProductTier.pulse:
            return ProductSnapshot(tier=tier, period="2025", payload=payload,
                                   entity_name=None, entity_roster=())
        return ProductSnapshot(tier=tier, period="2025", payload=payload, entity_name=DISPLAY)

    def sample_narratives(self, tier: ProductTier) -> Dict[str, str]:
        sections = self.product_manifest().require_level(tier).sections
        return {sec: (_LIMITATIONS if sec == "limitations" else _SAMPLE_NARRATIVES[sec])
                for sec in sections}

    # ── Narrativas (sin DB) ──
    async def narratives(self, tier: ProductTier, snapshot: ProductSnapshot,
                         lang: str = "es") -> Dict[str, str]:
        sections = self.product_manifest().require_level(tier).sections
        if not snapshot.payload.get("has_data"):
            return {sec: (_LIMITATIONS if sec == "limitations" else _NO_DATA)
                    for sec in sections}

        from shared.narrative.claude_engine import narrative_engine
        base_ctx = economic_structure_ai_context(snapshot.payload["structure"])
        audience = "gobierno"
        mode = ("standard" if tier == ProductTier.pulse
                else "deep" if tier == ProductTier.deep_dive else "detailed")
        out: Dict[str, str] = {}
        for section in sections:
            if section == "limitations":
                out["limitations"] = _LIMITATIONS
                continue
            ctx = dict(base_ctx)
            if section == "recommendation":
                ctx["enfoque"] = ("Cierre ACCIONABLE: la palanca de mayor retorno sobre el "
                                  "crecimiento agregado, dado el cuadro de motores y lastres.")
            res = await narrative_engine.generate(
                context=ctx, template="economic_structure_outlook", mode=mode,
                axis="economic_structure", audience=audience)
            out[section] = res.text
        return out

    # ── Render (sin DB, renderer genérico) ──
    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None, fmt: str = "pdf") -> str:
        level = self.product_manifest().require_level(tier)
        title = {"pulse": "Pulse Estructura Sectorial", "insight": "Insight Estructura Sectorial",
                 "deep_dive": "Deep Dive Estructura Sectorial"}.get(tier.value, "Estructura Sectorial")
        display = ("Economía Dominicana" if tier == ProductTier.pulse else DISPLAY)
        tables: List = []
        st = (snapshot.payload or {}).get("structure") or {}
        sectors = st.get("sectors") or []
        charts: List = []
        if sectors:
            rows = [["Sector", "Peso %", "Crec. %", "Aporte pp"]] + [
                [str(s.get("sector")), _fmt(s.get("weight")), _fmt(s.get("growth")),
                 _fmt(s.get("contribution"))] for s in sectors[:10]]
            tables.append(("Estructura sectorial (top por peso)", rows))
            # Gráfico: contribución al crecimiento por sector (motores vs lastres), top por |aporte|.
            ranked = sorted([s for s in sectors if s.get("contribution") is not None],
                            key=lambda s: abs(s["contribution"]), reverse=True)[:10]
            ranked.sort(key=lambda s: s["contribution"], reverse=True)
            if ranked:
                charts.append({"title": "Contribución al crecimiento por sector (pp)",
                               "items": [(s.get("sector"), s.get("contribution")) for s in ranked],
                               "signed": True})
        return render_product_pdf(
            sector_key=SECTOR_KEY, display_name=display, title=title,
            period=snapshot.period, narratives=narratives,
            section_titles=_SECTION_TITLES, tables=tables, charts=charts, subtitle=None,
            watermark=level.watermark, sample=sample, output_dir=output_dir, fmt=fmt)


register_product(SECTOR_KEY, lambda db: EconomicStructureProduct(db))
