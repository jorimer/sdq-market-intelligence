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
    section_mode,
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
    "mechanism": "Mecanismo y Escenario: el Sector Bisagra",
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
        "El crecimiento dominicano de **2.0% en Valor Agregado** es real pero de composición "
        "frágil: lo impulsan servicios livianos —financiero, transporte, turismo— mientras el "
        "sector más grande, la **Construcción (13.5% del PIB)**, se contrae 1.8% y resta 0.24 "
        "pp. Esa es la tensión del período: el motor estructural de la economía se encuentra en "
        "reversa y el agregado se sostiene porque la demanda interna de servicios lo compensa. El "
        "primer motor es el **financiero**: pesa apenas 4.6% pero aporta ~17% de todo el "
        "crecimiento (crece 7.5%). La implicación para la decisión es directa: el mayor retorno no "
        "reside en acelerar lo que ya crece, sino en revertir la contracción de la construcción."
    ),
    "structure_assessment": (
        "El veredicto estructural es el siguiente: se trata de una economía que crece por "
        "**servicios** y se frena por **inversión física** —tamaño y tracción apuntan en "
        "direcciones opuestas. Por **tamaño**, la columna es Construcción (13.5%), Comercio (12.6%) "
        "y Manufactura (9.9%); seis sectores concentran ~61% del Valor Agregado. La **tracción** "
        "(contribución = peso × crecimiento), en cambio, la lidera el financiero: pesa solo 4.6% y "
        "constituye el primer motor (+0.34 pp, ~17% del crecimiento) por su expansión de 7.5%. El "
        "contraste define el año: la Construcción, primer sector por tamaño, es el principal lastre "
        "(−0.24 pp) porque se contrae 1.8%. Para una institución, esto significa que el 2.0% "
        "comprende una economía donde el componente que sostiene (servicios) y el que frena "
        "(inversión física) se han separado, de modo que la política rinde más donde se ubica el "
        "freno que donde se ubica el impulso."
    ),
    "mechanism": (
        "El mecanismo detrás del cuadro se concentra en un factor: la **Construcción**. No "
        "constituye un evento sectorial aislado sino un lastre estructural, dado que es el sector "
        "de mayor encadenamiento hacia atrás de la economía: arrastra cemento, acero, comercio de "
        "materiales, empleo de baja calificación y servicios profesionales en obra. Que "
        "Servicios Profesionales y Salud también resten (−0.024 pp combinado, marginal) resulta "
        "coherente con una desaceleración de la inversión privada que comprime la demanda de "
        "valor añadido ligada a obra.\n\n"
        "El dato no desglosa el canal exacto, pero las hipótesis plausibles son tres: tasas "
        "de financiamiento aún por encima de mínimos históricos (canal crédito), contención del "
        "gasto de capital público (canal fiscal) y sobrecapacidad residencial post-pandemia. La "
        "política relevante difiere según el canal —subsidio de tasa vs. obra pública vs. "
        "vivienda asequible—, de modo que distinguirlos constituye la tarea analítica pendiente.\n\n"
        "La asimetría resulta determinante. Con un peso de 13.5%, si la Construcción pasara de "
        "−1.8% a apenas +2%, su contribución pasaría de −0.24 pp a +0.27 pp: un swing de ~0.51 pp "
        "sobre el crecimiento total, equivalente a replicar casi el aporte combinado del financiero "
        "más el transporte. Ningún otro sector dispone de esa palanca de reversión. Los indicadores "
        "a vigilar para determinar si el lastre cede en el próximo período son el crédito privado al "
        "sector, los permisos de construcción y la ejecución del gasto de capital público. Si esos "
        "tres permanecen deprimidos, la contracción es estructural y la política de tasas por sí "
        "sola no la resuelve."
    ),
    "recommendation": (
        "La palanca de mayor retorno sobre el crecimiento agregado consiste en **revertir la "
        "contracción de la Construcción**, no en acelerar los servicios que ya crecen. La razón es "
        "aritmética: por su peso (13.5%), pasar de −1.8% a crecimiento positivo aporta más al PIB "
        "que cualquier otra intervención individual —un swing potencial de ~0.5 pp. El instrumento "
        "es doble y se encuentra al alcance del Estado: destrabar la inversión pública en "
        "infraestructura (control directo) y sostener el crédito hipotecario en coordinación con el "
        "BCRD (segmento privado). Sostener los motores de servicios protege el piso, mientras que la "
        "construcción determina el techo. La señal que confirmaría la eficacia de la palanca es el "
        "alza de permisos y ejecución de obra pública en el segundo semestre; si permanecen sin "
        "variación, el arrastre es estructural y exige más que tasas."
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
                sections=("structure_assessment", "mechanism", "recommendation", "limitations"),
                narrative_templates=("economic_structure_outlook", "economic_structure_mechanism",
                                     "economic_structure_decision"),
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
        # Cada sección tiene su propio brief; la PROFUNDIDAD la decide el helper central
        # (section_mode): el assessment diagnostica (conclusión-primero), el mechanism abre
        # la cadena causal y cuantifica el escenario (la capa profunda real, la única que se
        # expande a 700-1000 palabras → deep_section), y la decisión cierra corta y accionable.
        templates = {
            "structure_overview": "economic_structure_outlook",
            "structure_assessment": "economic_structure_outlook",
            "mechanism": "economic_structure_mechanism",
            "recommendation": "economic_structure_decision",
        }
        out: Dict[str, str] = {}
        for section in sections:
            if section == "limitations":
                out["limitations"] = _LIMITATIONS
                continue
            res = await narrative_engine.generate(
                context=base_ctx, template=templates.get(section, "economic_structure_outlook"),
                mode=section_mode(tier, section, sections, deep_section="mechanism"),
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
        g = st.get("total_va_growth")
        headline = (f"Crecimiento del Valor Agregado {g:+.2f}% — {st.get('n_sectors', '')} sectores"
                    if isinstance(g, (int, float)) else None)
        return render_product_pdf(
            sector_key=SECTOR_KEY, display_name=display, title=title,
            period=snapshot.period, narratives=narratives,
            section_titles=_SECTION_TITLES, tables=tables, charts=charts, headline=headline,
            subtitle=None, watermark=level.watermark, sample=sample,
            output_dir=output_dir, fmt=fmt)


register_product(SECTOR_KEY, lambda db: EconomicStructureProduct(db))
