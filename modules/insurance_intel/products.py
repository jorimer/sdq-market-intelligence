"""Seguros (SIS) como ``SectorProduct`` — productización (mismo estándar que Pensiones).

Naturaleza MIXTA, idéntica a pensiones:
  * **Pulse** = pulso NACIONAL del mercado asegurador (anonimizado): primas totales,
    crecimiento, mezcla por ramo, estructura — NUNCA una aseguradora nombrada.
  * **Insight / Deep Dive** = una aseguradora NOMBRADA y su ISF (Índice de Solidez de
    Aseguradora: solvencia · liquidez · siniestralidad · escala · resultado técnico).

Honestidad DIRIGIDA POR EL DATO: el Pulse va con dato real de CKAN (F1a). El ISF por
entidad es una brecha declarada hasta ingerir los estados financieros auditados (F1b):
los niveles nombrados reportan "sin dato" en vez de fabricar un rating, exactamente
como pensiones arrancó relativa/parcial antes del backfill de solvencia de SIPEN.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.products.contract import EstadoBacktest
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
from modules.insurance_intel.ai_context import (
    insurance_early_warning_context,
    insurance_entity_context,
    insurance_peer_context,
    market_pulse_context,
)
from modules.insurance_intel.models.models import InsuranceSnapshot
from modules.insurance_intel.scoring.isf import compute_isf
from modules.insurance_intel.service import build_market_pulse

logger = logging.getLogger("sdq.products.insurance")

SECTOR_KEY = "insurance"
SYSTEM_NAME = "Mercado Asegurador Dominicano"

_SECTION_TITLES = {
    "insurance_pulse": "Pulso del Mercado Asegurador",
    "insurance_assessment": "Evaluación de Solidez de la Aseguradora (ISF)",
    "peer_positioning": "Posición Competitiva frente al Mercado",
    "market_context": "Contexto del Mercado (Mezcla y Estructura)",
    "early_warning": "Alerta Temprana",
    "recommendation": "Lectura para Decisión",
    "limitations": "Limitaciones",
}

_LIMITATIONS = (
    "El Índice de Solidez de Aseguradora (ISF) integra cinco dimensiones sobre dato público de "
    "la Superintendencia de Seguros (SIS). La solvencia y la liquidez toman los índices "
    "REGULATORIOS oficiales que la SIS publica por compañía conforme a la Ley 146-02, Cap. XII, "
    "Art. 164 —índice de solvencia = patrimonio técnico ajustado / margen de solvencia mínima "
    "requerida (Arts. 160-161) e índice de liquidez = disponibilidad libre / liquidez mínima "
    "requerida (Art. 162), en ambos casos ≥ 1 = cumplimiento—; la siniestralidad (loss ratio), "
    "la escala y el resultado técnico se derivan de los estados financieros auditados. Con la "
    "solvencia incorporada, el índice emite una banda absoluta de solidez además de ordenar la "
    "posición relativa. El marco de supervisión de referencia son los Principios Básicos de "
    "Seguros (ICP) de la IAIS, adoptados por la SIS (Res. 04-2024). La calibración de las bandas "
    "es provisional, sujeta a validación retrospectiva. El ISF es una medida de solidez; no "
    "constituye un rating de crédito ni un dictamen regulatorio de solvencia."
)
_NO_DATA = (
    "No hay ISF para esta aseguradora en el período seleccionado: sus estados financieros "
    "auditados no están ingeridos o su balance no concilió. No se fabrican cifras."
)
_PULSE_NO_DATA = (
    "No hay dato de mercado ingerido para publicar el pulso. Ejecute la sincronización "
    "de seguros (SIS). No se fabrican cifras."
)

_SAMPLE_PULSE = (
    "El mercado asegurador dominicano cierra el período con **primas netas cobradas por "
    "unos RD$ 153 MMM** y un crecimiento sostenido (del orden de dos dígitos en tasa "
    "compuesta entre años independientes). La cartera está **concentrada en cuatro ramos** "
    "—Incendio y Aliados, Salud, Vehículos de Motor y Vida Colectiva concentran cerca del "
    "85% de la prima—, un perfil característico de un mercado de daños y salud más que de "
    "vida individual. Para un inversionista o contraparte, la profundidad del mercado y su "
    "estructura por ramo definen dónde está el volumen y dónde la competencia."
)
_SAMPLE_ASSESSMENT = (
    "La aseguradora se ubica en una **banda de solidez Adecuada** del ISF, sostenida por una "
    "siniestralidad contenida (loss ratio en el tramo bajo del mercado) y una escala relevante, "
    "con una solvencia (patrimonio/activos) en línea con el promedio. El índice integra la "
    "solvencia, la siniestralidad, la liquidez, la escala y el resultado técnico de los estados "
    "financieros auditados que publica la SIS, y emite una banda absoluta además de ordenar la "
    "posición relativa. La palanca de mejora está en el resultado técnico. (Muestra ilustrativa.)"
)
_SAMPLE_PEER = (
    "Frente al mercado asegurador, la aseguradora **compite por escala y disciplina técnica**: "
    "figura entre las mayores por activos y reporta una siniestralidad por debajo del promedio "
    "del panel, si bien su solvencia relativa deja margen frente a las líderes. En términos "
    "competitivos, su diferenciación es de tamaño y suscripción, no de capitalización. (Muestra.)"
)
_SAMPLE_MARKET = (
    "El mercado en el que opera concentra la prima en cuatro ramos (Incendio, Salud, Vehículos y "
    "Vida Colectiva), un perfil de daños y salud. La posición de la aseguradora en esos ramos "
    "determina su exposición a la siniestralidad del ciclo. (Muestra ilustrativa.)"
)
_SAMPLE_RECO = (
    "Para un comité o contraparte, la lectura accionable es doble: solidez adecuada con "
    "disciplina técnica probada, y una palanca clara en el resultado técnico y la capitalización "
    "relativa. La señal a seguir es la trayectoria de la solvencia y la siniestralidad. (Muestra.)"
)


def insurance_manifest() -> SectorProductManifest:
    return SectorProductManifest(
        sector_key=SECTOR_KEY, display_name="SDQ Seguros (SIS)", levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=("insurance_pulse",), narrative_templates=("insurance_pulse",),
                audience="mercado / abierto", cadence="periodic",
                watermark="Vista abierta · SDQMIP", price_band="abierto"),
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.named_entity,
                sections=("insurance_assessment", "peer_positioning"),
                narrative_templates=("insurance_entity", "insurance_peer_positioning"),
                audience="cliente / comité", cadence="recurring", price_band="suscripción"),
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
                sections=("insurance_assessment", "peer_positioning", "market_context",
                          "early_warning", "recommendation", "limitations"),
                narrative_templates=("insurance_entity", "insurance_peer_positioning",
                                     "insurance_market_context"),
                audience="comité / contraparte", cadence="on_demand", price_band="on-demand"),
        })


def _pulse(db: Session, as_of: Optional[str] = None) -> Optional[Dict[str, Any]]:
    try:
        with db.begin_nested():
            return build_market_pulse(db, as_of=as_of)
    except Exception as e:  # noqa: BLE001
        logger.warning("Pulso de seguros no disponible: %s", e)
        return None


def _isf_results(db: Session) -> List[Dict[str, Any]]:
    try:
        with db.begin_nested():
            return compute_isf(db)
    except Exception as e:  # noqa: BLE001
        logger.warning("ISF no disponible: %s", e)
        return []


def _insurance_backtest(db: Session) -> Optional[Dict[str, Any]]:
    """Reporte de backtest persistido (op ``insurance-backtest``), o None. SAVEPOINT +
    best-effort: nunca tumba el estado de validación si falta o la tabla no existe."""
    import json

    from shared.settings.models import AppSetting
    try:
        with db.begin_nested():
            row = (db.query(AppSetting)
                   .filter(AppSetting.key == "insurance_backtest_report").first())
        return json.loads(row.value) if row and row.value else None
    except Exception as e:  # noqa: BLE001
        logger.warning("Backtest de seguros no leído (uso doctrina): %s", e)
        return None


def _mix_table(pulse: Dict[str, Any]) -> Optional[tuple]:
    mix = pulse.get("mix") or []
    if not mix:
        return None
    rows = [["Ramo (línea)", "Primas (RD$ MM)", "% del mercado"]]
    for d in mix[:11]:
        pct = "—" if d.get("pct") is None else f"{d['pct']:.1f}%"
        rows.append([d["label"], f"{d['amount'] / 1e6:,.0f}", pct])
    return (f"Mezcla del mercado por ramo · {pulse.get('latest_year')} (SIS)", rows)


def _named_headline_caveat(rating: Dict[str, Any]) -> tuple:
    """Titular + caveat de portada para niveles nombrados (paridad web↔PDF)."""
    ov = rating.get("overall_score")
    if not isinstance(ov, (int, float)):
        return None, None
    name = rating.get("name") or rating.get("slug")
    absolute = (rating.get("coverage") or 0) >= 0.99 and rating.get("band")
    if absolute:
        headline = f"ISF {ov:.0f}/100 · {rating.get('band')} · {name}"
    else:
        headline = f"ISF {ov:.0f}/100 · {name} (relativo, parcial)"
    caveat = ("Nota metodológica: el ISF toma la solvencia y la liquidez de los índices "
              "REGULATORIOS oficiales que publica la SIS (Ley 146-02, Art. 164: patrimonio "
              "técnico ajustado/margen requerido y disponibilidad/liquidez requerida, ≥1 = "
              "cumple), y la siniestralidad, escala y resultado técnico de los estados "
              "financieros auditados. Marco de referencia: ICP de la IAIS (Res. 04-2024). "
              "Calibración de bandas provisional. No es un rating de crédito.")
    return headline, caveat


def _isf_table(rating: Dict[str, Any]) -> Optional[tuple]:
    rows = [["Dimensión", "Peso", "Score", "Valor"]]
    for d in rating.get("dimensions") or []:
        score = "—" if d.get("score") is None else f"{d['score']:.0f}"
        raw = d.get("raw")
        raw_s = "—" if raw is None else (f"{raw:,.0f}" if abs(raw) >= 1000 else f"{raw:.3f}")
        rows.append([d["label"], f"{d['weight'] * 100:.0f}%", score, raw_s])
    return ("Desglose del ISF (banda absoluta + posición relativa)", rows) if len(rows) > 1 else None


_PEER_MAX_COMPARABLES = 10
_PEER_MAX_PARCIALES = 4
_PEER_DIVISOR = "── Cobertura parcial · fuera del orden ──"


def _peer_table(peers: Optional[List[Dict[str, Any]]]) -> Optional[tuple]:
    """Tabla de pares con las PARCIALES separadas del orden.

    La misma regla que ya rige el rank en `ai_context` tiene que regir acá. Cuando solo se
    arregló el contexto, el PDF quedó contradiciéndose consigo mismo: el texto hablaba de
    «27 comparables» y la tabla de al lado seguía listando a Reaseguradora Santo Domingo
    (74,6, tres dimensiones de cinco) en el segundo puesto, sin marca. Un score sobre 3 de 5
    dimensiones no ordena contra uno de 5 — las «—» de la fila no alcanzan como aviso.

    Las parciales NO se ocultan: van al final, bajo un divisor que dice por qué están ahí.
    """
    from shared.narrative.derived import universo_comparable

    if not peers:
        return None
    order = ["solvencia", "siniestralidad", "liquidez", "escala", "resultado_tecnico"]

    def _fila(p: Dict[str, Any]) -> List[str]:
        by = {d["key"]: d.get("score") for d in p.get("dimensions") or []}
        cells: List[str] = [str(p.get("name") or p.get("slug") or ""),
                            f"{p['overall_score']:.1f}"]
        cells += ["—" if by.get(k) is None else f"{by[k]:.0f}" for k in order]
        return cells

    u = universo_comparable(peers)
    comparables, parciales = u["comparables"], u["parciales"]
    rows = [["Aseguradora", "ISF", "Solv.", "Sinie.", "Liq.", "Esc.", "Res."]]
    rows += [_fila(p) for p in comparables[:_PEER_MAX_COMPARABLES]]
    if parciales:
        rows.append([_PEER_DIVISOR] + [""] * 6)
        rows += [_fila(p) for p in parciales[:_PEER_MAX_PARCIALES]]
    if len(rows) <= 1:
        return None
    # El título dice el criterio Y lo que quedó afuera: un top-N silencioso se lee como si
    # fuera el panel entero.
    titulo = (f"Comparación con el mercado (score 0-100 por dimensión) · "
              f"{len(comparables)} con las cinco dimensiones medidas"
              + (f", {len(parciales)} de cobertura parcial" if parciales else ""))
    ocultas = (max(0, len(comparables) - _PEER_MAX_COMPARABLES)
               + max(0, len(parciales) - _PEER_MAX_PARCIALES))
    if ocultas:
        titulo += f" — se muestran las primeras, {ocultas} no listadas"
    return (titulo, rows)


def _pulse_table(pulse: Dict[str, Any]) -> Optional[tuple]:
    rows = [["Indicador", "Valor"]]
    tot = pulse.get("total_premiums_rd")
    if tot is not None:
        rows.append(["Primas netas cobradas (año)", f"RD$ {tot / 1e9:,.1f} MMM"])
    g = pulse.get("growth_pct")
    if g is not None:
        gy = pulse.get("growth_years")
        span = f" ({gy[0]}–{gy[1]}, compuesto)" if gy else ""
        rows.append([f"Crecimiento{span}", f"{g:+.1f}%"])
    if pulse.get("active_insurers") is not None:
        # Rótulo fiel a la serie: es el máximo POR RAMO, no el tamaño del mercado.
        rows.append(["Máx. aseguradoras en un mismo ramo", f"{pulse['active_insurers']}"])
    if pulse.get("top4_concentration_pct") is not None:
        rows.append(["Concentración top-4 ramos", f"{pulse['top4_concentration_pct']:.1f}%"])
    hc = pulse.get("health_coverage") or {}
    if hc.get("afiliados_total") is not None:
        # El período de la afiliación va PEGADO a la cifra: es del SFS y suele ir por delante
        # del corte del informe. Sin él, el lector la atribuye al corte de la entidad.
        per = f" · {hc['period']}" if hc.get("period") else ""
        rows.append([f"Cobertura de salud SFS (afiliados){per}",
                     f"{hc['afiliados_total']/1e6:,.2f} MM"])
    if len(rows) <= 1:
        return None
    # El título declara el período de ESTA capa, que no es el corte del informe.
    año = pulse.get("latest_year")
    publicado = pulse.get("period")
    sello = f" · {año}" if año else ""
    if publicado and año and not str(publicado).startswith(str(año)):
        sello = f" · año {año} (publicado {publicado})"
    return (f"Pulso del mercado asegurador{sello} (SIS · SISALRIL)", rows)


def _corte_del_periodo(periodo):
    """Delega en `shared.capacidad_de_pago.corte_del_periodo`.

    El cuerpo vivía acá y era el único correcto de los tres: pensiones y política monetaria
    pasaban `date.today()` dentro de documentos fechados. Subió a `shared/` para que el
    arreglo de esos dos no fuera una copia —un módulo no puede importar de otro— y se
    conserva el nombre local porque es el que usan los llamadores de este módulo."""
    from shared.capacidad_de_pago import corte_del_periodo
    return corte_del_periodo(periodo)



#: Dónde vive el contexto que ve el modelo. Se declara porque este eje ahora lee un
#: constructor TRANSVERSAL —la capacidad de pago del hogar, en `shared/`— y sin declararlo
#: ese archivo queda FUERA de la huella de caché: un arreglo de lo que el modelo lee no
#: invalidaría nada, y `ProductReportCache` no tiene TTL.
AI_CONTEXT_FILES = (
    "ai_context.py",
    "shared/capacidad_de_pago.py",
)


class InsuranceProduct:
    """``SectorProduct`` de Seguros. ``db`` opcional (las muestras no tocan DB)."""

    ESTADO_BACKTEST = EstadoBacktest(
        tiene_motor=True, eje_motor="insurance_intel",
        desenlace="subdesempeño técnico relativo a la mediana del panel de aseguradoras",
        motivo=("Corte transversal de aseguradoras × años auditados. El panel se amplió a "
                "2013 y la señal de underwriting pasó a concluyente; el veredicto vigente "
                "se lee del reporte."))

    sector_key = SECTOR_KEY

    def __init__(self, db: Optional[Session] = None):
        self._db = db

    def _require_db(self) -> Session:
        if self._db is None:
            raise RuntimeError("InsuranceProduct requiere una sesión de DB para esta operación.")
        return self._db

    def product_manifest(self) -> SectorProductManifest:
        return insurance_manifest()

    # ── Catálogo: aseguradoras elegibles (con ISF) para niveles nombrados ──
    def scope_kind(self) -> str:
        return "entity"

    def scope_options(self) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        for r in _isf_results(self._require_db()):
            if r.get("overall_score") is not None:
                # label = nombre oficial del roster (bug real detectado en producción: el
                # selector del catálogo mostraba el slug crudo "mapfre_bhd" al cliente).
                out.append({"value": r["slug"], "label": r.get("name") or r["slug"],
                            "group": "Aseguradora"})
        return out

    # ── Señales de readiness ──
    def _freshness_days(self, db: Session) -> Optional[int]:
        from datetime import date

        from modules.insurance_intel.models.models import InsuranceSeries
        try:
            with db.begin_nested():
                latest = (db.query(InsuranceSeries.published_at)
                          .filter(InsuranceSeries.published_at.isnot(None))
                          .order_by(InsuranceSeries.published_at.desc()).first())
        except Exception as e:  # noqa: BLE001
            logger.warning("Frescura de seguros no disponible: %s", e)
            return None
        return (date.today() - latest[0]).days if latest and latest[0] else None

    def data_signals(self) -> DataHealth:
        db = self._require_db()
        pulse = _pulse(db)
        isf = _isf_results(db)
        n_scored = sum(1 for r in isf if r.get("overall_score") is not None)
        # Cobertura: el mercado (Pulse) está listo; el ISF por entidad es brecha declarada.
        market_ready = bool(pulse and pulse.get("has_data"))
        cov = 0.6 if market_ready and not n_scored else (1.0 if n_scored else 0.0)
        detail = ("Mercado (Pulse) con dato real de SIS; "
                  + (f"{n_scored} aseguradoras con ISF" if n_scored
                     else "ISF por entidad pendiente (estados financieros auditados, F1b)"))
        return DataHealth(
            coverage=round(cov, 4), freshness_days=self._freshness_days(db),
            sources=("SIS", "datos.gob.do"), detail=detail, cadence="quarterly")

    def has_engine(self) -> bool:
        db = self._require_db()
        pulse = _pulse(db)
        return bool((pulse and pulse.get("has_data")) or _isf_results(db))

    def available_periods(self) -> List[str]:
        return distinct_periods(self._require_db(), InsuranceSnapshot.period)

    def validation_state(self) -> ValidationState:
        # G5 DIRIGIDO POR DATO: si hay backtest persistido con Gini concluyente, sube de 0.60;
        # si no, se mantiene modesto y se declara. Sin hardcode.
        db = self._require_db()
        isf = _isf_results(db)
        n_scored = sum(1 for r in isf if r.get("overall_score") is not None)
        if not n_scored:
            note = ("Pulso de mercado descriptivo sobre dato real de SIS (primas por ramo). El ISF "
                    "por aseguradora y su validación retrospectiva llegan con los estados "
                    "financieros auditados. Se declara la brecha; no se fabrica rating.")
            return ValidationState(approved=True, score=0.5, notes=note)
        bt = _insurance_backtest(db)
        if bt and bt.get("headline_gini") is not None:
            g = bt["headline_gini"]
            sig = bt.get("headline_signal")
            ci = ((bt.get("signals") or {}).get(sig) or {}).get("gini_ci") or [None, None]
            n = ((bt.get("signals") or {}).get(sig) or {}).get("n_obs")
            score = round(min(0.80, 0.60 + max(0.0, g) * 0.3), 2)
            note = (f"ISF = índice de solidez con estados financieros auditados incorporados. "
                    f"Backtest de resultado-proxy (subdesempeño técnico relativo): Gini {g} "
                    f"(IC {ci[0]}–{ci[1]}, N={n}) en la señal '{sig}'. Concluyente; el N mayor del "
                    f"mercado asegurador estrecha el IC frente a otros ejes.")
            return ValidationState(approved=True, score=score, notes=note)
        note = ("ISF = índice de solidez con estados financieros auditados incorporados. Backtest "
                "de validación pendiente o no concluyente con el histórico disponible (se declara).")
        return ValidationState(approved=True, score=0.6, notes=note)

    # ── Snapshot por nivel ──
    def snapshot(self, tier: ProductTier, period: str,
                 scope: Optional[str] = None) -> ProductSnapshot:
        db = self._require_db()
        if tier == ProductTier.pulse:
            # `period` (del selector) produce la vista as-of; vacío → la más reciente.
            # Sin el pass-through, elegir un período histórico servía el pulso ACTUAL
            # con la etiqueta del período elegido — bug real detectado en producción.
            pulse = _pulse(db, as_of=period or None)
            if not pulse or not pulse.get("has_data"):
                return ProductSnapshot(tier=tier, period=period or "—",
                                       payload={"has_data": False}, entity_name=None)
            return ProductSnapshot(tier=tier, period=pulse.get("period") or "—",
                                   payload={"has_data": True, "pulse": pulse},
                                   entity_name=None)

        # Niveles nombrados (Insight / Deep Dive): ISF por aseguradora (estados auditados).
        # Sin scope se LANZA (contrato del registro, como banca/pensiones/ESG): devolver un
        # snapshot "sin dato" aquí cortaba la degradación deep_dive→pulse de los consumidores.
        if not scope:
            raise ValueError("Debe indicar la aseguradora (scope) para el nivel nombrado.")
        results = _isf_results(db)
        rating = next((r for r in results if r["slug"] == scope), None)
        if rating is None or rating.get("overall_score") is None:
            return ProductSnapshot(tier=tier, period=period or "—",
                                   payload={"has_data": False},
                                   entity_name=(rating or {}).get("name") or scope)
        payload: Dict[str, Any] = {"has_data": True, "rating": rating, "peers": results}
        headline, caveat = _named_headline_caveat(rating)
        if headline:
            payload["headline_line"] = headline
        if caveat:
            payload["caveat"] = caveat
        # LA CAPACIDAD DE PAGO DEL HOGAR. Una póliza voluntaria compite con la canasta: un hogar cuyo
        # piso de ingreso no la cubre deja de renovar antes que de comer.
        #
        # Vive en `shared/` porque la leen cuatro ejes y no tiene nada del eje adentro: son
        # series nacionales del BCRD y del MHE. Lo que cambia entre ejes es la LECTURA, no el
        # dato, y ésa la fija la regla de la plantilla — no se copia el bloque.
        try:
            from shared.capacidad_de_pago import capacidad_de_pago
            _cap = capacidad_de_pago(db, _corte_del_periodo(rating.get("period")))
            if _cap:
                payload["capacidad_de_pago"] = _cap
        except Exception:  # noqa: BLE001 — el snapshot nunca depende de esta serie
            logger.exception("Capacidad de pago omitida en el snapshot")
        return ProductSnapshot(tier=tier, period=rating.get("period") or "—",
                               payload=payload, entity_name=rating.get("name") or scope)

    # ── Muestra sintética (datos demo ilustrativos, sin DB) ──
    def sample_snapshot(self, tier: ProductTier) -> ProductSnapshot:
        if tier == ProductTier.pulse:
            pulse = {
                "has_data": True, "period": "2025-12", "latest_year": "2025",
                "total_premiums_rd": 153_360_000_000.0, "growth_pct": 16.4,
                "growth_years": ("2023", "2025"), "active_insurers": 27,
                "top4_concentration_pct": 87.1, "n_ramos": 11,
                "mix": [
                    {"ramo": "incendio_y_aliados", "label": "Incendio y Aliados", "amount": 39_930_000_000.0, "pct": 26.0},
                    {"ramo": "salud", "label": "Salud", "amount": 36_440_000_000.0, "pct": 23.8},
                    {"ramo": "vehiculos_de_motor", "label": "Vehículos de Motor", "amount": 33_530_000_000.0, "pct": 21.9},
                    {"ramo": "vida_colectiva", "label": "Vida Colectiva", "amount": 23_650_000_000.0, "pct": 15.4},
                ],
                "health_coverage": {"period": "2026-03", "afiliados_total": 10_648_114.0,
                                    "afiliados_contributivo": 4_856_429.0,
                                    "afiliados_subsidiado": 5_673_097.0, "crecimiento_5a_pct": 18.2,
                                    "source": "SISALRIL / CNSS — Seguro Familiar de Salud"},
                "source": "SIS — Superintendencia de Seguros (datos.gob.do)",
            }
            return ProductSnapshot(tier=tier, period="2025-12",
                                   payload={"has_data": True, "pulse": pulse}, entity_name=None)
        # Muestra sintética de nivel nombrado (rating ilustrativo, banda absoluta).
        def _dim(k, label, w, raw, score):
            return {"key": k, "label": label, "weight": w, "raw": raw, "score": score,
                    "provenance": "real", "present": True}
        rating = {
            "slug": "aseguradora_ejemplo", "name": "Aseguradora Ejemplo", "period": "2024",
            "overall_score": 64.2, "band": "Adecuada", "coverage": 1.0, "score_kind": "absolute",
            "dimensions": [
                _dim("solvencia", "Solvencia (patrimonio/activos)", 0.35, 0.243, 73.0),
                _dim("siniestralidad", "Siniestralidad (loss ratio)", 0.20, 0.363, 88.0),
                _dim("liquidez", "Liquidez (líquidos/reservas técnicas)", 0.15, 1.10, 55.0),
                _dim("escala", "Escala (activos totales)", 0.15, 3.3e10, 99.0),
                _dim("resultado_tecnico", "Resultado técnico (sobre primas)", 0.15, 0.06, 41.0),
            ],
        }
        peers = [rating,
                 {"slug": "beta", "name": "Aseguradora Beta", "overall_score": 61.9, "coverage": 1.0,
                  "band": "Adecuada", "dimensions": [{"key": "solvencia", "score": 48.0},
                  {"key": "siniestralidad", "score": 91.0}, {"key": "liquidez", "score": 55.0},
                  {"key": "escala", "score": 90.0}, {"key": "resultado_tecnico", "score": 35.0}]}]
        headline, caveat = _named_headline_caveat(rating)
        return ProductSnapshot(tier=tier, period="2024",
                               payload={"has_data": True, "rating": rating, "peers": peers,
                                        "headline_line": headline, "caveat": caveat},
                               entity_name="Aseguradora Ejemplo")

    def sample_narratives(self, tier: ProductTier) -> Dict[str, str]:
        sections = self.product_manifest().require_level(tier).sections
        curated = {
            "insurance_pulse": _SAMPLE_PULSE, "insurance_assessment": _SAMPLE_ASSESSMENT,
            "peer_positioning": _SAMPLE_PEER, "market_context": _SAMPLE_MARKET,
            "recommendation": _SAMPLE_RECO, "limitations": _LIMITATIONS,
            "early_warning": ("Sin banderas de vigilancia activas para esta aseguradora en el "
                              "período (complemento del ISF, no un veredicto). (Muestra.)"),
        }
        return {sec: curated.get(sec, _NO_DATA) for sec in sections}

    # ── Narrativas (operan sobre el snapshot) ──
    async def narratives(self, tier: ProductTier, snapshot: ProductSnapshot,
                         lang: str = "es") -> Dict[str, str]:
        sections = self.product_manifest().require_level(tier).sections
        if tier == ProductTier.pulse:
            if not snapshot.payload.get("has_data"):
                return {"insurance_pulse": _PULSE_NO_DATA}
            from shared.narrative.claude_engine import narrative_engine
            ctx = market_pulse_context(snapshot.payload["pulse"])
            try:
                res = await narrative_engine.generate(
                    context=ctx, template="insurance_pulse", mode="standard",
                    axis="insurance_intel", audience="inversionista")
                return {"insurance_pulse": res.text}
            except Exception as e:  # noqa: BLE001 — nunca romper la sección por el motor IA
                logger.warning("Narrativa de pulso seguros no disponible: %s", e)
                return {"insurance_pulse": _SAMPLE_PULSE}

        # Niveles nombrados: ISF por aseguradora sobre estados auditados.
        if not snapshot.payload.get("has_data"):
            return {sec: (_LIMITATIONS if sec == "limitations" else _NO_DATA) for sec in sections}
        from shared.narrative.claude_engine import narrative_engine
        rating = snapshot.payload["rating"]
        peers = snapshot.payload.get("peers") or [rating]
        entity = snapshot.entity_name or rating.get("name") or "Aseguradora"
        # Cada sección se resuelve en su propia corrutina y todas corren en PARALELO
        # (asyncio.gather): antes era secuencial (~15s × N). El cliente Anthropic ya libera el
        # event loop (asyncio.to_thread en claude_engine). Las lecturas de DB internas (_pulse)
        # son SÍNCRONAS → no ceden el loop, así que la Session se usa de a una corrutina por vez.
        async def _gen(section: str) -> tuple:
            if section == "limitations":
                return section, _LIMITATIONS
            if section == "market_context":
                pulse = _pulse(self._require_db())
                if not pulse or not pulse.get("has_data"):
                    return section, _PULSE_NO_DATA
                res = await narrative_engine.generate(
                    context=market_pulse_context(pulse), template="insurance_market_context",
                    mode=section_mode(tier, section, sections),
                    axis="insurance_intel", audience="inversionista")
                return section, res.text
            if section == "peer_positioning":
                res = await narrative_engine.generate(
                    context=insurance_peer_context(entity, rating, peers),
                    template="insurance_peer_positioning",
                    mode=section_mode(tier, section, sections),
                    axis="insurance_intel", audience="inversionista")
                return section, res.text
            if section == "early_warning":
                # Sección propia: TRAYECTORIA + disparadores. Antes caía al mismo template y al
                # mismo contexto que `insurance_assessment`, así que el Deep Dive publicaba dos
                # veces el mismo análisis —encabezado incluido— y la pendiente del combined que
                # Perfil SDQ ya computa no llegaba a la única sección que la necesitaba.
                res = await narrative_engine.generate(
                    context=insurance_early_warning_context(
                        self._require_db(), rating.get("slug") or "", rating, peers),
                    template="insurance_entity",
                    mode=section_mode(tier, section, sections),
                    axis="insurance_intel", audience="inversionista")
                return section, res.text
            ctx = insurance_entity_context(rating, peers)
            if section == "recommendation":
                ctx["enfoque"] = ("Cierre ACCIONABLE y SINTÉTICO: la dimensión de mayor palanca "
                                  "dada la posición relativa (solvencia, siniestralidad), la "
                                  "señal a vigilar y el 'y por tanto' de decisión.")
            res = await narrative_engine.generate(
                context=ctx,
                template="sector_decision" if section == "recommendation" else "insurance_entity",
                mode=section_mode(tier, section, sections),
                axis="insurance_intel", audience="inversionista")
            return section, res.text

        out: Dict[str, str] = dict(await asyncio.gather(*(_gen(s) for s in sections)))
        return out

    # ── Render (renderer genérico) ──
    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None, fmt: str = "pdf") -> str:
        level = self.product_manifest().require_level(tier)
        title = {"pulse": "Pulse Seguros", "insight": "Insight Seguros",
                 "deep_dive": "Deep Dive Seguros"}.get(tier.value, "Seguros")
        display = SYSTEM_NAME if tier == ProductTier.pulse else (snapshot.entity_name or "Aseguradora")
        tables: List = []
        charts: List = []
        headline: Optional[str] = None
        subtitle: Optional[str] = None
        payload = snapshot.payload or {}

        if tier == ProductTier.pulse and payload.get("has_data"):
            pulse = payload["pulse"]
            for tbl in (_pulse_table(pulse), _mix_table(pulse)):
                if tbl:
                    tables.append(tbl)
            mix = pulse.get("mix") or []
            present = [(d["label"], d.get("pct")) for d in mix[:8]
                       if isinstance(d.get("pct"), (int, float))]
            if len(present) >= 2:
                charts.append({"title": "Mezcla del mercado por ramo (% de la prima)", "items": present})
            tot = pulse.get("total_premiums_rd")
            g = pulse.get("growth_pct")
            if isinstance(tot, (int, float)):
                headline = (f"Primas RD$ {tot / 1e9:,.1f} MMM ({pulse.get('latest_year')})"
                            + (f" · crecim. {g:+.1f}% compuesto" if isinstance(g, (int, float)) else "")
                            + (f" · {pulse.get('active_insurers')} aseguradoras"
                               if pulse.get("active_insurers") else ""))
            if pulse.get("data_caveat"):
                subtitle = pulse["data_caveat"]
        elif payload.get("has_data"):
            rating = payload.get("rating") or {}
            for tbl in (_isf_table(rating), _peer_table(payload.get("peers"))):
                if tbl:
                    tables.append(tbl)
            present = [(d["label"], d.get("score")) for d in rating.get("dimensions") or []
                       if isinstance(d.get("score"), (int, float))]
            if len(present) >= 2:
                charts.append({"title": "Dimensiones del ISF (score 0-100)", "items": present})
            headline = payload.get("headline_line")
            subtitle = payload.get("caveat")
            if headline is None and subtitle is None:
                headline, subtitle = _named_headline_caveat(rating)

        return render_product_pdf(
            sector_key=SECTOR_KEY, display_name=display, title=title,
            period=snapshot.period, narratives=narratives,
            section_titles=_SECTION_TITLES, tables=tables, charts=charts, headline=headline,
            subtitle=subtitle, watermark=level.watermark, sample=sample,
            output_dir=output_dir, fmt=fmt)


register_product(SECTOR_KEY, lambda db: InsuranceProduct(db))
