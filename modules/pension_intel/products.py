"""Pensiones (SIPEN) como ``SectorProduct`` — productización (F3).

Mono-módulo (como Banca/Comercio): ``pension_intel`` ya tiene módulo + dato real
(SIPEN) + pulso del sistema + scoring de AFP (ISA). Implementa el ``Protocol``
``SectorProduct`` SIN tocar el framework: manifiesto de 3 niveles + señales de
readiness + producción de reporte por nivel, reusando el motor de narrativa y los
getters PÚBLICOS del propio módulo (``service``/``ai_context``/``scoring``).

Naturaleza MIXTA:
  * **Pulse** = pulso NACIONAL del sistema (anonimizado): rentabilidad CCI/SDP,
    comisiones, afiliados, dispersión AGREGADA (brecha/promedio) — NUNCA nombres de
    AFP (las AFP son firmas → ``entity_roster`` lleva sus nombres y el sensor de
    anonimización verifica que ninguno se filtró al agregado).
  * **Insight / Deep Dive** = una AFP NOMBRADA y su ISA (score relativo parcial).

Honestidad heredada del scoring: solvencia = brecha declarada (``coverage`` < 1) y
bandas absolutas DIFERIDAS → el producto vende una lectura RELATIVA y PARCIAL, no un
rating de solidez cerrado. Eso se nombra en limitaciones y en la narrativa.
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
from modules.pension_intel.ai_context import (
    pension_cartera_context,
    pension_entity_context,
    pension_peer_context,
)
from modules.pension_intel.models.models import PensionSnapshot
from modules.pension_intel.scoring.isa import compute_isa
from modules.pension_intel.service import build_system_pulse
from shared.data.sipen_client import afp_catalog

logger = logging.getLogger("sdq.products.pension")

SECTOR_KEY = "pension"
SYSTEM_NAME = "Sistema Dominicano de Pensiones"

_SECTION_TITLES = {
    "pension_pulse": "Pulso del Sistema de Pensiones",
    "pension_assessment": "Evaluación de Solidez de la AFP (ISA)",
    "peer_positioning": "Posición Competitiva frente a las AFP",
    "portfolio_context": "Cartera de Inversiones del Sistema (Contexto de Riesgo)",
    "recommendation": "Lectura para Decisión",
    "limitations": "Limitaciones",
}
_LIMITATIONS = (
    "El Índice de Solidez de AFP (ISA) es una lectura RELATIVA y PARCIAL sobre dato "
    "público de SIPEN/ADAFP: la SOLVENCIA (estados financieros de las AFP) es una brecha "
    "declarada y aún no entra al índice, por lo que la cobertura es inferior al 100% y las "
    "bandas absolutas de solidez (Sólida/Frágil) están diferidas hasta disponer de ella. "
    "El score ordena por POSICIÓN RELATIVA entre AFP con dato suficiente, no certifica "
    "solvencia. La rentabilidad es nominal. No es un rating crediticio ni grado-Basilea."
)
_NO_DATA = (
    "No hay dato suficiente de SIPEN para publicar este nivel: el producto está cableado "
    "pero su cobertura (G1) es insuficiente. No se fabrican cifras."
)
_NO_CARTERA = (
    "La composición de la cartera de inversiones del sistema (Cuadro 6.1 del boletín SIPEN) "
    "aún no está ingerida para este período. Ejecute la sincronización de cartera para "
    "incorporar este contexto de riesgo. No se fabrican cifras."
)
_SAMPLE_NARRATIVES = {
    "pension_pulse": (
        "El sistema dominicano de pensiones cierra el período con una **rentabilidad nominal "
        "de la CCI de 9.4%**, en torno a su promedio histórico, y un patrimonio acumulado en "
        "expansión (cerca de 15% anual). La lectura de mercado es de un sistema en crecimiento "
        "sostenido, donde la dispersión de rentabilidad entre administradoras —una **brecha de "
        "unos 2.8 puntos** entre la líder y la rezagada— es la variable competitiva a vigilar. "
        "La fragilidad estructural no está en los retornos sino en la cobertura: la densidad de "
        "cotización sigue siendo el límite del modelo. Para un inversionista, las AFP son el "
        "mayor bloque institucional del país y su crecimiento de activos define la profundidad "
        "del mercado de capitales local."
    ),
    "pension_assessment": (
        "La AFP se ubica en una **posición relativa intermedia** del Índice de Solidez (ISA), "
        "sostenida por su escala (es de las mayores del sistema por patrimonio gestionado) y "
        "una rentabilidad alineada con el promedio. El índice es PARCIAL: la solvencia —la "
        "dimensión de mayor peso— es una brecha declarada hasta disponer de los estados "
        "financieros, de modo que esta lectura mide posición competitiva (rentabilidad, escala, "
        "costo), no solvencia certificada. Su palanca de mejora más clara es el costo relativo "
        "(comisión sobre patrimonio), donde queda por detrás de su par más eficiente."
    ),
    "peer_positioning": (
        "Frente a las siete AFP del sistema, esta administradora **lidera en escala y costo** "
        "—está entre las mayores por patrimonio gestionado y reporta la comisión relativa más "
        "baja del grupo— pero **rezaga en rentabilidad**: su rendimiento nominal queda por debajo "
        "del promedio del panel, con una brecha de un par de puntos frente a la líder. En solvencia "
        "declarada se ubica en la parte alta, aunque esa dimensión descansa en cifras aún no "
        "auditadas para todas. La lectura competitiva: compite por costo y tamaño, no por retorno; "
        "su diferenciación es estructural (perfil conservador), no coyuntural."
    ),
    "portfolio_context": (
        "El ahorro previsional del sistema está **fuertemente concentrado en deuda soberana**: "
        "más de la mitad de la cartera son títulos del Ministerio de Hacienda y una porción "
        "adicional del Banco Central, lo que ata el rendimiento del fondo al riesgo y la curva del "
        "Estado dominicano. La exposición al **sistema financiero** (bancos y asociaciones) es el "
        "segundo bloque —fondeo institucional a la banca—, y el resto diversifica hacia **empresas, "
        "fideicomisos y fondos de inversión** del sector real. Para el afiliado, esto define el "
        "perfil de riesgo de su ahorro: profundidad y seguridad soberana a cambio de una "
        "concentración alta en un solo emisor —el Estado—."
    ),
    "recommendation": (
        "Para un afiliado o un comité, la lectura accionable es doble: la AFP ofrece escala y "
        "una rentabilidad sostenida en torno al promedio del sistema —consistencia, no picos—, "
        "pero su costo relativo es la variable a negociar o vigilar. Mientras la solvencia no "
        "entre al índice, la decisión debe apoyarse en el desempeño consistente y el costo, no "
        "en una banda de solidez absoluta que aún no es emisible. La señal a seguir: la "
        "evolución del costo relativo y la entrada de los estados financieros."
    ),
}


def pension_manifest() -> SectorProductManifest:
    return SectorProductManifest(
        sector_key=SECTOR_KEY, display_name="SDQ Pensiones (SIPEN)", levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=("pension_pulse",), narrative_templates=("pension_pulse",),
                audience="mercado / abierto", cadence="periodic",
                watermark="Vista abierta · SDQMIP", price_band="abierto"),
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.named_entity,
                sections=("pension_assessment", "peer_positioning"),
                narrative_templates=("pension_entity", "pension_peer_positioning"),
                audience="cliente / comité", cadence="recurring", price_band="suscripción"),
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=("pension_assessment", "peer_positioning", "portfolio_context",
                          "recommendation", "limitations"),
                narrative_templates=("pension_entity", "pension_peer_positioning",
                                     "pension_portfolio_context"),
                audience="comité / contraparte", cadence="on_demand", price_band="on-demand"),
        })


def _afp_names() -> Dict[str, str]:
    return {slug: name for slug, name in afp_catalog()}


def _isa_results(db: Session) -> List[Dict[str, Any]]:
    """``compute_isa`` en SAVEPOINT: si la lectura falla (tabla ausente o transacción
    abortada en Postgres) revierte solo el savepoint, sin tumbar el recompute compartido."""
    try:
        with db.begin_nested():
            return compute_isa(db)
    except Exception as e:  # noqa: BLE001
        logger.warning("ISA no disponible: %s", e)
        return []


def _pulse(db: Session) -> Optional[Dict[str, Any]]:
    try:
        with db.begin_nested():
            return build_system_pulse(db)
    except Exception as e:  # noqa: BLE001
        logger.warning("Pulso de pensiones no disponible: %s", e)
        return None


def _rentabilidad_trend(db: Session, slug: str, n: int = 24) -> List[tuple]:
    """``[(period, value)]`` de la rentabilidad nominal mensual de una AFP (últimos n)."""
    from modules.pension_intel.models.models import PensionSeries
    try:
        with db.begin_nested():
            rows = (db.query(PensionSeries.period, PensionSeries.value)
                    .filter(PensionSeries.entity_slug == slug,
                            PensionSeries.series_code == "rentabilidad_nominal_anual",
                            PensionSeries.value.isnot(None))
                    .order_by(PensionSeries.period.asc()).all())
    except Exception as e:  # noqa: BLE001
        logger.warning("Trayectoria de rentabilidad no disponible: %s", e)
        return []
    return [(p, v) for p, v in rows][-n:]


def _system_cartera(db: Session) -> Optional[Dict[str, Any]]:
    """Composición de la cartera de inversiones del sistema (Cuadro 6.1, fondo CCI), o None.

    Devuelve el payload completo (holdings + summary + total) — mismo molde que el
    endpoint ``/cartera`` — para alimentar tabla y narrativa de contexto de riesgo."""
    from modules.pension_intel.models.models import PensionHolding
    try:
        with db.begin_nested():
            latest = (db.query(PensionHolding.period).filter(PensionHolding.fund == "cci")
                      .order_by(PensionHolding.period.desc()).first())
            if not latest:
                return None
            period = latest[0]
            rows = (db.query(PensionHolding)
                    .filter(PensionHolding.fund == "cci", PensionHolding.period == period)
                    .order_by(PensionHolding.amount.desc().nullslast()).all())
    except Exception as e:  # noqa: BLE001
        logger.warning("Cartera del sistema no disponible: %s", e)
        return None
    leaves = [r for r in rows if not r.is_subtotal and r.amount is not None]
    total = sum(r.amount for r in leaves)

    def _cls_total(mc: str) -> float:
        return sum(r.amount for r in leaves if r.macro_class == mc and r.amount is not None)

    pub, bcrd = _cls_total("deuda_publica"), _cls_total("bcrd")
    return {
        "found": True, "fund": "cci", "period": period, "total": total,
        "summary": {
            "public_debt_amount": pub, "bcrd_amount": bcrd,
            "public_debt_pct": round(pub / total * 100, 2) if total else None,
            "bcrd_pct": round(bcrd / total * 100, 2) if total else None,
            "issuer_count": len(leaves),
        },
        "holdings": [{"issuer": r.issuer, "issuer_slug": r.issuer_slug, "sub_sector": r.sub_sector,
                      "amount": r.amount, "pct": r.pct, "is_subtotal": r.is_subtotal,
                      "macro_class": r.macro_class} for r in rows],
    }


def _peer_table(peers: Optional[List[Dict[str, Any]]]) -> Optional[tuple]:
    """Tabla comparativa: AFP × (ISA + score relativo por dimensión), ordenada por ISA."""
    if not peers:
        return None
    order = ["solvencia", "rentabilidad", "escala", "costo"]
    rows = [["AFP", "ISA", "Solvencia", "Rentab.", "Escala", "Costo"]]
    ranked = sorted(peers, key=lambda r: (r.get("overall_score") is not None,
                                          r.get("overall_score") or 0), reverse=True)
    for r in ranked:
        by = {d["key"]: d for d in r.get("dimensions") or []}
        isa = "—" if r.get("overall_score") is None else f"{r['overall_score']:.1f}"
        cells = [r.get("name") or r.get("slug"), isa]
        for k in order:
            sc = (by.get(k) or {}).get("score")
            cells.append("—" if sc is None else f"{sc:.0f}")
        rows.append(cells)
    if len(rows) <= 1:
        return None
    return ("Comparación con las AFP del sistema (score relativo 0–100 por dimensión)", rows)


def _trend_table(trend: Optional[List[tuple]]) -> Optional[tuple]:
    """Trayectoria de rentabilidad: muestreo anual (último mes de cada año) + último punto."""
    if not trend or len(trend) < 2:
        return None
    by_year: Dict[str, tuple] = {}
    for p, v in trend:  # ascendente → el último por año gana
        by_year[str(p)[:4]] = (p, v)
    pts = sorted(by_year.values())
    if trend[-1] not in pts:
        pts.append(trend[-1])
    rows = [["Período", "Rentab. nominal (anual)"]]
    for p, v in pts[-10:]:
        rows.append([p, f"{v:.2f}%"])
    return ("Trayectoria de rentabilidad nominal (SIPEN)", rows)


def _cartera_table(cartera: Optional[Dict[str, Any]]) -> Optional[tuple]:
    """Composición de la cartera del sistema por sub-sector/emisor (top-level), RD$ MM + %."""
    if not cartera or not cartera.get("found"):
        return None
    top = [h for h in cartera.get("holdings") or []
           if (h.get("is_subtotal") or h.get("sub_sector") is None) and h.get("amount") is not None]
    top.sort(key=lambda h: h["amount"], reverse=True)
    rows = [["Categoría / Emisor", "Monto (RD$ MM)", "% cartera"]]
    for h in top[:9]:
        pct = "—" if h.get("pct") is None else f"{h['pct']:.1f}%"
        rows.append([h["issuer"], f"{h['amount']/1e6:,.0f}", pct])
    if len(rows) <= 1:
        return None
    return (f"Composición de la cartera de inversiones · {cartera.get('period')} (Cuadro 6.1)", rows)


def _anon_pulse_payload(pulse: Dict[str, Any], n_scoreable: int) -> Dict[str, Any]:
    """Pulse payload SIN nombres de AFP (anonimizado): headline + dispersión agregada."""
    afp = pulse.get("afp_rentabilidad") or {}
    return {
        "has_data": True,
        "headline": pulse.get("headline") or {},
        "dispersion": {
            "spread_pp": afp.get("spread"),
            "average": afp.get("average"),
            "n_afp": pulse.get("entity_count"),
            "n_scoreable": n_scoreable,
        },
        "period": pulse.get("period"),
    }


def _anon_pulse_context(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Contexto IA del Pulse SIN nombres (líder/rezagada anonimizados)."""
    h = payload.get("headline") or {}
    d = payload.get("dispersion") or {}
    return {
        "period": payload.get("period"),
        "rentabilidad_cci_nominal": h.get("sipen.rentabilidad.cci_nominal_anual"),
        "rentabilidad_sdp_nominal": h.get("sipen.rentabilidad.sdp_nominal_anual"),
        "comisiones_sistema_rd_mm": h.get("sipen.comisiones.total_anual"),
        "afp_rentabilidad": {
            "periodo": payload.get("period"),
            "ranking": [],  # anonimizado: el Pulse abierto NO nombra AFP
            "lider": None, "rezagada": None,
            "brecha_pp": d.get("spread_pp"), "promedio_simple": d.get("average"),
        },
        "n_afp": d.get("n_afp"),
        "direction": "mayor cobertura/fondo y rentabilidad sostenible = sistema más sólido",
        "source": "SIPEN — sistema dominicano de pensiones (dato real)",
        "unit_rentabilidad": "% anual nominal",
        "note": "Pulse anonimizado: dispersión AGREGADA entre AFP (sin nombres). "
                "Rentabilidad nominal; léela vs su promedio histórico, no como ranking del mes.",
    }


class PensionProduct:
    """``SectorProduct`` de Pensiones. ``db`` opcional: las muestras sintéticas usan
    solo ``narratives``/``render`` (sin DB)."""

    sector_key = SECTOR_KEY

    def __init__(self, db: Optional[Session] = None):
        self._db = db

    def _require_db(self) -> Session:
        if self._db is None:
            raise RuntimeError("PensionProduct requiere una sesión de DB para esta operación.")
        return self._db

    def product_manifest(self) -> SectorProductManifest:
        return pension_manifest()

    # ── Catálogo: AFP elegibles para los niveles nombrados ──
    def scope_kind(self) -> str:
        return "entity"

    def scope_options(self) -> List[Dict[str, str]]:
        """AFP CALIFICABLES (con score) para el selector del catálogo. Las de dato
        insuficiente no se ofrecen como producto nombrado (no se vende un 'sin dato')."""
        names = _afp_names()
        out: List[Dict[str, str]] = []
        for r in _isa_results(self._require_db()):
            if r.get("overall_score") is not None:
                out.append({"value": r["slug"], "label": names.get(r["slug"], r["slug"]),
                            "group": "AFP"})
        return out

    # ── Señales de readiness ──
    def _freshness_days(self, db: Session) -> Optional[int]:
        """Días desde la última actualización del dato que alimenta el ISA (max
        ``published_at`` de las series por-AFP). Señal REAL de recencia (G1); ``None``
        solo si no hay nada que fechar."""
        from datetime import date

        from modules.pension_intel.models.models import PensionSeries
        try:
            with db.begin_nested():
                latest = (db.query(PensionSeries.published_at)
                          .filter(PensionSeries.entity_slug.isnot(None),
                                  PensionSeries.published_at.isnot(None))
                          .order_by(PensionSeries.published_at.desc()).first())
        except Exception as e:  # noqa: BLE001
            logger.warning("Frescura de pensiones no disponible: %s", e)
            return None
        return (date.today() - latest[0]).days if latest and latest[0] else None

    def data_signals(self) -> DataHealth:
        db = self._require_db()
        results = _isa_results(db)
        if not results:
            return DataHealth(coverage=0.0, freshness_days=None, sources=("SIPEN", "ADAFP"),
                              detail="Sin ISA de AFP computado.", cadence="quarterly")
        # Cobertura = media de la cobertura metodológica del ISA (parcial por la brecha
        # de solvencia): honesto, no hardcode.
        cov = sum(r["coverage"] for r in results) / len(results)
        n_scoreable = sum(1 for r in results if r["overall_score"] is not None)
        fresh = self._freshness_days(db)
        return DataHealth(
            coverage=round(cov, 4), freshness_days=fresh, sources=("SIPEN", "ADAFP"),
            detail=f"{n_scoreable}/{len(results)} AFP calificables · solvencia = brecha declarada",
            cadence="quarterly")

    def has_engine(self) -> bool:
        return bool(_isa_results(self._require_db()))

    def available_periods(self) -> List[str]:
        return distinct_periods(self._require_db(), PensionSnapshot.period)

    def validation_state(self) -> ValidationState:
        # Sin backtest de outcomes: el ISA es metodología parcial declarada, no validada
        # contra resultados. Honesto: aprobado por doctrina, fuerza modesta.
        return ValidationState(
            approved=True, score=0.5,
            notes="ISA = índice RELATIVO y PARCIAL (sin backtest de outcomes); solvencia = "
                  "brecha declarada, bandas absolutas diferidas.")

    # ── Snapshot por nivel ──
    def snapshot(self, tier: ProductTier, period: str,
                 scope: Optional[str] = None) -> ProductSnapshot:
        db = self._require_db()
        roster = tuple(_afp_names().values())
        if tier == ProductTier.pulse:
            pulse = _pulse(db)
            if not pulse:
                return ProductSnapshot(tier=tier, period=period or "—",
                                       payload={"has_data": False}, entity_name=None,
                                       entity_roster=roster)
            n_scoreable = sum(1 for r in _isa_results(db) if r["overall_score"] is not None)
            payload = _anon_pulse_payload(pulse, n_scoreable)
            payload["cartera"] = _system_cartera(db)  # composición de la cartera (sin nombres de AFP)
            return ProductSnapshot(tier=tier, period=pulse.get("period") or "—",
                                   payload=payload, entity_name=None, entity_roster=roster)

        # Niveles nombrados (Insight / Deep Dive): requieren la AFP.
        if not scope:
            raise ValueError("Debe indicar la AFP (scope) para el nivel nombrado.")
        names = _afp_names()
        results = _isa_results(db)
        rating = next((r for r in results if r["slug"] == scope), None)
        entity = names.get(scope, scope)
        if rating is None or rating.get("overall_score") is None:
            return ProductSnapshot(tier=tier, period=period or "—",
                                   payload={"has_data": False}, entity_name=entity)
        payload: Dict[str, Any] = {
            "has_data": True, "rating": rating, "peers": results,
            "trend": _rentabilidad_trend(db, scope, n=60),  # trayectoria real (hasta 5 años)
        }
        if tier == ProductTier.deep_dive:
            payload["cartera"] = _system_cartera(db)  # contexto de riesgo (dónde invierte el fondo)
        return ProductSnapshot(
            tier=tier, period=rating.get("period") or "—",
            payload=payload, entity_name=entity)

    # ── Muestra sintética (datos demo ilustrativos, sin DB) ──
    def sample_snapshot(self, tier: ProductTier) -> ProductSnapshot:
        if tier == ProductTier.pulse:
            payload = {
                "has_data": True,
                "headline": {"sipen.rentabilidad.cci_nominal_anual": 9.4,
                             "sipen.rentabilidad.sdp_nominal_anual": 9.6,
                             "sipen.comisiones.total_anual": 11500},
                "dispersion": {"spread_pp": 2.85, "average": 9.83, "n_afp": 7, "n_scoreable": 3},
                "period": "2025",
            }
            return ProductSnapshot(tier=tier, period="2025", payload=payload,
                                   entity_name=None, entity_roster=())
        rating = {
            "slug": "afp_ejemplo", "name": "AFP Ejemplo", "overall_score": 54.6,
            "score_kind": "relative_partial", "band": None, "coverage": 0.65, "period": "2025",
            "dimensions": [
                {"key": "solvencia", "label": "Solvencia", "weight": 0.35,
                 "provenance": "brecha", "present": False, "raw": None, "score": None},
                {"key": "rentabilidad", "label": "Rentabilidad", "weight": 0.30,
                 "provenance": "real", "present": True, "raw": 9.59, "score": 51.6},
                {"key": "escala", "label": "Escala (patrimonio)", "weight": 0.20,
                 "provenance": "real", "present": True, "raw": 428449.7, "score": 100.0},
                {"key": "costo", "label": "Costo (comisión/patrimonio)", "weight": 0.15,
                 "provenance": "real", "present": True, "raw": 0.00885, "score": 0.0},
            ],
        }
        peers = [rating,
                 {"slug": "afp_b", "name": "AFP Beta", "overall_score": 71.2, "coverage": 0.65,
                  "dimensions": [{"key": "solvencia", "score": 60.0}, {"key": "rentabilidad", "score": 80.0},
                                 {"key": "escala", "score": 55.0}, {"key": "costo", "score": 70.0}]},
                 {"slug": "afp_c", "name": "AFP Gamma", "overall_score": 48.3, "coverage": 0.65,
                  "dimensions": [{"key": "solvencia", "score": 40.0}, {"key": "rentabilidad", "score": 65.0},
                                 {"key": "escala", "score": 30.0}, {"key": "costo", "score": 45.0}]}]
        trend = [(f"2024-{m:02d}", 9.0 + 0.1 * m) for m in range(1, 13)] + \
                [(f"2025-{m:02d}", 9.6 - 0.05 * m) for m in range(1, 6)]
        cartera = {
            "found": True, "fund": "cci", "period": "2025", "total": 1_299_519_710_008.94,
            "summary": {"public_debt_pct": 56.04, "bcrd_pct": 8.69, "issuer_count": 77},
            "holdings": [
                {"issuer": "Ministerio de Hacienda", "sub_sector": None, "amount": 728_220_623_962.93,
                 "pct": 56.04, "is_subtotal": False, "macro_class": "deuda_publica"},
                {"issuer": "Fondos de Inversión", "sub_sector": "Fondos de Inversión", "amount": 248_276_866_041.58,
                 "pct": 19.11, "is_subtotal": True, "macro_class": None},
                {"issuer": "Banco Central de la República Dominicana", "sub_sector": None,
                 "amount": 112_896_479_175.12, "pct": 8.69, "is_subtotal": False, "macro_class": "bcrd"},
                {"issuer": "Bancos Múltiples", "sub_sector": "Bancos Múltiples", "amount": 87_956_707_912.06,
                 "pct": 6.77, "is_subtotal": True, "macro_class": None},
            ],
        }
        return ProductSnapshot(tier=tier, period="2025",
                               payload={"has_data": True, "rating": rating, "peers": peers,
                                        "trend": trend, "cartera": cartera},
                               entity_name="AFP Ejemplo")

    def sample_narratives(self, tier: ProductTier) -> Dict[str, str]:
        sections = self.product_manifest().require_level(tier).sections
        return {sec: (_LIMITATIONS if sec == "limitations" else _SAMPLE_NARRATIVES[sec])
                for sec in sections}

    # ── Narrativas (operan sobre el snapshot) ──
    async def narratives(self, tier: ProductTier, snapshot: ProductSnapshot,
                         lang: str = "es") -> Dict[str, str]:
        sections = self.product_manifest().require_level(tier).sections
        if not snapshot.payload.get("has_data"):
            return {sec: (_LIMITATIONS if sec == "limitations" else _NO_DATA)
                    for sec in sections}

        from shared.narrative.claude_engine import narrative_engine

        if tier == ProductTier.pulse:
            ctx = _anon_pulse_context(snapshot.payload)
            res = await narrative_engine.generate(
                context=ctx, template="pension_pulse", mode="standard",
                axis="pension_intel", audience="inversionista")
            return {"pension_pulse": res.text}

        rating = snapshot.payload["rating"]
        peers = snapshot.payload.get("peers") or [rating]
        entity = snapshot.entity_name or rating.get("name") or "AFP"
        base_ctx = pension_entity_context(rating, peers)
        # Enriquecer el contexto base con trayectoria (tendencia real) para que el análisis
        # de las dimensiones lea la trayectoria, no un punto.
        trend = snapshot.payload.get("trend") or []
        if trend:
            base_ctx["trayectoria_rentabilidad"] = [{"periodo": p, "valor": v} for p, v in trend[-12:]]
        cartera = snapshot.payload.get("cartera")
        mode = "deep" if tier == ProductTier.deep_dive else "detailed"
        out: Dict[str, str] = {}
        for section in sections:
            if section == "limitations":
                out["limitations"] = _LIMITATIONS
                continue
            if section == "peer_positioning":
                res = await narrative_engine.generate(
                    context=pension_peer_context(entity, rating, peers),
                    template="pension_peer_positioning", mode=mode,
                    axis="pension_intel", audience="inversionista")
                out[section] = res.text
                continue
            if section == "portfolio_context":
                if not cartera or not cartera.get("found"):
                    out[section] = _NO_CARTERA
                    continue
                res = await narrative_engine.generate(
                    context=pension_cartera_context(cartera),
                    template="pension_portfolio_context", mode=mode,
                    axis="pension_intel", audience="inversionista")
                out[section] = res.text
                continue
            ctx = dict(base_ctx)
            if section == "recommendation":
                ctx["enfoque"] = ("Cierre ACCIONABLE y SINTÉTICO (no repitas el desglose de "
                                  "dimensiones ya cubierto): la palanca de mayor retorno dada la "
                                  "posición relativa, la señal a vigilar (procedencia de solvencia, "
                                  "trayectoria de rentabilidad) y el 'y por tanto' de decisión.")
            res = await narrative_engine.generate(
                context=ctx, template="pension_entity", mode=mode,
                axis="pension_intel", audience="inversionista")
            out[section] = res.text
        return out

    # ── Render (renderer genérico) ──
    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None, fmt: str = "pdf") -> str:
        level = self.product_manifest().require_level(tier)
        title = {"pulse": "Pulse Pensiones", "insight": "Insight Pensiones",
                 "deep_dive": "Deep Dive Pensiones"}.get(tier.value, "Pensiones")
        display = SYSTEM_NAME if tier == ProductTier.pulse else (snapshot.entity_name or "AFP")
        tables: List = []
        payload = snapshot.payload or {}
        if tier == ProductTier.pulse and payload.get("has_data"):
            h = payload.get("headline") or {}
            rows = [["Indicador", "Valor"]]
            cci = h.get("sipen.rentabilidad.cci_nominal_anual")
            sdp = h.get("sipen.rentabilidad.sdp_nominal_anual")
            com = h.get("sipen.comisiones.total_anual")
            if cci is not None:
                rows.append(["Rentabilidad CCI (nominal)", f"{cci:.1f}%"])
            if sdp is not None:
                rows.append(["Rentabilidad SDP (nominal)", f"{sdp:.1f}%"])
            if com is not None:
                rows.append(["Comisiones del sistema", f"RD$ {com:,.0f} MM"])
            spread = (payload.get("dispersion") or {}).get("spread_pp")
            if spread is not None:
                rows.append(["Brecha de rentabilidad entre AFP", f"{spread:.2f} pp"])
            if len(rows) > 1:
                tables.append(("Pulso del sistema (SIPEN)", rows))
            cart = _cartera_table(payload.get("cartera"))
            if cart:
                tables.append(cart)
        elif payload.get("has_data"):
            rating = payload.get("rating") or {}
            rows = [["Dimensión", "Peso", "Score", "Procedencia"]]
            for d in rating.get("dimensions") or []:
                score = "—" if d.get("score") is None else f"{d['score']:.0f}"
                rows.append([d["label"], f"{d['weight']*100:.0f}%", score, d["provenance"]])
            tables.append(("Desglose del ISA (relativo, parcial)", rows))
            # Profundidad: pares (números reales), trayectoria, y cartera (deep dive).
            for tbl in (_peer_table(payload.get("peers")), _trend_table(payload.get("trend"))):
                if tbl:
                    tables.append(tbl)
            if tier == ProductTier.deep_dive:
                cart = _cartera_table(payload.get("cartera"))
                if cart:
                    tables.append(cart)
        return render_product_pdf(
            sector_key=SECTOR_KEY, display_name=display, title=title,
            period=snapshot.period, narratives=narratives,
            section_titles=_SECTION_TITLES, tables=tables, subtitle=None,
            watermark=level.watermark, sample=sample, output_dir=output_dir, fmt=fmt)


register_product(SECTOR_KEY, lambda db: PensionProduct(db))
