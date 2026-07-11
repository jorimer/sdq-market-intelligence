"""Sectores económicos como ``SectorProduct`` — sectores #4,#5,#8,#9.

Mono-módulo PARAMETRIZADO: ``sector_intel`` scorea los 17 sectores económicos (IAI
atractividad + SGPS momentum) sobre dato real BCRD (valor agregado por sector) +
contrato macro→sectorial. Un mismo ``SectorIntelProduct(product_key, sector_code)``
sirve a varios productos del catálogo, cada uno = un sector económico, registrándose
bajo su propia ``product_key``:

    construction → construccion
    agribusiness → agropecuario
    (free_zones tiene producto dedicado: modules.free_zones_intel · IZF/CNZFE)
    (tourism tiene producto dedicado: modules.tourism_intel · ITT/ONE)

Implementa el ``Protocol`` ``SectorProduct`` SIN tocar el framework, reusando el
motor de narrativa y los getters PÚBLICOS del propio módulo (``service``/``ai_context``).

Naturaleza NACIONAL/AGREGADA: el "entity" es el SECTOR económico de RD; no hay
firmas → ``entity_roster=()`` (el sensor de anonimización pasa trivialmente). El
Pulse es el pulso del sector; el nivel nombrado nombra al sector (no a una empresa).

Cobertura HONESTA por PROCEDENCIA (no hardcode): G1 acredita el peso del IAI que el
motor consumió con dato real. Hoy 6/9 variables son live —sector (BCRD ×2), macro
(contrato), operating_cost (TSS), labor_availability (ENCFT), regulatory_quality
(WGI nacional)— y 3 siguen rúbrica (ease_of_business, skills_index,
regulatory_volatility). Cada dimensión a medias acredita media cobertura → ~0.70, no
0.40. NUNCA inventar data: las rúbricas restantes suben con su conector (no se fingen).

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
    distinct_periods,
    register_product,
    section_mode,
)
from shared.products.render import render_product_pdf
from modules.sector_intel.ai_context import sector_ai_context
from modules.sector_intel.models.models import SectorScore
from modules.sector_intel.service import get_latest

logger = logging.getLogger("sdq.products.sector")

# product_key (catálogo) → (sector_code BCRD, display_name). Mapeo declarativo de los
# productos sectoriales servidos por sector_intel.
SECTOR_PRODUCTS: Dict[str, tuple] = {
    # free_zones, tourism y construction tienen producto DEDICADO (modules.free_zones_intel ·
    # IZF/CNZFE; modules.tourism_intel · ITT/ONE; modules.construction_intel · ICC/MIVHED+BCRD)
    # — ya no los sirve el corte transversal del IAI. Cada sector sigue en el peer set del IAI
    # (sector_catalog/bcrd_sectors); solo cambia el producto consumible del slot.
    "agribusiness": ("agropecuario", "Agropecuario · RD"),
}
# Dims históricamente reales — usadas SOLO como fallback conservador cuando el
# breakdown es legacy (sin procedencia por-variable). El cálculo vigente lee la
# procedencia real de cada variable (``_real_coverage``), no este conjunto fijo.
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
    "El Índice de Atractividad de Inversión (IAI), junto con su momentum (SGPS), se calcula "
    "por sector a la fecha de corte. Con dato real por sector: tamaño y crecimiento (valor "
    "agregado del BCRD), exposición macro (contrato macro→sectorial), costo operativo "
    "(salario TSS por actividad), mano de obra (empleo ENCFT por rama) y, donde la ENAE "
    "cubre el sector, rentabilidad real (utilidad/ingresos). Con dato real nacional (común a "
    "todos los sectores, no diferencia el ranking): calidad y volatilidad regulatoria (WGI). "
    "La facilidad de negocios y el índice de competencias se mantienen sobre rúbrica "
    "declarada y se incorporarán como dato real al disponer de su fuente. Donde la ENAE no "
    "cubre un sector, esa variable se omite —no se estima—, por lo que el atractivo de esos "
    "sectores se lee con menor profundidad."
)
_NO_DATA = (
    "No hay score persistido para este sector: el producto está cableado pero su "
    "cobertura (G1) es insuficiente para publicar. No se fabrican cifras."
)

# Narrativa CURADA tier-1 de la muestra (exemplar). Coherente con los datos demo
# (IAI 55.75 «Media», SGPS 62; breakdown sector 70/macro 55, negocios/talento/regulación
# 50 = rúbrica; SGPS histórico 60/estructural 64). El sector concreto lo nombra el título
# del PDF (render usa display); la prosa es válida para los 4 sub-sectores.
_SAMPLE_NARRATIVES = {
    "sector_pulse": (
        "El sector cierra el período con un **Índice de Atractivo de Inversión (IAI) de "
        "55.75/100 —banda Media—**, un perfil de potencial sólido con desarrollo desigual "
        "entre sus pilares. La fortaleza se concentra en el **desempeño del propio sector "
        "(score 70)**, que refleja un crecimiento real y una contribución consistente a la "
        "economía dominicana, reforzado por un **entorno macro favorable (55)**: el "
        "crecimiento elevado y la estabilidad nominal del país operan a favor. El momentum "
        "acompaña: un **SGPS de 62** indica que la trayectoria reciente sostiene el nivel. "
        "Los pilares de **clima de negocios, talento y marco regulatorio** se evalúan sobre "
        "rúbrica declarada —no sobre dato vivo—, por lo que el índice debe interpretarse "
        "como una señal direccional y no como un veredicto pleno, hasta ampliar esas "
        "fuentes. En términos de mercado, se trata de un sector con fundamentos atractivos y "
        "respaldo macroeconómico, cuya tesis de inversión se fortalece a medida que maduran "
        "las dimensiones de entorno."
    ),
    "sector_assessment": (
        "El atractivo de inversión del sector se evalúa en **55.75/100 (banda Media)**, una "
        "posición que combina fortalezas reales con dimensiones aún por consolidar. El "
        "pilar más sólido es el desempeño sectorial (70): el sector crece en términos "
        "reales y aporta de forma consistente al PIB, lo que constituye una base tangible "
        "para la tesis de inversión. El entorno macroeconómico (55) refuerza el cuadro, "
        "dado que la economía dominicana ofrece un contexto de crecimiento y estabilidad "
        "poco frecuente en la región. La cautela proviene de las dimensiones de entorno "
        "—clima de negocios, talento y regulación—, que hoy se sostienen sobre rúbrica "
        "declarada y no sobre dato vivo; en ese ámbito reside tanto la incertidumbre como el "
        "mayor potencial de revaluación del índice. Para un inversionista, el sector ofrece "
        "fundamentos atractivos respaldados por un entorno macro favorable, con la salvedad "
        "de que la evaluación completa del entorno operativo requiere profundizar la base de "
        "datos."
    ),
    "momentum": (
        "El momentum del sector se resume en el Score de Generación de Potencial Sostenible "
        "(SGPS) de 62. Una nota de transparencia sobre su composición: el **factor de "
        "aceleración** —la única de las tres componentes construida sobre dato real reciente— "
        "es la señal viva del momentum y la que aporta la lectura de dinámica. En cambio, los "
        "componentes **histórico y estructural son estimación declarada (rúbrica de casa), "
        "aún sin fuente sectorial**, y funcionan hoy como una base transparente y uniforme, "
        "no como medición: no debe leerse en ellos una diferencia de fundamentos entre "
        "sectores. La tabla de procedencia acompaña cada factor con su origen (real vs. "
        "rúbrica). En síntesis, la aceleración respalda una lectura favorable de la "
        "trayectoria reciente; la profundización del histórico y lo estructural sobre dato "
        "sectorial real es la vía para elevar la robustez de esta sección."
    ),
    "recommendation": (
        "Para un inversionista o comité que evalúa exposición al sector, la recomendación es "
        "de **interés constructivo con diligencia sobre el entorno operativo**. Los "
        "fundamentos —desempeño sectorial real y un entorno macro favorable— justifican la "
        "tesis; el momentum estructural la refuerza. La palanca de mayor retorno sobre el "
        "atractivo no reside en el desempeño (ya consolidado) sino en la **maduración de las "
        "dimensiones de entorno**: clima de negocios, disponibilidad de talento y marco "
        "regulatorio son las variables que hoy se evalúan sobre rúbrica y que, al "
        "consolidarse con dato vivo, definirán el atractivo real del sector. La "
        "recomendación operativa consiste en avanzar en la tesis aprovechando el respaldo "
        "macroeconómico, en paralelo a una mayor profundización de la diligencia sobre las "
        "condiciones operativas específicas del sector —el factor que distingue un buen "
        "sector de una buena inversión."
    ),
}


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
                sections=("sector_assessment", "momentum"),
                narrative_templates=("sector_outlook",),
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


# Variables live que son NACIONALES (constantes entre sectores): suben cobertura pero
# no diferencian el ranking (normalizan al medio bajo min-max). El resto del dato live
# es per-sector (BCRD, ENAE, ENCFT, TSS, contrato macro→sectorial). La distinción se
# declara en el linaje para no sobre-vender el cruce de umbral como profundidad real.
_NATIONAL_LIVE_VARS = ("regulatory_quality", "regulatory_volatility")


def _live_vars(breakdown: Dict[str, Any]) -> tuple:
    """``(live, total, national_live)`` de las variables del IAI con procedencia
    ``source=="live"``. ``national_live`` = cuántas de las live son señal nacional
    constante (no diferencian ranking). Solo cuenta dimensiones con ``variables`` que
    llevan ``source`` (breakdown moderno)."""
    live = total = national = 0
    for d in (breakdown or {}).values():
        for var, v in ((d or {}).get("variables") or {}).items():
            if "source" not in (v or {}):
                continue
            total += 1
            if v.get("source") == "live":
                live += 1
                if var in _NATIONAL_LIVE_VARS:
                    national += 1
    return live, total, national


def _real_coverage(breakdown: Dict[str, Any]) -> float:
    """Fracción del PESO del IAI respaldada por dato real, honesta a la procedencia
    por-variable persistida (``variables[var]["source"] == "live"``).

    Cada dimensión aporta ``peso × (variables live / variables totales)``: una
    dimensión a medias (p.ej. business = operating_cost live + ease_of_business
    rúbrica) acredita la mitad de su peso —ni 0 ni el total—, reflejando el dato que
    el motor REALMENTE consumió. Si el breakdown es legacy (sin procedencia por
    variable), cae al conteo por-dimensión-completa de las dims históricamente reales
    (sector+macro) para no regresar antes del re-backfill que estampa la procedencia.
    """
    dims = breakdown or {}
    total = sum((d or {}).get("weight") or 0.0 for d in dims.values())
    if total <= 0:
        return 0.0
    if _live_vars(dims)[1] == 0:  # legacy: sin procedencia → conteo conservador
        real = sum((d or {}).get("weight") or 0.0 for k, d in dims.items()
                   if k in _REAL_DIMS and (d or {}).get("score") is not None)
        return real / total
    real = 0.0
    for d in dims.values():
        vars_ = (d or {}).get("variables") or {}
        sourced = [v for v in vars_.values() if "source" in (v or {})]
        if not sourced:
            continue
        live = sum(1 for v in sourced if v.get("source") == "live")
        real += ((d or {}).get("weight") or 0.0) * (live / len(sourced))
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
        live, total, national = _live_vars(s.iai_breakdown)
        if total:
            per_sector = live - national
            prov = (f"{live}/{total} variables reales "
                    f"({per_sector} per-sector + {national} nacional)")
        else:
            prov = f"{len(_REAL_DIMS)}/5 dims reales"
        # Cadencia ANUAL: el valor agregado BCRD por sector es la cifra de año completo.
        freshness = None
        try:
            freshness = (date.today() - date(int(str(s.period)[:4]), 12, 31)).days
        except (ValueError, TypeError):
            pass
        return DataHealth(coverage=coverage, freshness_days=freshness, cadence="annual",
                          sources=("BCRD", "contrato macro→sectorial", "TSS", "ENCFT", "WGI"),
                          detail=f"IAI {_fmt(s.iai_score)} ({s.iai_band}) en {s.period} · {prov}")

    def has_engine(self) -> bool:
        return self._latest() is not None

    def available_periods(self) -> List[str]:
        return distinct_periods(self._require_db(), SectorScore.period,
                                where=SectorScore.sector_code == self._sector_code)

    def validation_state(self) -> ValidationState:
        # Gate E sectorial DEFERIDO (lo desbloquea dato por sector, no backtest); el IAI
        # corre sobre 2/5 dims reales → validación parcial honesta, no veredicto pleno.
        return ValidationState(approved=True, score=0.5,
                               notes="Gate E sectorial diferido; IAI sobre 6/9 variables reales "
                                     "(sector, macro, costo op. TSS, empleo ENCFT, WGI). SGPS "
                                     "(momentum) sobre crecimiento real BCRD.")

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

    # ── Muestra sintética (datos demo ilustrativos, sin DB) ──
    def sample_snapshot(self, tier: ProductTier) -> ProductSnapshot:
        latest = {"sector_code": self._sector_code, "period": "2025", "iai_score": 55.75,
                  "iai_band": "Media", "sgps_score": 62.0, "iai_breakdown": {
                      "sector": {"score": 70.0, "weight": 0.25, "contribution": 17.5},
                      "macro": {"score": 55.0, "weight": 0.15, "contribution": 8.25},
                      "business": {"score": 50.0, "weight": 0.20, "contribution": 10.0},
                      "talent": {"score": 50.0, "weight": 0.20, "contribution": 10.0},
                      "regulation": {"score": 50.0, "weight": 0.20, "contribution": 10.0}}}
        payload: Dict[str, Any] = {"has_score": True, "latest": latest}
        if tier == ProductTier.pulse:
            return ProductSnapshot(tier=tier, period="2025", payload=payload,
                                   entity_name=None, entity_roster=())
        if tier == ProductTier.deep_dive:
            payload["sgps_detail"] = {"sgps_score": 62.0, "factors": {
                "historical": {"value": 60.0, "weight": 0.40, "contribution": 24.0,
                               "imputed": False, "source": "rubric"},
                "structural": {"value": 64.0, "weight": 0.35, "contribution": 22.4,
                               "imputed": False, "source": "rubric"},
                "acceleration": {"value": 62.4, "weight": 0.25, "contribution": 15.6,
                                 "imputed": False, "source": "live"}}}
        return ProductSnapshot(tier=tier, period="2025", payload=payload, entity_name=self._display)

    def sample_narratives(self, tier: ProductTier) -> Dict[str, str]:
        """Narrativa CURADA tier-1 de la muestra (exemplar). NO usa el motor IA. El sector
        concreto lo nombra el título del PDF (render usa ``self._display``)."""
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
        base_ctx = sector_ai_context(
            snapshot.payload["latest"], sector_name=self._display,
            sgps_detail=snapshot.payload.get("sgps_detail"))
        audience = "inversionista"
        out: Dict[str, str] = {}
        for section in sections:
            if section == "limitations":
                out["limitations"] = _LIMITATIONS
                continue
            ctx = dict(base_ctx)
            if section == "momentum":
                ctx["enfoque"] = ("Momentum del sector (SGPS): aceleración/desaceleración del "
                                  "crecimiento real reciente, separada del nivel de atractividad. "
                                  "DECLARÁ con transparencia que los componentes histórico y "
                                  "estructural son ESTIMACIÓN DECLARADA (rúbrica de casa, aún sin "
                                  "fuente); solo la aceleración es dato real. No los presentes como "
                                  "medición.")
            elif section == "recommendation":
                ctx["enfoque"] = ("Cierre ACCIONABLE: la dimensión real con mayor brecha y la "
                                  "palanca de atractividad con mayor retorno, dado el cuadro anterior.")
            res = await narrative_engine.generate(
                context=ctx,
                template="sector_decision" if section == "recommendation" else "sector_outlook",
                mode=section_mode(tier, section, sections),
                axis="sector_intel", audience=audience)
            out[section] = res.text
        return out

    # ── Render (sin DB, renderer genérico) ──
    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None, fmt: str = "pdf") -> str:
        level = self.product_manifest().require_level(tier)
        title = {"pulse": "Pulse Sectorial", "insight": "Insight Sectorial",
                 "deep_dive": "Deep Dive Sectorial"}.get(tier.value, "Sectorial")
        display = (f"Sector {self._display}" if tier == ProductTier.pulse else self._display)
        tables: List = []
        charts: List = []
        latest = (snapshot.payload or {}).get("latest") or {}
        dims = latest.get("iai_breakdown") or {}
        _labels = {"sector": "Sectorial (BCRD)", "macro": "Macro", "business": "Negocios",
                   "talent": "Talento", "regulation": "Regulación"}
        if dims:
            rows = [["Dimensión", "Score", "Peso"]] + [
                [_labels.get(k, str(k)), _fmt((d or {}).get("score")), _fmt((d or {}).get("weight"))]
                for k, d in dims.items()]
            tables.append(("Dimensiones del IAI", rows))
            items = [(_labels.get(k, str(k)), (d or {}).get("score")) for k, d in dims.items()]
            charts.append({"title": "Dimensiones del IAI (score 0-100)", "items": items})
        # SGPS (momentum): tabla con PROCEDENCIA por factor. Histórico ← BCRD
        # crecimiento (real, all-17); estructural ← margen ENAE (real donde el marco
        # llega, ~9/17; rúbrica declarada en el resto); aceleración es real. La columna
        # evita presentar la rúbrica como dato (brecha de honestidad H1).
        sgps_factors = ((snapshot.payload or {}).get("sgps_detail") or {}).get("factors") or {}
        if sgps_factors:
            _sgps_labels = {"historical": "Histórico", "structural": "Estructural",
                            "acceleration": "Aceleración"}
            srows = [["Factor", "Valor", "Peso", "Procedencia"]]
            for k in ("historical", "structural", "acceleration"):
                f = sgps_factors.get(k) or {}
                proc = "Real" if f.get("source") == "live" else "Rúbrica (declarada)"
                srows.append([_sgps_labels.get(k, k), _fmt(f.get("value")),
                              _fmt(f.get("weight")), proc])
            tables.append(("Momentum del sector (SGPS) · procedencia", srows))
        sc = latest.get("iai_score")
        headline = (f"IAI {_fmt(sc)} · {latest.get('iai_band')}"
                    if isinstance(sc, (int, float)) else None)
        return render_product_pdf(
            sector_key=self.sector_key, display_name=display, title=title,
            period=snapshot.period, narratives=narratives,
            section_titles=_SECTION_TITLES, tables=tables, charts=charts, headline=headline,
            subtitle=None, watermark=level.watermark, sample=sample,
            output_dir=output_dir, fmt=fmt)


# Auto-registro de cada producto sectorial (idempotente). Cada factory captura su
# product_key; shared/products nunca importa este módulo (anti-Frankenstein).
for _pk in SECTOR_PRODUCTS:
    register_product(_pk, lambda db, pk=_pk: SectorIntelProduct(db, pk))
