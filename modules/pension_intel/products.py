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
  * **Insight / Deep Dive** = una AFP NOMBRADA y su ISA (banda de solidez + posición relativa).

Honestidad DIRIGIDA POR EL DATO: con la solvencia incorporada (estados financieros de SIPEN,
historia 2010-2026) el ISA emite BANDA ABSOLUTA y ``coverage`` = 1; los caveats, el titular y
el contexto de IA se adaptan a ese estado vía ``_solvency_incorporated``/``_limitations_for``.
Si alguna AFP quedara sin estados financieros, vuelve sola a la lectura RELATIVA y PARCIAL con
banda reservada — nunca un hardcode. Eso se nombra en limitaciones y en la narrativa.
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
from modules.pension_intel.ai_context import (
    pension_cartera_context,
    pension_entity_context,
    pension_peer_context,
)
from modules.pension_intel.models.models import PensionSnapshot
from modules.pension_intel.scoring.isa import compute_isa
from modules.pension_intel.scoring.real_return import deflate_trend, fisher_real, inflation_at
from modules.pension_intel.service import build_system_pulse
from shared.contracts import load_inflation_series
from shared.data.sipen_client import afp_catalog

logger = logging.getLogger("sdq.products.pension")

SECTOR_KEY = "pension"
SYSTEM_NAME = "Sistema Dominicano de Pensiones"

_SECTION_TITLES = {
    "pension_pulse": "Pulso del Sistema de Pensiones",
    "pension_assessment": "Evaluación de Solidez de la AFP (ISA)",
    "peer_positioning": "Posición Competitiva frente a las AFP",
    "portfolio_context": "Cartera de Inversiones del Sistema (Contexto de Riesgo)",
    "early_warning": "Alerta Temprana",
    "recommendation": "Lectura para Decisión",
    "limitations": "Limitaciones",
}
# Limitaciones — DOS variantes por estado real del ISA (no hardcode):
#  * ABSOLUTA: la solvencia (estados financieros de SIPEN) está incorporada → el ISA emite
#    banda absoluta de solidez. Es el estado vigente desde el backfill de auditados 2010-2026.
#  * PARCIAL: sin solvencia (una AFP sin estados financieros) → lectura relativa, bandas
#    reservadas. Se conserva como fallback honesto para cualquier AFP que quede sin dato.
_LIMITATIONS_ABSOLUTE = (
    "El Índice de Solidez de AFP (ISA) integra cinco dimensiones sobre dato público de "
    "SIPEN/ADAFP: solvencia (patrimonio/activos, tomada de los estados financieros de las "
    "AFP publicados por SIPEN, con historia desde 2010), rentabilidad, riesgo (volatilidad "
    "realizada del valor cuota), escala y costo. Con la solvencia incorporada, el índice "
    "emite una banda absoluta de solidez (Sólida / Adecuada / En vigilancia / Frágil) además "
    "de ordenar la posición relativa entre las AFP. La rentabilidad se presenta en términos "
    "reales —deflactada por la inflación interanual del BCRD— además del nominal; el ISA "
    "puntúa sobre el nominal, ya que deflactar por una inflación común a todas las AFP no "
    "altera la posición relativa. El riesgo se mide como la volatilidad realizada del valor "
    "cuota y el Sharpe lo relaciona con la TPM; la volatilidad está parcialmente atenuada por "
    "la valoración a costo amortizado de la cartera. El ISA es una medida de solidez, "
    "relativa y por bandas absolutas; no constituye un rating de crédito ni una clasificación "
    "de grado-Basilea."
)
_LIMITATIONS_PARTIAL = (
    "El Índice de Solidez de AFP (ISA) ofrece una lectura relativa y parcial construida "
    "sobre dato público de SIPEN/ADAFP. Para esta AFP la solvencia (estados financieros) "
    "aún no está incorporada; mientras tanto la cobertura es inferior al 100% y la banda "
    "absoluta de solidez (Sólida/Frágil) se reserva. El score ordena la posición relativa "
    "entre las AFP con dato suficiente y no certifica solvencia. La rentabilidad se presenta "
    "en términos reales —deflactada por la inflación interanual del BCRD— además del nominal; "
    "el ISA puntúa sobre el nominal, ya que deflactar por una inflación común a todas las AFP "
    "no altera la posición relativa. El riesgo se mide como la volatilidad realizada del "
    "valor cuota y el Sharpe lo relaciona con la TPM, como complemento de lectura ajustada "
    "por riesgo. El ISA es una medida de fortaleza relativa; no constituye un rating de "
    "crédito ni una clasificación de grado-Basilea."
)
_LIMITATIONS = _LIMITATIONS_PARTIAL  # default sin rating (muestra / sin dato)


def _solvency_incorporated(rating: Optional[Dict[str, Any]]) -> bool:
    """True si el ISA emite banda absoluta para esta AFP (la solvencia está presente).
    Único criterio para elegir el encuadre honesto de los caveats/titular."""
    return bool(rating) and rating.get("score_kind") == "absolute" and bool(rating.get("band"))


def _limitations_for(rating: Optional[Dict[str, Any]]) -> str:
    """La sección Limitaciones que corresponde al estado REAL del rating."""
    return _LIMITATIONS_ABSOLUTE if _solvency_incorporated(rating) else _LIMITATIONS_PARTIAL
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
        "expansión (cerca de 15% anual). El sistema presenta un crecimiento sostenido, en el que "
        "la dispersión de rentabilidad entre administradoras —una **brecha de "
        "unos 2.8 puntos** entre la líder y la rezagada— constituye la variable competitiva "
        "relevante. La fragilidad estructural no se localiza en los retornos sino en la cobertura: "
        "la densidad de cotización permanece como el límite del modelo. Para un inversionista, "
        "las AFP representan el mayor bloque institucional del país y su crecimiento de activos "
        "determina la profundidad del mercado de capitales local."
    ),
    "pension_assessment": (
        "La AFP se ubica en una **banda de solidez Adecuada** del Índice de Solidez (ISA), "
        "sostenida por su escala (figura entre las mayores del sistema por patrimonio gestionado) "
        "y una rentabilidad alineada con el promedio. El índice integra la solvencia "
        "(patrimonio/activos de los estados financieros de las AFP publicados por SIPEN, con "
        "historia desde 2010), la rentabilidad real, el riesgo y el costo, y emite una banda "
        "absoluta de solidez además de ordenar la posición relativa entre las AFP. La principal "
        "palanca de mejora corresponde al costo relativo (comisión sobre AUM), donde se ubica por "
        "detrás de su par más eficiente."
    ),
    "peer_positioning": (
        "Frente a las siete AFP del sistema, esta administradora **lidera en escala y costo** "
        "—figura entre las mayores por patrimonio gestionado y reporta la comisión relativa más "
        "baja del grupo— pero **rezaga en rentabilidad**: su rendimiento nominal se ubica por debajo "
        "del promedio del panel, con una brecha de un par de puntos frente a la líder. En solvencia "
        "se posiciona en la parte alta, con las cifras tomadas de los estados financieros publicados "
        "por SIPEN. En términos competitivos, la administradora compite por costo y tamaño, no por "
        "retorno; su diferenciación es estructural (perfil conservador), no coyuntural."
    ),
    "portfolio_context": (
        "El ahorro previsional del sistema se encuentra **fuertemente concentrado en deuda "
        "soberana**: más de la mitad de la cartera corresponde a títulos del Ministerio de Hacienda "
        "y una porción adicional al Banco Central, lo que vincula el rendimiento del fondo al riesgo "
        "y la curva del Estado dominicano. La exposición al **sistema financiero** (bancos y "
        "asociaciones) constituye el segundo bloque —fondeo institucional a la banca—, y el resto "
        "diversifica hacia **empresas, fideicomisos y fondos de inversión** del sector real. Para el "
        "afiliado, esta composición define el perfil de riesgo de su ahorro: profundidad y seguridad "
        "soberana a cambio de una concentración elevada en un solo emisor, el Estado."
    ),
    "early_warning": (
        "Banderas de vigilancia activas —señales de monitoreo para el afiliado (complemento del "
        "ISA, no un veredicto):\n\n"
        "- **Costo elevado** (media) — comisión/AUM %: 0.86 (umbral 0.80). Comisión sobre AUM en "
        "el tramo superior del panel — menor retorno neto.\n"
        "- **Rentabilidad rezagada** (media) — rentabilidad nominal %: 7.69 (umbral 7.80). "
        "Rendimiento en el tramo inferior del panel de AFP."
    ),
    "recommendation": (
        "Para un afiliado o un comité, la lectura accionable es doble: la AFP ofrece escala y "
        "una rentabilidad sostenida en torno al promedio del sistema —consistencia, no picos—, "
        "si bien su costo relativo constituye la variable a negociar o vigilar. Con la solvencia "
        "incorporada al índice, la banda absoluta de solidez complementa la lectura de desempeño "
        "consistente y costo. La señal a seguir es la evolución del costo relativo y de la "
        "trayectoria de solvencia."
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
                          "early_warning", "recommendation", "limitations"),
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


def _pension_backtest(db: Session) -> Optional[Dict[str, Any]]:
    """Reporte de backtest persistido (op ``pension-backtest``), o None. SAVEPOINT +
    best-effort: nunca tumba el estado de validación si falta o la tabla no existe."""
    import json

    from shared.settings.models import AppSetting
    try:
        with db.begin_nested():
            row = (db.query(AppSetting)
                   .filter(AppSetting.key == "pension_backtest_report").first())
        return json.loads(row.value) if row and row.value else None
    except Exception as e:  # noqa: BLE001
        logger.warning("Backtest de pensiones no leído (uso doctrina): %s", e)
        return None


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


def _real_trend_table(trend_real: Optional[List[tuple]]) -> Optional[tuple]:
    """Trayectoria de rentabilidad REAL (deflactada por inflación BCRD): nominal vs real,
    muestreo anual + último punto. Fase 5."""
    if not trend_real or len(trend_real) < 2:
        return None
    by_year: Dict[str, tuple] = {}
    for p, nom, real in trend_real:
        by_year[str(p)[:4]] = (p, nom, real)
    pts = sorted(by_year.values())
    if trend_real[-1] not in pts:
        pts.append(trend_real[-1])
    rows = [["Período", "Nominal (anual)", "Real (deflact. BCRD)"]]
    for p, nom, real in pts[-10:]:
        rows.append([p, f"{nom:.2f}%", f"{real:+.2f}%"])
    return ("Trayectoria de rentabilidad real vs nominal (SIPEN · BCRD)", rows)


def _apply_real_return(rating: Dict[str, Any], trend: List[tuple],
                       infl: Dict[str, float]) -> Dict[str, Any]:
    """Enriquece la dimensión rentabilidad de *rating* con su retorno REAL (raw_real +
    inflación) y devuelve la trayectoria real. Presentación — NO toca score/ISA.
    Deflactar por inflación común es neutral al min-max entre pares."""
    extra: Dict[str, Any] = {}
    dim = next((d for d in rating.get("dimensions") or [] if d.get("key") == "rentabilidad"), None)
    if dim and isinstance(dim.get("raw"), (int, float)):
        i = inflation_at(infl, rating.get("period") or "")
        if i is not None:
            dim["raw_real"] = fisher_real(dim["raw"], i)
            dim["inflacion"] = round(i, 2)
            extra["inflacion_actual"] = round(i, 2)
    tr = deflate_trend(trend, infl)
    if tr:
        extra["trend_real"] = tr
    return extra


def _apply_risk_adjusted(rating: Dict[str, Any], db) -> Dict[str, Any]:
    """Enriquece la dimensión *riesgo* de *rating* con su retorno ajustado por riesgo
    (Sharpe = (retorno anualizado − TPM promedio de la ventana) / σ). Presentación — NO
    toca score/ISA (el score de riesgo es la σ; el Sharpe es lectura para la narrativa).
    Devuelve ``{sharpe}`` para el titular. Sin serie NAV o sin TPM → no anexa nada.

    Delega en ``scoring.isa.annotate_risk_adjusted`` (único origen de verdad, compartido
    con los endpoints del eje ISA) para que la web y el PDF muestren el mismo Sharpe."""
    from modules.pension_intel.scoring.isa import annotate_risk_adjusted

    return annotate_risk_adjusted(rating, db)


def _named_headline_caveat(payload: Dict[str, Any]) -> tuple:
    """Titular + caveat de portada para niveles nombrados (Insight/Deep Dive).

    Se ADAPTA al estado real del ISA (``_solvency_incorporated``): con banda absoluta el
    titular es ``ISA {score}/100 · {banda} · {AFP} · rentab. real ±X% · Sharpe Y`` y el caveat
    dice que la solvencia está incorporada; sin banda, vuelve al encuadre RELATIVO/PARCIAL con
    la solvencia como brecha. (Los tramos rentab./Sharpe solo si el dato está.) Único builder →
    la vista in-app y el PDF muestran lo mismo. ``(None, None)`` si no hay ISA (nunca fabrica)."""
    rating = payload.get("rating") or {}
    ov = rating.get("overall_score")
    if not isinstance(ov, (int, float)):
        return None, None
    rdim = next((d for d in rating.get("dimensions") or []
                 if d.get("key") == "rentabilidad"), None)
    real = (rdim or {}).get("raw_real")
    sharpe = payload.get("sharpe")
    name = rating.get("name", "AFP")
    absolute = _solvency_incorporated(rating)
    if absolute:
        headline = f"ISA {ov:.0f}/100 · {rating.get('band')} · {name}"
    else:
        headline = f"ISA {ov:.0f}/100 · {name} (relativo, parcial)"
    if isinstance(real, (int, float)):
        headline += f" · rentab. real {real:+.1f}%"
    if isinstance(sharpe, (int, float)):
        headline += f" · Sharpe {sharpe:.2f}"
    if absolute:
        caveat = ("Nota metodológica: el ISA integra la solvencia (patrimonio/activos de los "
                  "estados financieros de las AFP publicados por SIPEN, con historia desde "
                  "2010) y emite una banda absoluta de solidez, además de ordenar la posición "
                  "relativa entre las AFP. La rentabilidad se presenta en términos reales, "
                  "deflactada por la inflación del BCRD. El riesgo corresponde a la volatilidad "
                  "realizada del valor cuota (σ) y el Sharpe la relaciona con la TPM; la σ está "
                  "parcialmente atenuada por la valoración a costo amortizado de la cartera.")
    else:
        caveat = ("Nota metodológica: el ISA ofrece una lectura relativa y parcial —ordena la "
                  "posición entre las AFP con dato suficiente—. Para esta AFP la solvencia se "
                  "incorporará al publicarse sus estados financieros. La rentabilidad se "
                  "presenta en términos reales, deflactada por la inflación del BCRD. El riesgo "
                  "corresponde a la volatilidad realizada del valor cuota (σ) y el Sharpe la "
                  "relaciona con la TPM; la σ está parcialmente atenuada por la valoración a "
                  "costo amortizado de la cartera.")
    return headline, caveat


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
        n_band = sum(1 for r in results if _solvency_incorporated(r))
        fresh = self._freshness_days(db)
        detail = (f"{n_scoreable}/{len(results)} AFP calificables · "
                  + (f"solvencia incorporada · {n_band} con banda absoluta"
                     if n_band else "solvencia = brecha declarada"))
        return DataHealth(
            coverage=round(cov, 4), freshness_days=fresh, sources=("SIPEN", "ADAFP"),
            detail=detail, cadence="quarterly")

    def has_engine(self) -> bool:
        return bool(_isa_results(self._require_db()))

    def available_periods(self) -> List[str]:
        return distinct_periods(self._require_db(), PensionSnapshot.period)

    def validation_state(self) -> ValidationState:
        # G5 DIRIGIDO POR DATO: refleja (a) el estado de la solvencia (con banda o brecha) y
        # (b) el backtest de resultado-proxy persistido. Sube de 0.50 SOLO si el IC del Gini es
        # positivo (concluyente); si no, se mantiene la fuerza modesta y se declara. Sin hardcode.
        db = self._require_db()
        results = _isa_results(db)
        n_band = sum(1 for r in results if _solvency_incorporated(r))
        solv = ("con banda absoluta (solvencia incorporada de los estados financieros de SIPEN)"
                if n_band else "relativo y parcial; solvencia = brecha declarada")
        bt = _pension_backtest(db)
        if bt and bt.get("headline_gini") is not None:
            g = bt["headline_gini"]
            sig = bt.get("headline_signal")
            ci = ((bt.get("signals") or {}).get(sig) or {}).get("gini_ci") or [None, None]
            score = round(min(0.75, 0.60 + max(0.0, g) * 0.3), 2)  # soft: concluyente, no grado-regulador
            note = (f"ISA = índice de solidez {solv}. Backtest de resultado-proxy (subdesempeño "
                    f"relativo): Gini {g} (IC {ci[0]}–{ci[1]}) en la señal '{sig}'. Validación "
                    f"soft; no es grado-regulador (N acotado por el número de AFP).")
            return ValidationState(approved=True, score=score, notes=note)
        note = (f"ISA = índice de solidez {solv}. Sin validación retrospectiva concluyente: el "
                f"backtest de resultado-proxy no supera el ruido con el N disponible (se declara).")
        return ValidationState(approved=True, score=0.5, notes=note)

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
        trend = _rentabilidad_trend(db, scope, n=60)  # trayectoria mensual (hasta 5 años)
        payload: Dict[str, Any] = {
            "has_data": True, "rating": rating, "peers": results, "trend": trend,
        }
        # Retorno real (Fase 5): deflacta la rentabilidad por la inflación interanual del
        # BCRD (serie del AppSetting compartido; sin importar macro). Presentación — NO
        # muta el ISA (deflactar por inflación común es neutral al min-max entre pares).
        infl = load_inflation_series(db)
        if infl:
            payload.update(_apply_real_return(rating, trend, infl))
        # Retorno ajustado por riesgo (Diferido B): Sharpe = (retorno − TPM) / σ, con la TPM
        # del BCRD como tasa libre (serie del AppSetting compartido). Presentación — NO muta.
        payload.update(_apply_risk_adjusted(rating, db))
        if tier == ProductTier.deep_dive:
            payload["cartera"] = _system_cartera(db)  # contexto de riesgo (dónde invierte el fondo)
        # Titular + caveat de portada (ISA · rentab. real · Sharpe + caveat de σ/costo
        # amortizado): se stashean en el payload para que la vista in-app muestre lo mismo
        # que la portada del PDF. Un solo builder → paridad web↔PDF por construcción.
        headline, caveat = _named_headline_caveat(payload)
        if headline:
            payload["headline_line"] = headline
        if caveat:
            payload["caveat"] = caveat
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
            "slug": "afp_ejemplo", "name": "AFP Ejemplo", "overall_score": 62.4,
            "score_kind": "absolute", "band": "Adecuada", "coverage": 1.0, "period": "2025",
            "dimensions": [
                {"key": "solvencia", "label": "Solvencia (patrimonio/activos)", "weight": 0.35,
                 "provenance": "real", "present": True, "raw": 0.8435, "score": 63.4},
                {"key": "rentabilidad", "label": "Rentabilidad", "weight": 0.25,
                 "provenance": "real", "present": True, "raw": 9.59, "score": 51.6},
                {"key": "riesgo", "label": "Consistencia / Riesgo (volatilidad)", "weight": 0.15,
                 "provenance": "real", "present": True, "raw": 1.64, "score": 55.5},
                {"key": "escala", "label": "Escala (fondos administrados / AUM)", "weight": 0.15,
                 "provenance": "real", "present": True, "raw": 428449.7, "score": 98.0},
                {"key": "costo", "label": "Costo (comisión/AUM)", "weight": 0.10,
                 "provenance": "real", "present": True, "raw": 0.00885, "score": 42.0},
            ],
        }
        peers = [rating,
                 {"slug": "afp_b", "name": "AFP Beta", "overall_score": 71.2, "coverage": 1.0,
                  "score_kind": "absolute", "band": "Adecuada",
                  "dimensions": [{"key": "solvencia", "score": 60.0}, {"key": "rentabilidad", "score": 80.0},
                                 {"key": "escala", "score": 55.0}, {"key": "costo", "score": 70.0}]},
                 {"slug": "afp_c", "name": "AFP Gamma", "overall_score": 48.3, "coverage": 1.0,
                  "score_kind": "absolute", "band": "En vigilancia",
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
        return {sec: (_LIMITATIONS_ABSOLUTE if sec == "limitations" else _SAMPLE_NARRATIVES[sec])
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
        # Trayectoria REAL (deflactada BCRD, Fase 5) cuando hay serie de inflación.
        trend_real = snapshot.payload.get("trend_real") or []
        if trend_real:
            base_ctx["trayectoria_rentabilidad_real"] = [
                {"periodo": p, "nominal": nom, "real": real} for p, nom, real in trend_real[-12:]]
        cartera = snapshot.payload.get("cartera")
        out: Dict[str, str] = {}
        for section in sections:
            if section == "limitations":
                out["limitations"] = _limitations_for(rating)
                continue
            if section == "early_warning":
                # Banderas deterministas + párrafo IA que LEE EL PATRÓN (alimentado SOLO por
                # las banderas → numeric_guard). Sin DB (muestra) o sin motor: solo bullets.
                if self._db is None:
                    out["early_warning"] = _SAMPLE_NARRATIVES["early_warning"]
                    continue
                from modules.pension_intel.early_warning import afp_alerts, format_alerts_text
                blk = afp_alerts(self._db, rating.get("slug"))
                bullets = format_alerts_text(blk)
                flags = blk.get("alerts") or []
                interp = ""
                if flags:
                    try:
                        res = await narrative_engine.generate(
                            context={"entity": entity,
                                     "dominio": "pensiones — banderas de vigilancia para el afiliado",
                                     "flags": flags},
                            template="early_warning_reading", mode="standard",
                            axis="pension_intel", audience="inversionista")
                        if res.model_used != "static_fallback":
                            interp = (res.text or "").strip()
                    except Exception:  # noqa: BLE001 — la sección nunca depende del motor IA
                        interp = ""
                out["early_warning"] = (interp + "\n\n" + bullets) if interp else bullets
                continue
            if section == "peer_positioning":
                res = await narrative_engine.generate(
                    context=pension_peer_context(entity, rating, peers),
                    template="pension_peer_positioning",
                    mode=section_mode(tier, section, sections),
                    axis="pension_intel", audience="inversionista")
                out[section] = res.text
                continue
            if section == "portfolio_context":
                if not cartera or not cartera.get("found"):
                    out[section] = _NO_CARTERA
                    continue
                res = await narrative_engine.generate(
                    context=pension_cartera_context(cartera),
                    template="pension_portfolio_context",
                    mode=section_mode(tier, section, sections),
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
                context=ctx,
                template="sector_decision" if section == "recommendation" else "pension_entity",
                mode=section_mode(tier, section, sections),
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
        charts: List = []
        headline: Optional[str] = None
        subtitle: Optional[str] = None
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
            if isinstance(cci, (int, float)):
                headline = (f"Rentabilidad CCI {cci:.1f}% (nominal)"
                            + (f" · brecha {spread:.2f} pp entre AFP"
                               if isinstance(spread, (int, float)) else ""))
        elif payload.get("has_data"):
            rating = payload.get("rating") or {}
            rows = [["Dimensión", "Peso", "Score", "Procedencia"]]
            for d in rating.get("dimensions") or []:
                score = "—" if d.get("score") is None else f"{d['score']:.0f}"
                rows.append([d["label"], f"{d['weight']*100:.0f}%", score, d["provenance"]])
            _isa_title = ("Desglose del ISA (banda absoluta + posición relativa)"
                          if _solvency_incorporated(rating) else "Desglose del ISA (relativo, parcial)")
            tables.append((_isa_title, rows))
            # Gráfico SOLO de las dimensiones con dato real (las 'brecha' van nulas → se omiten,
            # honestidad: no se grafica una dimensión sin medir).
            present = [(d["label"], d.get("score")) for d in (rating.get("dimensions") or [])
                       if isinstance(d.get("score"), (int, float))]
            if len(present) >= 2:
                charts.append({"title": "Dimensiones del ISA con dato (score 0-100)",
                               "items": present})
            # Titular (ISA · rentab. real · Sharpe) y caveat de portada: mismos strings que
            # la vista in-app, stasheados en el payload por `snapshot()` (paridad web↔PDF).
            # Fallback al builder para las muestras sintéticas, que no pasan por `snapshot()`.
            headline = payload.get("headline_line")
            subtitle = payload.get("caveat")
            if headline is None and subtitle is None:
                headline, subtitle = _named_headline_caveat(payload)
            # Profundidad: pares, trayectoria (real vs nominal si hay inflación) y cartera.
            trend_tbl = (_real_trend_table(payload.get("trend_real"))
                         or _trend_table(payload.get("trend")))
            for tbl in (_peer_table(payload.get("peers")), trend_tbl):
                if tbl:
                    tables.append(tbl)
            if tier == ProductTier.deep_dive:
                cart = _cartera_table(payload.get("cartera"))
                if cart:
                    tables.append(cart)
        return render_product_pdf(
            sector_key=SECTOR_KEY, display_name=display, title=title,
            period=snapshot.period, narratives=narratives,
            section_titles=_SECTION_TITLES, tables=tables, charts=charts, headline=headline,
            subtitle=subtitle, watermark=level.watermark, sample=sample,
            output_dir=output_dir, fmt=fmt)


register_product(SECTOR_KEY, lambda db: PensionProduct(db))
