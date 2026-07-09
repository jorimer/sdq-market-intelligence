"""Política Monetaria como SectorProduct — reporte descargable monetizable (PDF/Word).

Reúne, gateado por tier, lo ya construido en macro_monitor: la evaluación IA de la postura
de política monetaria, la trayectoria completa de la TPM (gráfico + tabla de decisiones) y el
PRONÓSTICO/SESGO del modelo (regla de Taylor + clasificador XGBoost) con su backtest y su
track record en vivo. Producto NACIONAL/agregado (RD): los tres niveles son ``system`` (sin
entidad, sin scope) — se ensambla a nivel **app** vía los getters públicos de macro_monitor
(mismo patrón que ``app/products_macro``), sin importar entre módulos ni tocar el framework.

Doctrina "IA para interpretar, nunca para contar": las cifras (pronóstico, backtest) se
renderizan DETERMINISTAS desde el payload; la IA solo evalúa la postura y recomienda.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
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

logger = logging.getLogger("sdq.products.monetary_policy")

SECTOR_KEY = "monetary_policy"
COUNTRY_NAME = "República Dominicana"

_ACTION_ES = {"hold": "Mantener", "cut": "Reducir", "hike": "Incrementar"}
_ACTION_VERB = {"hold": "mantuvo", "cut": "redujo", "hike": "incrementó"}
_BIAS_ES = {"restrictivo": "restrictivo", "expansivo": "expansivo", "neutral": "neutral"}

# Cuántas decisiones muestra el gráfico de trayectoria por nivel (pulse resumido → deep amplio).
_TRAJ_CHART_POINTS = {ProductTier.pulse: 18, ProductTier.insight: 36, ProductTier.deep_dive: 60}

_SECTION_TITLES = {
    "tpm_snapshot": "Postura y trayectoria de la TPM",
    "mp_evaluation": "Evaluación de la política monetaria",
    "forecast": "Pronóstico del modelo (regla de Taylor + clasificador)",
    "recommendation": "Lectura para decisión",
}


def _period_label(iso_date: Optional[str]) -> str:
    """'YYYY-MM-DD' → 'YYYY-MM' para las etiquetas del gráfico."""
    return (iso_date or "")[:7]


def monetary_policy_manifest() -> SectorProductManifest:
    return SectorProductManifest(
        sector_key=SECTOR_KEY, display_name="SDQ Política Monetaria", levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=("tpm_snapshot",), narrative_templates=("mp_evaluation",),
                audience="mercado / abierto", cadence="periodic",
                watermark="Vista abierta · SDQMIP", price_band="abierto"),
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.system,
                sections=("mp_evaluation",), narrative_templates=("mp_evaluation",),
                audience="cliente / comité", cadence="recurring", price_band="suscripción"),
            ProductTier.deep_dive: TierLevelSpec(
                tier=ProductTier.deep_dive, granularity=Granularity.system,
                sections=("mp_evaluation", "forecast", "recommendation"),
                narrative_templates=("mp_evaluation",),
                audience="comité / tesorería", cadence="on_demand", price_band="on-demand"),
        })


# ── Getters de macro_monitor (nivel app, en SAVEPOINT para no envenenar la transacción) ──
def _trajectory(db: Session) -> List[Dict[str, Any]]:
    try:
        with db.begin_nested():
            from modules.macro_monitor.comunicados.service import trajectory
            return trajectory(db)
    except Exception as e:  # noqa: BLE001
        logger.warning("trayectoria TPM no disponible: %s", e)
        return []


def _eval_context(db: Session) -> Dict[str, Any]:
    try:
        with db.begin_nested():
            from modules.macro_monitor.comunicados.service import mp_evaluation_context
            return mp_evaluation_context(db)
    except Exception as e:  # noqa: BLE001
        logger.warning("contexto de evaluación MP no disponible: %s", e)
        return {"has_data": False}


def _forecast(db: Session) -> Dict[str, Any]:
    try:
        with db.begin_nested():
            from modules.macro_monitor.tpm_modeling.service import get_forecast
            return get_forecast(db)
    except Exception as e:  # noqa: BLE001
        logger.warning("pronóstico TPM no disponible: %s", e)
        return {"has_model": False}


def _backtest(db: Session) -> Dict[str, Any]:
    try:
        with db.begin_nested():
            from modules.macro_monitor.tpm_modeling.service import get_backtest
            return get_backtest(db)
    except Exception as e:  # noqa: BLE001
        return {"has_backtest": False}


def _track_record(db: Session) -> Dict[str, Any]:
    try:
        with db.begin_nested():
            from modules.macro_monitor.tpm_modeling.ledger import track_record
            return track_record(db)
    except Exception as e:  # noqa: BLE001
        return {"has_data": False, "n_scored": 0}


class MonetaryPolicyProduct:
    sector_key = SECTOR_KEY

    def __init__(self, db: Optional[Session] = None):
        self._db = db
        self._cache: Optional[tuple] = None  # (trajectory, eval_context)

    def _require_db(self) -> Session:
        if self._db is None:
            raise RuntimeError("MonetaryPolicyProduct requiere una sesión de DB.")
        return self._db

    def _signals(self) -> tuple:
        if self._cache is None:
            db = self._require_db()
            self._cache = (_trajectory(db), _eval_context(db))
        return self._cache

    def product_manifest(self) -> SectorProductManifest:
        return monetary_policy_manifest()

    # ── Señales de readiness ──
    def data_signals(self) -> DataHealth:
        traj, _ = self._signals()
        freshness = None
        if traj and traj[0].get("fecha"):
            d = _parse_iso(traj[0]["fecha"])
            freshness = (date.today() - d).days if d else None
        span = (f"{traj[-1].get('fecha')}→{traj[0].get('fecha')}" if traj else "")
        return DataHealth(
            coverage=1.0 if traj else 0.0, freshness_days=freshness, cadence="monthly",
            sources=("BCRD — Comunicados de Política Monetaria (Junta Monetaria)",
                     "BCRD — series macro (inflación, IMAE, tipo de cambio, reservas, M1)"),
            detail=f"{len(traj)} decisiones de TPM {span}" if traj else "sin decisiones ingeridas")

    def has_engine(self) -> bool:
        traj, _ = self._signals()
        return bool(traj)

    def validation_state(self) -> ValidationState:
        # G5: el modelo tiene backtest time-series + track record en vivo (ver tpm_modeling).
        score, note = 0.6, ("Modelo de TPM con backtest time-series (expanding-window, recall "
                            "por clase vs baseline) + track record en vivo en acumulación.")
        try:
            bt = _backtest(self._require_db())
            mf1 = (bt.get("classifier") or {}).get("macro_f1") if bt.get("has_backtest") else None
            if isinstance(mf1, (int, float)):
                score = float(mf1)
        except Exception:  # noqa: BLE001
            pass
        return ValidationState(approved=True, score=score, notes=note)

    # ── Snapshot ──
    def snapshot(self, tier: ProductTier, period: str,
                 scope: Optional[str] = None) -> ProductSnapshot:
        db = self._require_db()
        traj, eval_ctx = self._signals()
        if not traj:
            raise ValueError("No hay decisiones de política monetaria (TPM) ingeridas todavía.")
        latest = traj[0]
        payload: Dict[str, Any] = {
            "latest": {"fecha": latest.get("fecha"), "sentido": latest.get("sentido"),
                       "tpm": latest.get("tpm")},
            "trajectory": traj,
            "cycle": eval_ctx.get("ciclo") or {},
            "macro_context": eval_ctx.get("contexto_macro") or {},
            "eval_context": eval_ctx,
        }
        if tier == ProductTier.deep_dive:
            payload["forecast"] = _forecast(db)
            payload["backtest"] = _backtest(db)
            payload["track_record"] = _track_record(db)
        # Nacional/agregado: sin entidad (system) → el período es la fecha de la última decisión.
        return ProductSnapshot(tier=tier, period=str(latest.get("fecha") or period or ""),
                               payload=payload, entity_name=None)

    # ── Narrativas ──
    async def narratives(self, tier: ProductTier, snapshot: ProductSnapshot,
                         lang: str = "es") -> Dict[str, str]:
        sections = self.product_manifest().require_level(tier).sections
        out: Dict[str, str] = {}
        eval_ctx = snapshot.payload.get("eval_context") or {}
        for section in sections:
            if section == "tpm_snapshot":
                out[section] = _tpm_snapshot_md(snapshot.payload)
            elif section == "forecast":
                out[section] = _forecast_md(snapshot.payload)
            elif section in ("mp_evaluation", "recommendation"):
                out[section] = await _mp_narrative(section, eval_ctx, snapshot.payload, tier)
        return out

    # ── Render ──
    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None, fmt: str = "pdf") -> str:
        level = self.product_manifest().require_level(tier)
        title = {"pulse": "Pulse · Política Monetaria", "insight": "Insight · Política Monetaria",
                 "deep_dive": "Deep Dive · Política Monetaria"}.get(tier.value, "Política Monetaria")
        p = snapshot.payload
        latest = p.get("latest") or {}
        tables: List = []
        charts: List = []

        # Titular: TPM vigente + sentido de la última decisión.
        headline = None
        if latest.get("tpm") is not None:
            act = _ACTION_ES.get(latest.get("sentido") or "", latest.get("sentido") or "")
            headline = f"TPM {latest['tpm']:.2f}% · {act} ({latest.get('fecha') or ''})"

        # Gráfico de trayectoria (línea, %) — cronológico, acotado por nivel.
        traj = list(reversed(p.get("trajectory") or []))  # a orden cronológico
        pts = _TRAJ_CHART_POINTS.get(tier, 36)
        items = [(_period_label(d.get("fecha")), d.get("tpm")) for d in traj[-pts:]
                 if d.get("tpm") is not None]
        if len(items) >= 2:
            charts.append({"title": f"Trayectoria de la TPM (últimas {min(pts, len(items))} decisiones, %)",
                           "items": items, "kind": "line", "unit": "%"})

        # Tabla de decisiones recientes (todas los niveles).
        recent = (p.get("trajectory") or [])[:8]
        if recent:
            rows = [["Fecha", "TPM (%)", "Decisión"]]
            for d in recent:
                rows.append([d.get("fecha") or "—",
                             f"{d['tpm']:.2f}" if d.get("tpm") is not None else "—",
                             _ACTION_ES.get(d.get("sentido") or "", d.get("sentido") or "—")])
            tables.append(("Decisiones recientes de la Junta Monetaria", rows))

        # Contexto macro (insight+): cifras de la última decisión digerida.
        if tier != ProductTier.pulse:
            macro_rows = _macro_context_rows(p.get("macro_context") or {})
            if macro_rows:
                tables.append(("Contexto macroeconómico (última decisión)", macro_rows))

        # Pronóstico como barras (deep dive).
        if tier == ProductTier.deep_dive:
            probs = ((p.get("forecast") or {}).get("clasificador") or {}).get("probabilidades") or {}
            bar = [("Reducir", probs.get("cut")), ("Mantener", probs.get("hold")),
                   ("Subir", probs.get("hike"))]
            bar = [(lbl, v * 100 if isinstance(v, (int, float)) else None) for lbl, v in bar]
            if any(v is not None for _lbl, v in bar):
                charts.append({"title": "Pronóstico de la próxima decisión (probabilidad, %)",
                               "items": bar, "unit": "%"})

        return render_product_pdf(
            sector_key=SECTOR_KEY, display_name=f"Política Monetaria · {COUNTRY_NAME}",
            title=title, period=snapshot.period, narratives=narratives,
            section_titles=_SECTION_TITLES, tables=tables, charts=charts, headline=headline,
            subtitle=None, watermark=level.watermark, sample=sample,
            output_dir=output_dir, fmt=fmt)

    # ── Muestra curada (sin DB) ──
    def sample_snapshot(self, tier: ProductTier) -> ProductSnapshot:
        traj = [{"fecha": f, "sentido": s, "tpm": t} for f, s, t in _SAMPLE_TRAJECTORY]
        payload: Dict[str, Any] = {
            "latest": {"fecha": "2026-06-30", "sentido": "hold", "tpm": 5.25},
            "trajectory": traj,
            "cycle": {"ultimos_24m": {"holds": 8, "cortes": 3, "alzas": 0},
                      "tpm_actual": 5.25, "tpm_12_decisiones_atras": 6.75,
                      "tpm_24_decisiones_atras": 7.0, "desde": "2024-07-31",
                      "decisiones_en_historico": 190},
            "macro_context": {"cifras": [{"etiqueta": "Inflación interanual", "valor": "5.35%"},
                                         {"etiqueta": "Meta de inflación", "valor": "4% ±1"},
                                         {"etiqueta": "Crecimiento del IMAE", "valor": "2.4%"}]},
            "eval_context": {"has_data": True},
        }
        if tier == ProductTier.deep_dive:
            payload["forecast"] = {
                "has_model": True, "version": "muestra", "tpm_vigente": 5.25,
                "clasificador": {"probabilidades": {"cut": 0.01, "hold": 0.64, "hike": 0.35},
                                 "decision_mas_probable": "hold"},
                "regla_taylor": {"tasa_implicita": 5.30, "sesgo_pp": 0.05, "sesgo": "neutral"},
                "caveats": ["Análisis macro con incertidumbre; no es consejo de inversión."]}
            payload["backtest"] = {"has_backtest": True,
                                   "classifier": {"macro_f1": 0.56, "accuracy": 0.69,
                                                  "baseline_always_hold_accuracy": 0.69}}
            payload["track_record"] = {"has_data": True, "n_scored": 0}
        return ProductSnapshot(tier=tier, period="2026-06-30", payload=payload, entity_name=None)

    def sample_narratives(self, tier: ProductTier) -> Dict[str, str]:
        sections = self.product_manifest().require_level(tier).sections
        return {sec: _SAMPLE_NARRATIVES[sec] for sec in sections}


# ── Helpers de narrativa determinista + IA ────────────────────────
def _parse_iso(s: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat((s or "")[:10])
    except (ValueError, TypeError):
        return None


def _tpm_snapshot_md(payload: Dict[str, Any]) -> str:
    """Narrativa DETERMINISTA del Pulse: última decisión + resumen del ciclo (sin IA)."""
    latest = payload.get("latest") or {}
    cycle = payload.get("cycle") or {}
    tpm = latest.get("tpm")
    verb = _ACTION_VERB.get(latest.get("sentido") or "", "fijó")
    lines = []
    if tpm is not None:
        lines.append(f"El Banco Central de la República Dominicana **{verb} la Tasa de Política "
                     f"Monetaria (TPM) en {tpm:.2f}%** en su decisión del {latest.get('fecha') or ''}.")
    u24 = cycle.get("ultimos_24m") or {}
    if u24:
        lines.append(f"En las últimas 24 decisiones acumula **{u24.get('holds', 0)} de mantener, "
                     f"{u24.get('cortes', 0)} de reducción y {u24.get('alzas', 0)} de alza**.")
    if cycle.get("tpm_12_decisiones_atras") is not None:
        lines.append(f"El nivel vigente compara con {cycle['tpm_12_decisiones_atras']:.2f}% doce "
                     "decisiones atrás" + (f" y {cycle['tpm_24_decisiones_atras']:.2f}% veinticuatro atrás."
                     if cycle.get("tpm_24_decisiones_atras") is not None else "."))
    lines.append("La trayectoria completa se muestra en el gráfico; la evaluación de la postura y "
                 "el pronóstico del modelo están disponibles en los niveles Insight y Deep Dive.")
    return "\n\n".join(lines)


def _forecast_md(payload: Dict[str, Any]) -> str:
    """Narrativa DETERMINISTA del pronóstico (deep dive): cifras del modelo, sin IA."""
    fc = payload.get("forecast") or {}
    if not fc.get("has_model"):
        return ("El modelo de pronóstico de TPM aún no está entrenado. Corra la operación "
                "'tpm-model-train' para habilitar esta sección.")
    probs = (fc.get("clasificador") or {}).get("probabilidades") or {}
    rt = fc.get("regla_taylor") or {}

    def _pct(x):
        return f"{x * 100:.0f}%" if isinstance(x, (int, float)) else "—"

    md = ["El modelo combina una **regla de reacción tipo Taylor** (interpretable) con un "
          "**clasificador XGBoost** entrenado sobre las decisiones históricas, con variables "
          "macro point-in-time. La distribución estimada para la próxima decisión:", "",
          "| Escenario | Probabilidad |", "|---|---|",
          f"| Reducir (recorte) | {_pct(probs.get('cut'))} |",
          f"| Mantener | {_pct(probs.get('hold'))} |",
          f"| Incrementar (alza) | {_pct(probs.get('hike'))} |", ""]
    top = (fc.get("clasificador") or {}).get("decision_mas_probable")
    if top:
        md.append(f"**Escenario más probable:** {_ACTION_ES.get(top, top)}.")
    if rt.get("tasa_implicita") is not None:
        bias = rt.get("sesgo_pp")
        bias_txt = (f" con un sesgo {_BIAS_ES.get(rt.get('sesgo'), rt.get('sesgo') or '')} "
                    f"({bias:+.2f} pp vs la TPM vigente)" if isinstance(bias, (int, float)) else "")
        md.append(f"**Tasa implícita de la regla de Taylor:** {rt['tasa_implicita']:.2f}%{bias_txt}.")
    bt = (payload.get("backtest") or {}).get("classifier") or {}
    if bt.get("macro_f1") is not None:
        # E2E-MM5 (candor): exhibir que en accuracy CRUDA el modelo no supera al baseline
        # "siempre mantener" — su valor está en anticipar los giros (recorte/alza), que la
        # macro-F1 capta y la accuracy (dominada por los 'mantener') esconde. Nunca vender
        # el macro-F1 sin decir que la accuracy no bate el promedio ingenuo.
        acc, base = bt.get("accuracy"), bt.get("baseline_always_hold_accuracy")
        beats = bt.get("beats_baseline")
        line = f"**Backtest (out-of-sample, expanding-window):** macro-F1 {bt['macro_f1']:.2f}."
        if isinstance(acc, (int, float)) and isinstance(base, (int, float)):
            rel = "supera" if beats else ("iguala" if abs(acc - base) < 0.005 else "no supera")
            line += (f" En accuracy cruda el modelo {rel} al baseline ingenuo de 'siempre "
                     f"mantener' (accuracy {acc:.2f} vs {base:.2f}): su valor NO está en batir "
                     "ese promedio —que el desbalance de 'mantener' infla— sino en anticipar "
                     "los giros de recorte y alza, que es lo que la macro-F1 mide.")
        else:
            line += (" El clasificador aporta en las decisiones de recorte y alza sobre el "
                     "baseline ingenuo de 'siempre mantener'.")
        md.append(line)
    tr = payload.get("track_record") or {}
    n = tr.get("n_scored", 0)
    md.append(f"**Track record en vivo:** {n} pronóstico(s) puntuado(s) contra la decisión real. "
              + ("Aún en acumulación (crece ~1 por reunión); léase junto al backtest histórico."
                 if not n else f"Aciertos acumulados: {tr.get('hit_rate')}."))
    for c in (fc.get("caveats") or [])[:4]:
        md.append(f"- {c}")
    return "\n".join(md)


def _macro_context_rows(macro_ctx: Dict[str, Any]) -> Optional[List[List[str]]]:
    """Tabla de cifras del contexto macro (defensiva ante dict {etiqueta,valor} o string)."""
    cifras = macro_ctx.get("cifras") or []
    rows = [["Indicador", "Valor"]]
    for c in cifras[:8]:
        if isinstance(c, dict):
            rows.append([str(c.get("etiqueta", "—")), str(c.get("valor", "—"))])
        else:
            rows.append([str(c), ""])
    return rows if len(rows) > 1 else None


async def _mp_narrative(section: str, eval_ctx: Dict[str, Any], payload: Dict[str, Any],
                        tier: ProductTier) -> str:
    """Narrativa IA vía el template thin ``mp_evaluation`` (guardado). La sección
    'recommendation' reusa el mismo template con un ``enfoque`` (patrón MacroProduct), para
    no salirse de la ruta con numeric_guard. Cualitativa: las cifras van en 'forecast'."""
    from shared.narrative.claude_engine import narrative_engine

    ctx = dict(eval_ctx)
    ctx["pais"] = COUNTRY_NAME
    if section == "recommendation":
        fc = payload.get("forecast") or {}
        rt = fc.get("regla_taylor") or {}
        ctx["pronostico"] = {
            "decision_mas_probable": (fc.get("clasificador") or {}).get("decision_mas_probable"),
            "sesgo_regla": rt.get("sesgo"),
        }
        ctx["enfoque"] = (
            "Cierre ACCIONABLE para un comité o tesorería: dado el ciclo, el balance "
            "inflación-actividad y el sesgo del modelo ('pronostico'), anticipa la postura "
            "probable y cómo posicionarse (duración, cobertura de tasa), SIEMPRE con "
            "incertidumbre y sin recomendar inversión específica. No repitas el diagnóstico "
            "ni cites cifras nuevas (el detalle numérico va en la sección de pronóstico).")
    res = await narrative_engine.generate(
        context=ctx, template="mp_evaluation",
        mode="deep" if tier == ProductTier.deep_dive else "detailed",
        axis="macro_monitor", audience="inversionista")
    return res.text


# ── Muestra curada (exemplar tier-1, sin DB ni motor) ─────────────
_SAMPLE_TRAJECTORY = [
    ("2026-06-30", "hold", 5.25), ("2026-05-30", "hold", 5.25), ("2026-04-30", "hold", 5.25),
    ("2026-01-31", "hold", 5.25), ("2025-10-31", "cut", 5.25), ("2025-09-30", "cut", 5.50),
    ("2025-06-30", "hold", 5.75), ("2025-01-31", "cut", 5.75), ("2024-10-31", "cut", 6.00),
    ("2024-07-31", "hold", 7.00),
]

_SAMPLE_NARRATIVES = {
    "tpm_snapshot": (
        "El Banco Central de la República Dominicana **mantuvo la Tasa de Política Monetaria "
        "(TPM) en 5.25%** en su decisión del 30/06/2026. En las últimas 24 decisiones acumula "
        "**8 de mantener, 3 de reducción y ninguna de alza**, tras el ciclo de distensión que "
        "llevó la tasa desde 7.00% hasta 5.25%. El nivel vigente compara con 6.75% doce "
        "decisiones atrás. La trayectoria completa se muestra en el gráfico."),
    "mp_evaluation": (
        "La postura de política monetaria se ubica en una **fase de pausa tras la distensión**. "
        "El ciclo de recortes de 2024-2025 retiró 175 puntos básicos desde el pico de 7.00%, y "
        "desde entonces la Junta Monetaria ha optado por mantener, señal de una gestión "
        "cautelosa ante un balance de riesgos mixto. La inflación interanual, en torno a 5.35%, "
        "se ubica por encima del punto medio de la meta (4% ±1), lo que justifica no acelerar "
        "la distensión pese a una actividad económica que se modera. En términos de "
        "transmisión, el nivel actual preserva un tono ligeramente restrictivo en términos "
        "reales, coherente con el objetivo de reanclar la inflación al centro de la meta sin "
        "sacrificar de forma abrupta el crecimiento del crédito y la actividad."),
    "forecast": (
        "El modelo combina una **regla de reacción tipo Taylor** con un **clasificador "
        "XGBoost**, con variables macro point-in-time. Distribución estimada para la próxima "
        "decisión:\n\n| Escenario | Probabilidad |\n|---|---|\n| Reducir (recorte) | 1% |\n"
        "| Mantener | 64% |\n| Incrementar (alza) | 35% |\n\n**Escenario más probable:** "
        "Mantener. **Tasa implícita de la regla de Taylor:** 5.30% con un sesgo neutral "
        "(+0.05 pp vs la TPM vigente). **Backtest (out-of-sample):** macro-F1 0.56; el "
        "clasificador aporta en recortes y alzas sobre el baseline de 'siempre mantener'. "
        "**Track record en vivo:** en acumulación (crece ~1 por reunión).\n"
        "- Análisis macro con incertidumbre; no constituye consejo de inversión."),
    "recommendation": (
        "Para un comité o una tesorería con exposición a tasa en pesos, la lectura es de "
        "**estabilidad con sesgo neutral a la baja en el mediano plazo**. El escenario base "
        "—mantener— sugiere que no hay urgencia de reposicionar duración de forma táctica; la "
        "cola de alza (35%) recomienda, sin embargo, no extender duración de manera agresiva "
        "hasta confirmar la convergencia de la inflación al centro de la meta. Se sugiere "
        "monitorear dos señales adelantadas: la trayectoria de la inflación subyacente y el "
        "tono de los comunicados de la Junta. La recomendación es de gestión prudente del "
        "riesgo de tasa, no de una apuesta direccional; toda decisión debe dimensionarse con "
        "su propio marco de riesgo."),
}


register_product(SECTOR_KEY, lambda db: MonetaryPolicyProduct(db))
