"""Report assembly — the quarterly Market Context Report.

Follows the house standard (``docs/REPORT_STANDARD.md``): cover, executive summary,
findings, methodology, sources and limits. Two of those sections are **generated from
provenance, never written by hand** — methodology and limits are derived from what the
data actually supports, so they cannot drift away from the analysis they describe.

The report states what it does not know. Where a section lacks its input it says so and
why, instead of quietly disappearing: a missing section that goes unmentioned reads as an
absence of problems.
"""
from __future__ import annotations

import asyncio
import html
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.brand_intel import service as svc
from modules.brand_intel.engines import category as cat_engine
from modules.brand_intel.engines.metrics import label_for
from modules.brand_intel.models.models import BrandEngagement, BrandObservation

REPORT_TITLE = "Informe de Contexto de Mercado"


# ── payload ───────────────────────────────────────────────────────────

def build_report(db: Session, engagement: BrandEngagement) -> Dict[str, Any]:
    """Assemble every section plus the auto-generated methodology, sources and limits."""
    eid = engagement.id
    # Waves WITH data: a projection wave exists only to hold a frozen forecast and is not
    # part of the report's history — counting it would overstate the panel behind every
    # statement the report makes about how much history there is.
    ws = svc.data_waves(db, eid)

    explanations = svc.explanations_analysis(db, str(eid))
    category = svc.category_analysis(db, eid)
    funnel = svc.funnel_analysis(db, eid)
    ticket = svc.ticket_analysis(db, eid)
    attribution = svc.attribution_analysis(db, eid)
    backtest = svc.rule_backtest(db, eid)
    track = svc.forecast_track_record(db, eid)
    signal = svc.signal_filter(db, eid)
    decisions = svc.evaluate_decisions(db, eid)
    scenarios = svc.scenarios_analysis(db, eid)
    vigilance = svc.vigilance_analysis(db, eid)
    plan = svc.plan_readiness(db, str(eid))

    payload: Dict[str, Any] = {
        "engagement": {
            "slug": engagement.slug,
            "client": engagement.client_name,
            "focal_brand": engagement.focal_brand,
            "market": engagement.market,
            "category": engagement.category,
            "provider": engagement.research_provider,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "waves": [
            {"code": w.code, "label": w.label,
             "period": w.period_date.isoformat() if w.period_date else None,
             "base": w.nominal_base}
            for w in ws
        ],
        "sections": {
            "explanations": explanations,
            "category": category,
            "funnel": funnel,
            "ticket": ticket,
            "attribution": attribution,
            "forecast_backtest": backtest,
            "forecast_track_record": track,
            "signal_filter": signal,
            "decisions": decisions,
            "scenarios": scenarios,
            "vigilance": vigilance,
            "plan": plan,
        },
    }
    payload["executive"] = _executive(payload)
    payload["methodology"] = _methodology(payload)
    payload["sources"] = _sources(db, eid, engagement)
    payload["limits"] = _limits(payload)
    return payload


def _fmt(v: Optional[float], suffix: str = "%", dec: int = 1) -> str:
    """Spanish number format: dot for thousands, comma for decimals."""
    if v is None:
        return "n/d"
    return (
        f"{v:,.{dec}f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
        + suffix
    )


def _executive(p: Dict[str, Any]) -> Dict[str, Any]:
    """At most three findings. A report that leads with everything leads with nothing.

    Lo que lidera es lo que SOLO SDQ aporta: cuántas conclusiones del proveedor tienen
    porqué económico, el veredicto entorno-vs-marca, y el ticket en pesos constantes.
    Una versión anterior lideraba con share, divergencia y embudo — re-análisis del dato
    del propio proveedor, que es exactamente lo que este informe ya no hace.

    Desde el reenfoque narrativo, estos findings ya NO son el resumen ejecutivo que ve el
    cliente: son parte del CONTEXTO que se le sirve al cerebro (``cerebro_contexts``) para
    que redacte una síntesis real del trimestre, y el fallback determinista del documento
    cuando la narrativa IA no está disponible. El ``empty_reason`` se conserva con ese rol.
    """
    findings: List[Dict[str, str]] = []
    brand = p["engagement"]["focal_brand"]
    provider = p["engagement"].get("provider") or "el proveedor"

    xp = p["sections"].get("explanations") or {}
    if xp.get("available"):
        n_x = len(xp.get("explicadas") or [])
        n_c = len(xp.get("competitivas") or [])
        if n_x:
            findings.append({
                "title": "El porqué económico de lo que el estudio concluye",
                "figure": str(n_x),
                "detail": (f"Conclusiones de {provider} sobre consumo y gasto que los "
                           "datos de entorno de SDQ ayudan a explicar — inflación, tasa "
                           "de política, actividad económica y tipo de cambio, con sus "
                           "valores del período."),
            })
        stance = xp.get("environment_stance")
        caidas_sin_excusa = [c for c in (xp.get("competitivas") or [])
                             if c.get("direction") == "baja"] if stance == "favorable" else []
        if caidas_sin_excusa:
            findings.append({
                "title": "Retrocesos que el entorno no explica",
                "figure": str(len(caidas_sin_excusa)),
                "detail": ("El entorno del período fue favorable: estos movimientos de "
                           "percepción son dinámica competitiva, no marea del mercado — "
                           "y por eso son accionables por la marca."),
            })
        elif n_c and len(findings) < 3:
            findings.append({
                "title": "Lo que es de la marca, no del entorno",
                "figure": str(n_c),
                "detail": ("Conclusiones de percepción (favorito, imagen, fidelidad) "
                           "donde invocar el entorno económico sería inventar: su "
                           "lectura es competitiva."),
            })

    tick = p["sections"]["ticket"]
    if tick.get("available") and tick.get("deflated"):
        chg = tick.get("change_from_peak_pct")
        if chg is not None and chg < -1.0 and len(findings) < 3:
            findings.append({
                "title": "El ticket real retrocede",
                "figure": _fmt(chg),
                "detail": (
                    "Gasto medio por visita en pesos constantes desde el máximo de la serie. "
                    "En términos nominales la lectura sería de estabilidad."
                ),
            })

    return {
        "findings": findings[:3],
        "empty_reason": (None if findings else
                         "Sin conclusiones del proveedor utilizables ni insumos de "
                         "entorno: sube la presentación del tracker para que el informe "
                         "tenga qué explicar."),
    }


# ── narrativa vía cerebro ─────────────────────────────────────────────
# El informe del cliente se narra por el motor compartido (shared/narrative/cerebro.py),
# igual que los otros ejes: doctrina en AXIS_DOCTRINE["brand_intel"], frame en
# AUDIENCE_FRAMES, thin templates brand_context_*. El LLM narra sobre lo que
# engines/explain.py y service.py YA calcularon — nunca decide causalidad ni cifras;
# si degrada (sin API key, presupuesto), el documento cae a la composición determinista.

CEREBRO_AXIS = "brand_intel"
CEREBRO_AUDIENCE = "cliente_marca"

_CEREBRO_TEMPLATES = {
    "executive": "brand_context_executive",
    "explanations": "brand_context_reading",
    "priorities": "brand_context_priorities",
    "plan": "brand_plan_readiness",
}


def group_competitivas(xp: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Las conclusiones de percepción agrupadas por dirección del movimiento.

    Servirle al modelo decenas de frases casi idénticas invita al patrón cita-por-cita
    que este informe elimina; agrupadas por dirección (la lectura del motor determinista
    depende solo de dirección × postura del entorno) el contexto empuja a sintetizar.
    """
    grupos: Dict[str, Dict[str, Any]] = {}
    for c in xp.get("competitivas") or []:
        d = str(c.get("direction") or "sin_direccion")
        g = grupos.setdefault(d, {"n": 0, "lectura": c.get("reading"), "conclusiones": []})
        g["n"] += 1
        g["conclusiones"].append({"claim": c.get("claim"),
                                  "subjects": c.get("subjects") or []})
    return grupos


def cerebro_contexts(p: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Los tres contextos que el cerebro narra. Solo re-empaqueta lo YA calculado.

    Nada se recalcula aquí: cada campo viene tal cual de ``build_report``. Si al narrar
    falta una lectura, el arreglo es servir más contexto calculado, nunca dejar que el
    modelo la derive por su cuenta.
    """
    s = p["sections"]
    eng = p["engagement"]
    xp = s.get("explanations") or {}
    vig = s.get("vigilance") or {}
    ag = (vig.get("agenda") or {}) if vig.get("available") else {}
    sf = s.get("signal_filter") or {}
    esc = s.get("scenarios") or {}
    att = s.get("attribution") or {}
    tic = s.get("ticket") or {}
    dec = s.get("decisions") or {}
    bt = s.get("forecast_backtest") or {}
    tr = s.get("forecast_track_record") or {}

    base = {
        "marca": eng.get("focal_brand"), "cliente": eng.get("client"),
        "proveedor": eng.get("provider"), "mercado": eng.get("market"),
        "categoria": eng.get("category"),
        "olas": [w.get("label") for w in p.get("waves") or []],
    }
    explicadas = [
        {"claim": e.get("claim"), "subjects": e.get("subjects") or [],
         "direction": e.get("direction"), "canal": e.get("channel"),
         "lectura": e.get("reading")}
        for e in xp.get("explicadas") or []
    ]
    competitivas = group_competitivas(xp)

    lectura = {
        **base,
        "entorno": xp.get("entorno") or {},
        "postura_entorno": xp.get("environment_stance"),
        "explicadas": explicadas,
        "competitivas_por_direccion": competitivas,
        "sin_capa_n": len(xp.get("sin_capa") or []),
        "nota_motor": xp.get("note"),
    }
    prioridades = {
        **base,
        "agenda": {"items": ag.get("items") or [],
                   "nota": ag.get("note") or ag.get("empty_reason")},
        "filtro_senal": ({"rows": sf.get("rows"), "nota": sf.get("note")}
                         if sf.get("available") else {"nota": sf.get("reason")}),
        # Sin la fuente "decision": el resumen de decisiones ya viaja aparte, y con un
        # plan adoptado entero esas señales repiten cien títulos casi idénticos.
        "senales_vigilancia": (
            {k: v for k, v in (vig.get("signals") or {}).items() if k != "decision"}
            if vig.get("available") else None),
        "escenarios": ({"escenarios": esc.get("scenarios"),
                        "riesgos": esc.get("risks"),
                        "dispersion_reglas": esc.get("rule_dispersion"),
                        "nota": esc.get("note")} if esc.get("available") else None),
        "decisiones": (dec.get("summary") if dec.get("decisions") else None),
        "pronostico": {"regla_ganadora": bt.get("winner"), "nota": bt.get("note"),
                       "track_record": (tr if tr.get("available") else tr.get("reason"))},
    }
    plan = s.get("plan") or {}
    # Un cliente real adopta el plan ENTERO (100+ compromisos): el contexto separa lo
    # que tiene medida (completo, con su veredicto mecánico) de lo operativo (agregado
    # con ejemplos) — servirle cien filas casi iguales al modelo invita al inventario.
    plan_rows = plan.get("rows") or []

    def _measurable(r: Dict[str, Any]) -> bool:
        return bool(r.get("metric_code")) or r.get("success_threshold") is not None

    medibles = [r for r in plan_rows if _measurable(r)]
    operativos = [r for r in plan_rows if not _measurable(r)]
    plan_goals = plan.get("goals") or []
    goal_metas = [g for g in plan_goals if g.get("kind") == "meta"]
    goal_acciones = [g for g in plan_goals if g.get("kind") != "meta"]
    plan_ctx = {
        **base,
        "documentos": plan.get("documents") or [],
        "metas_extraidas": goal_metas,
        "acciones_del_plan": {
            "n": len(goal_acciones),
            "ejemplos": [g.get("claim") for g in goal_acciones[:10]],
        },
        # Cada fila trae el veredicto MECÁNICO de medibilidad (feasible/gap/needs/
        # umbral detectable) recomputado por el ledger: el modelo lo narra y
        # prescribe sobre él; jamás lo recalcula.
        "compromisos_medibles": medibles,
        "compromisos_operativos": {
            "n": len(operativos),
            "ejemplos": [r.get("title") for r in operativos[:10]],
        },
        "nota_motor": plan.get("note"),
        "instrumento": {
            "olas_con_dato": base["olas"],
            "metricas_cargadas": [
                {"metric_code": r.get("metric_code"), "label": r.get("label"),
                 "corte": r.get("segment"), "base": r.get("base_n"),
                 "minimo_detectable_pp": r.get("threshold")}
                for r in (sf.get("rows") or [])
            ] if sf.get("available") else [],
            "ticket_con_serie": bool(tic.get("available")),
        },
    }
    ejecutivo = {
        **base,
        "hallazgos_deterministas": (p.get("executive") or {}).get("findings") or [],
        "entorno": xp.get("entorno") or {},
        "postura_entorno": xp.get("environment_stance"),
        "explicadas": explicadas,
        "competitivas_por_direccion": competitivas,
        "atribucion": ({"variacion_categoria_pct": att.get("category_delta_pct"),
                        "rows": att.get("rows"), "nota": att.get("note")}
                       if att.get("available") else None),
        "ticket": ({"series": tic.get("series"),
                    "variacion_real_desde_maximo_pct": tic.get("change_from_peak_pct"),
                    "nota_deflactor": tic.get("deflator_note")}
                   if tic.get("available") else None),
        "agenda": ag.get("items") or [],
        "nota_umbral": sf.get("note"),
    }
    return {"executive": ejecutivo, "explanations": lectura,
            "priorities": prioridades, "plan": plan_ctx}


async def ai_narratives(payload: Dict[str, Any]) -> Dict[str, str]:
    """Las tres narrativas del documento del cliente, generadas por la ruta cerebro.

    Devuelve solo las secciones con narrativa REAL: una que degradó a fallback estático
    se omite, y el documento cae a su composición determinista — nunca relleno hueco en
    un PDF de cliente (misma doctrina que ``NarrativeDegradedError`` en los Deep Dive).
    Cada sección narra solo si su insumo existe: las tres del trimestre requieren
    conclusiones utilizables; la del plan, planes o decisiones registradas.
    """
    from shared.narrative.claude_engine import is_static_fallback_text, narrative_engine

    xp = payload["sections"].get("explanations") or {}
    plan = payload["sections"].get("plan") or {}
    ctxs = cerebro_contexts(payload)
    if not xp.get("available"):
        ctxs.pop("executive", None)
        ctxs.pop("explanations", None)
        ctxs.pop("priorities", None)
    if not plan.get("available"):
        ctxs.pop("plan", None)
    if not ctxs:
        return {}

    async def _gen(section: str, ctx: Dict[str, Any]):
        res = await narrative_engine.generate(
            context=ctx, template=_CEREBRO_TEMPLATES[section], mode="detailed",
            axis=CEREBRO_AXIS, audience=CEREBRO_AUDIENCE)
        return section, res.text

    out: Dict[str, str] = {}
    for section, text in await asyncio.gather(*(_gen(s, c) for s, c in ctxs.items())):
        if text and not is_static_fallback_text(text):
            out[section] = text
    return out


def ai_narratives_sync(payload: Dict[str, Any]) -> Dict[str, str]:
    """Envoltura síncrona para los endpoints ``def`` (corren en threadpool)."""
    return asyncio.run(ai_narratives(payload))


def _methodology(p: Dict[str, Any]) -> List[Dict[str, str]]:
    """Derived from what ran, not written by hand."""
    out: List[Dict[str, str]] = []
    cat = p["sections"]["category"]
    if cat.get("available"):
        out.append({
            "title": "Denominador de categoría",
            "text": "Suma del alcance a 7 días de las marcas declaradas dentro del set. "
                    + str(cat.get("denominator_note", "")),
        })
    tick = p["sections"]["ticket"]
    if tick.get("available") and tick.get("deflated"):
        out.append({
            "title": "Deflactación",
            "text": "Nivel de precios encadenado desde la inflación interanual del Banco "
                    "Central: cada mes aporta (1 + π/12). " + str(tick.get("deflator_note", "")),
        })
    bt = p["sections"]["forecast_backtest"]
    if bt.get("available"):
        out.append({
            "title": "Selección de la regla de pronóstico",
            "text": f"Regla ganadora por backtest de ventana expansiva: «{bt['winner']}». "
                    + str(bt.get("note", "")),
        })
    sf = p["sections"]["signal_filter"]
    if sf.get("available"):
        out.append({
            "title": "Umbrales de decisión",
            "text": str(sf.get("note", "")),
        })
    attribution = p["sections"]["attribution"]
    if attribution.get("available"):
        out.append({"title": "Atribución", "text": str(attribution.get("note", ""))})
    scen = p["sections"].get("scenarios") or {}
    if scen.get("available"):
        out.append({"title": "Escenarios", "text": str(scen.get("note", ""))})
    vig = p["sections"].get("vigilance") or {}
    if vig.get("available"):
        out.append({"title": "Panel de vigilancia y agenda", "text": str(vig.get("note", ""))})
    return out


def _sources(db: Session, eid: str, engagement: BrandEngagement) -> List[Dict[str, str]]:
    """Distinct provenance strings on the observations, plus the macro series if used."""
    rows = (
        db.query(BrandObservation.source)
        .filter(BrandObservation.engagement_id == eid,
                BrandObservation.source.isnot(None))
        .distinct()
        .all()
    )
    out = [{"name": r[0], "kind": "tracker",
            "provider": engagement.research_provider or "—"} for r in rows if r[0]]
    from shared.contracts import load_inflation_series
    if load_inflation_series(db):
        out.append({
            "name": "Inflación interanual — serie mensual",
            "kind": "macro",
            "provider": "Banco Central de la República Dominicana",
        })
    return out


def _limits(p: Dict[str, Any]) -> List[str]:
    """Generated from the analysis's own state — the honest part of the standard."""
    limits: List[str] = []
    n_waves = len(p.get("waves") or [])

    cat = p["sections"]["category"]
    if cat.get("available"):
        limits.append(str(cat.get("denominator_note")))
        limits.append(
            "El alcance mide personas, no transacciones ni valor: la lectura de valor "
            "requiere cruzarlo con el ticket."
        )
    else:
        limits.append(f"Posición competitiva no disponible: {cat.get('reason')}")

    tick = p["sections"]["ticket"]
    if not tick.get("available"):
        # La sección del ticket no ocupa un título propio cuando no hay serie: su
        # ausencia se declara aquí, donde el estándar de la casa declara lo que falta.
        limits.append(f"El ticket en pesos constantes no se calcula: {tick.get('reason')}")
    elif tick.get("available") and not tick.get("deflated"):
        limits.append(f"Ticket sin deflactar: {tick.get('reason')}")
    elif tick.get("available") and (tick.get("coverage") or 1.0) < 1.0:
        limits.append(
            f"Deflactor con cobertura parcial ({tick['coverage'] * 100:.0f}% de los meses "
            "del tramo); el resto se extrapoló a la ventana completa."
        )

    if n_waves < 8:
        limits.append(
            f"El pronóstico es una línea base ingenua, no un modelo aprendido: con "
            f"{n_waves} ola{'s' if n_waves != 1 else ''} no hay panel para entrenar. "
            "Un modelo aprendido gana valor a partir de la ola 8-10."
        )

    track = p["sections"]["forecast_track_record"]
    if not track.get("available"):
        limits.append(str(track.get("reason")))

    sf = p["sections"]["signal_filter"]
    if sf.get("available"):
        weak = [r for r in sf.get("rows", []) if not r.get("publishable")]
        if weak:
            names = ", ".join(sorted({r["label"] for r in weak}))
            limits.append(
                f"Celdas con base insuficiente, excluidas de todo veredicto: {names}."
            )

    attribution = p["sections"].get("attribution") or {}
    if not attribution.get("available"):
        limits.append(
            f"La atribución categoría/marca no se calcula: {attribution.get('reason')}"
        )
    env = (attribution.get("environment") or {})
    if attribution.get("available") and not env.get("available"):
        limits.append(
            "Sin contexto macro publicado para el período: la atribución separa marca y "
            "categoría, pero no puede decir si el entorno era exigente o favorable."
        )
    elif env.get("available"):
        limits.append(
            "La lectura de entorno es cualitativa y NO ajusta ninguna cifra: con esta "
            "cantidad de olas no hay base para estimar cuánto de un indicador de marca "
            "explica un punto de una variable macro."
        )

    scen = p["sections"].get("scenarios") or {}
    if scen.get("available"):
        limits.append(
            "Los escenarios no llevan probabilidad asignada: hacerlo implicaría una "
            "distribución que nadie estimó."
        )
        fragile = [d["label"] for d in scen.get("rule_dispersion", []) if not d.get("robust")]
        if fragile:
            limits.append(
                "Pronósticos sensibles a la regla elegida (la dispersión entre reglas "
                f"supera la banda muestral): {', '.join(fragile)}."
            )

    # Las secciones estructuralmente vacías con pocas olas (pronóstico puntuado, ledger
    # de decisiones) ya no ocupan un título propio en el documento: su estado honesto
    # se declara aquí. Un informe con tres títulos seguidos de "aún no hay X" se lee
    # incompleto; uno que lo declara en Límites se lee honesto.
    dec = p["sections"].get("decisions") or {}
    if not (dec.get("decisions") or []):
        limits.append(
            "Aún no hay decisiones del cliente registradas para seguimiento. Cada "
            "decisión requiere métrica, línea base, ventana de evaluación, umbral de "
            "éxito y responsable; el ledger aparecerá cuando exista la primera."
        )

    # Brechas de instrumento que el PLAN del cliente refiere — generadas del ledger,
    # nunca escritas a mano. La imparcialidad manda: un corte sin cargar es un hueco
    # de NUESTRA base, y se declara como tal.
    plan = p["sections"].get("plan") or {}
    cortes = sorted({
        f"«{r['segment']}» ({r['medida']})"
        for r in (plan.get("rows") or [])
        if r.get("gap") == "sin_datos_del_corte" and (r.get("segment") or "total") != "total"
    })
    if cortes:
        limits.append(
            "El plan del cliente refiere cortes del tracker sin datos en la base "
            f"cargada por SDQ: {', '.join(cortes)}. Hasta cargarlos (o pedirlos en la "
            "próxima entrega del proveedor), esas decisiones quedan inevaluables."
        )
    externas = sum(1 for r in (plan.get("rows") or []) if r.get("gap") == "dato_externo")
    if externas:
        limits.append(
            f"{externas} compromiso(s) del plan se mide(n) con fuentes externas al "
            "tracker (plataformas, dato transaccional): el informe los registra y "
            "vigila, pero su veredicto requiere ese dato del cliente."
        )

    vig = p["sections"].get("vigilance") or {}
    if vig.get("available") and (vig.get("agenda") or {}).get("dropped"):
        limits.append(
            f"La agenda se limita a {len((vig['agenda'])['items'])} punto(s); "
            f"{vig['agenda']['dropped']} quedaron fuera del corte por prioridad."
        )

    limits.append(
        "Las lecturas de esta capa son descomposiciones contables y correlaciones; "
        "ninguna establece causalidad."
    )
    limits.append(
        "Ninguna cifra fue estimada por IA: todas provienen del tracker cargado o de "
        "series oficiales."
    )
    return [x for x in limits if x and x != "None"]


# ── HTML rendering ────────────────────────────────────────────────────

_CSS = """
:root{--navy:#0B1F3A;--ink:#1A2433;--muted:#6B7A8F;--signal:#D7263D;--line:#DCE3EC;
--panel:#F6F8FB;--teal:#0F7E7E;--teal-soft:#E4F2F1;--signal-soft:#FBEAEC}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Inter","Plus Jakarta Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",
Helvetica,Arial,sans-serif;color:var(--ink);line-height:1.5;background:#E9EDF2;padding:24px}
.doc{max-width:1080px;margin:0 auto;background:#fff;box-shadow:0 8px 40px rgba(11,31,58,.14)}
header{background:var(--navy);color:#fff;padding:38px 48px 32px;position:relative}
header::after{content:"";position:absolute;left:0;bottom:0;height:3px;width:100%;
background:linear-gradient(90deg,var(--signal) 0 22%,transparent 22%)}
.brand{font-size:11px;letter-spacing:.22em;font-weight:700;text-transform:uppercase}
.brand span{color:var(--signal)}
h1{font-size:32px;font-weight:800;letter-spacing:-.02em;margin:16px 0 6px}
.meta{font-size:12.5px;color:#B9CAE0}
section{padding:30px 48px;border-bottom:1px solid var(--line)}
h2{font-size:20px;font-weight:750;color:var(--navy);margin-bottom:4px;letter-spacing:-.012em}
.kicker{font-size:9.5px;letter-spacing:.19em;text-transform:uppercase;color:var(--signal);
font-weight:700;margin-bottom:6px}
.lede{font-size:13px;color:var(--muted);margin-bottom:16px;max-width:760px}
table{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:8px}
th{text-align:left;font-size:9.5px;letter-spacing:.11em;text-transform:uppercase;
color:var(--muted);font-weight:700;padding:0 10px 7px 0;border-bottom:1.5px solid var(--navy)}
td{padding:9px 10px 9px 0;border-bottom:1px solid var(--line);vertical-align:top}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;padding-right:16px}
tr.focal td{background:#F4F8FD;font-weight:650}
.finding{display:flex;gap:18px;padding:14px 0;border-bottom:1px solid var(--line)}
.finding:last-child{border-bottom:none}
.figure{font-size:26px;font-weight:800;color:var(--navy);min-width:130px;letter-spacing:-.02em}
.finding h3{font-size:14.5px;font-weight:700;margin-bottom:3px}
.finding p{font-size:12.5px;color:var(--muted)}
.note{border-left:3px solid var(--teal);background:var(--teal-soft);padding:11px 15px;
font-size:12.5px;color:#0B4A4A;margin-top:14px;border-radius:0 3px 3px 0}
.note.red{border-left-color:var(--signal);background:var(--signal-soft);color:#5B1420}
.tag{display:inline-block;font-size:10px;font-weight:750;padding:3px 9px;border-radius:99px}
.t-ok{background:var(--teal-soft);color:var(--teal)}
.t-no{background:var(--signal-soft);color:var(--signal)}
.t-mid{background:#FDF3E0;color:#B7791F}
.t-gray{background:#EEF2F7;color:var(--muted)}
ul{margin:6px 0 0 18px;font-size:12.5px;color:var(--muted)}
li{margin-bottom:5px}
.empty{font-size:12.5px;color:var(--muted);font-style:italic;
background:var(--panel);padding:12px 15px;border-radius:3px}
footer{padding:22px 48px 28px;background:var(--panel);font-size:11px;color:var(--muted)}
@media print{body{background:#fff;padding:0}.doc{box-shadow:none}
section{page-break-inside:avoid}@page{margin:12mm}}
@media(max-width:720px){section,header,footer{padding-left:20px;padding-right:20px}
.finding{flex-direction:column;gap:4px}.figure{min-width:0}}
"""


def _e(v: Any) -> str:
    return html.escape(str(v)) if v is not None else ""


def _empty(reason: Optional[str]) -> str:
    return f'<p class="empty">{_e(reason or "Sección sin insumos suficientes.")}</p>'


def render_html(p: Dict[str, Any]) -> str:
    """Render the report as a self-contained, printable HTML document."""
    eng = p["engagement"]
    gen = p["generated_at"][:10]
    waves_lbl = " · ".join(w["label"] for w in p["waves"]) or "sin olas"

    parts: List[str] = [
        "<!doctype html><html lang='es'><head><meta charset='utf-8'>",
        f"<title>{_e(REPORT_TITLE)} — {_e(eng['focal_brand'])}</title>",
        f"<style>{_CSS}</style></head><body><div class='doc'>",
        "<header>",
        "<div class='brand'>SDQ<span>·</span>MIP <span>|</span> "
        "Market Intelligence Platform</div>",
        f"<h1>{_e(REPORT_TITLE)}</h1>",
        f"<div class='meta'>{_e(eng['focal_brand'])} · {_e(eng.get('category') or '')} · "
        f"{_e(eng['market'])}<br>Olas: {_e(waves_lbl)} · Generado {_e(gen)}"
        + (f" · Tracker: {_e(eng['provider'])}" if eng.get("provider") else "")
        + "</div></header>",
    ]

    parts.append(_render_executive(p))
    parts.append(_render_explanations(p["sections"].get("explanations") or {},
                                      p["engagement"].get("provider") or "el proveedor"))
    parts.append(_render_agenda(p["sections"]["vigilance"]))
    parts.append(_render_ticket(p["sections"]["ticket"]))
    parts.append(_render_attribution(p["sections"]["attribution"]))
    parts.append(_render_forecast(p["sections"]))
    parts.append(_render_scenarios(p["sections"]["scenarios"]))
    parts.append(_render_signal(p["sections"]["signal_filter"]))
    parts.append(_render_vigilance(p["sections"]["vigilance"]))
    parts.append(_render_decisions(p["sections"]["decisions"]))
    parts.append(_render_method_sources_limits(p))

    parts.append(
        "<footer><b>SDQ Market Intelligence Platform</b> · Documento confidencial, "
        "de uso interno del cliente. Metodología, fuentes y limitaciones se generan "
        "automáticamente de la procedencia del dato.</footer>"
    )
    parts.append("</div></body></html>")
    return "".join(parts)


def _render_explanations(x: Dict[str, Any], provider: str) -> str:
    """«El proveedor concluye X → lectura SDQ».

    El entorno se declara UNA vez con sus valores; cada conclusión lleva su lectura
    propia — el cruce de su dirección con la postura del período. La conclusión va
    LITERAL y entre comillas — voz del proveedor, nunca paráfrasis. La lámina NO se
    imprime: el recibo vive en el registro (vista interna y mesa con el proveedor).
    """
    out = ["<section><div class='kicker'>El porqué económico</div>",
           f"<h2>Lo que concluye {_e(provider)}, explicado con datos SDQ</h2>"]
    if not x.get("available"):
        out.append(_empty(x.get("reason") or "Sin conclusiones utilizables del proveedor."))
        out.append("</section>")
        return "".join(out)

    entorno = x.get("entorno") or {}
    if entorno:
        out.append("<h3>El entorno del período</h3><ul>")
        for f in entorno.values():
            val = _fmt(f.get("value")) if f.get("unit") == "%" else \
                f"{f.get('value')}{f.get('unit') or ''}"
            out.append(f"<li><b>{_e(str(f.get('label')))}: {_e(val)}</b> "
                       f"({_e(str(f.get('direction')))}) — {_e(str(f.get('doctrine')))}.</li>")
        out.append("</ul>")

    for e in x.get("explicadas") or []:
        out.append("<div class='finding'><div>")
        out.append(f"<h3>{_e(provider)} concluye</h3><p>«{_e(e['claim'])}»</p>")
        out.append(f"<h3>Lectura SDQ</h3><p>{_e(str(e.get('reading') or ''))}</p>")
        out.append("</div></div>")

    comp = x.get("competitivas") or []
    if comp:
        out.append("<h3>Lo que el entorno no explica</h3>")
        out.append("<p>Indicadores de percepción: invocar el entorno económico aquí "
                   "sería inventar. Su lectura es competitiva.</p><ul>")
        for c in comp:
            out.append(f"<li>«{_e(c['claim'])}» — {_e(c.get('reading') or '')}</li>")
        out.append("</ul>")
    out.append(f"<p class='note'>{_e(str(x.get('note') or ''))}</p>")
    out.append("</section>")
    return "".join(out)


def _render_executive(p: Dict[str, Any]) -> str:
    ex = p["executive"]
    out = ["<section><div class='kicker'>Resumen ejecutivo</div>",
           "<h2>Las lecturas del trimestre</h2>"]
    if not ex["findings"]:
        out.append(_empty(ex.get("empty_reason")))
    for f in ex["findings"]:
        out.append(
            f"<div class='finding'><div class='figure'>{_e(f['figure'])}</div>"
            f"<div><h3>{_e(f['title'])}</h3><p>{_e(f['detail'])}</p></div></div>"
        )
    out.append("</section>")
    return "".join(out)


_VERDICT_TAG = {
    "marca": ("t-no", "Marca"),
    "categoria": ("t-mid", "Categoría"),
    "mixto": ("t-gray", "Mixto"),
    "solo_marca": ("t-no", "Marca"),
    "sin_movimiento": ("t-gray", "Sin movimiento"),
}


def _render_attribution(a: Dict[str, Any]) -> str:
    out = ["<section><div class='kicker'>S3 · Atribución</div>",
           "<h2>¿La marca o el mercado?</h2>"]
    if not a.get("available"):
        return "".join(out) + _empty(a.get("reason")) + "</section>"

    env = a.get("environment") or {}
    out.append(
        "<p class='lede'>Descomposición del movimiento de cada indicador núcleo entre "
        f"{_e(a.get('wave_from_label') or a['wave_from'])} y "
        f"{_e(a.get('wave_to_label') or a['wave_to'])}. La categoría varió "
        f"{_fmt(a.get('category_delta_pct'))} en el período.</p>"
    )
    out.append("<table><thead><tr><th>Indicador</th><th class='num'>Movimiento</th>"
               "<th class='num'>Categoría</th><th class='num'>Marca</th>"
               "<th>Origen</th></tr></thead><tbody>")
    for r in a["rows"]:
        cls, lbl = _VERDICT_TAG.get(r["verdict"], ("t-gray", r["verdict"]))
        out.append(
            f"<tr><td>{_e(r['label'])}</td>"
            f"<td class='num'>{_fmt(r['delta'], ' pp')}</td>"
            f"<td class='num'>{_fmt(r['category_effect'], ' pp', 2)}</td>"
            f"<td class='num'>{_fmt(r['brand_effect'], ' pp', 2)}</td>"
            f"<td><span class='tag {cls}'>{_e(lbl)}</span></td></tr>"
        )
    out.append("</tbody></table>")

    if env.get("available"):
        stance = env.get("stance")
        tone = " red" if stance == "exigente" else ""
        out.append(
            f"<div class='note{tone}'>Entorno macro del período: "
            f"<b>{_e(stance)}</b>. {_e(env.get('note'))}</div>"
        )
        readings = {r["cycle_text"] for r in a["rows"] if r.get("cycle_text")}
        if readings:
            out.append("<ul>" + "".join(f"<li>{_e(t)}</li>" for t in sorted(readings))
                       + "</ul>")
    else:
        out.append(f"<div class='note'>{_e(env.get('note'))}</div>")

    out.append(f"<div class='note'>{_e(a.get('note'))}</div></section>")
    return "".join(out)


_PRIORITY_TAG = {"alta": ("t-no", "Alta"), "media": ("t-mid", "Media"),
                 "baja": ("t-gray", "Baja")}


def _render_agenda(v: Dict[str, Any]) -> str:
    """The agenda leads the report: it is what the reader acts on."""
    out = ["<section><div class='kicker'>S5 · Agenda</div>",
           "<h2>Lo que el trimestre justifica discutir</h2>"]
    if not v.get("available"):
        return "".join(out) + _empty(v.get("reason")) + "</section>"

    ag = v["agenda"]
    if ag.get("empty_reason"):
        return "".join(out) + _empty(ag["empty_reason"]) + "</section>"

    for i, item in enumerate(ag["items"], start=1):
        cls, lbl = _PRIORITY_TAG.get(item["priority"], ("t-gray", item["priority"]))
        out.append(
            f"<div class='finding'><div class='figure'>{i}</div><div>"
            f"<h3>{_e(item['title'])} <span class='tag {cls}'>{_e(lbl)}</span></h3>"
            f"<p>{_e(item['rationale'])}</p>"
            + ("<p class='mono' style='font-size:11.5px;margin-top:4px'>"
               + " · ".join(_e(e) for e in item["evidence"]) + "</p>"
               if item.get("evidence") else "")
            + "</div></div>"
        )
    out.append(f"<div class='note'>{_e(ag.get('note'))}</div></section>")
    return "".join(out)


def _render_scenarios(s: Dict[str, Any]) -> str:
    out = ["<section><div class='kicker'>S4 · Escenarios y sensibilidad</div>",
           "<h2>Qué podría invalidar el pronóstico</h2>"]
    if not s.get("available"):
        return "".join(out) + _empty(s.get("reason")) + "</section>"

    out.append(f"<p class='lede'>{_e(s.get('note'))}</p>")
    out.append("<table><thead><tr><th>Escenario</th><th>Supuestos</th>"
               "<th>Lectura de la banda</th></tr></thead><tbody>")
    for sc in s.get("scenarios", []):
        band = {"sesgo_a_la_baja": "Sesgo a la baja", "sesgo_al_alza": "Sesgo al alza",
                "simetrica": "Simétrica"}.get(sc["band_reading"], sc["band_reading"])
        out.append(
            f"<tr><td><b>{_e(sc['label'])}</b></td>"
            f"<td>{' '.join(_e(a) for a in sc['assumptions'])}</td>"
            f"<td>{_e(band)}</td></tr>"
        )
    out.append("</tbody></table>")

    fragile = [d for d in s.get("rule_dispersion", []) if not d.get("robust")]
    if fragile:
        out.append(
            "<div class='note red'>Pronósticos que dependen de la regla elegida más que "
            "de la serie: " + ", ".join(f"<b>{_e(d['label'])}</b>" for d in fragile)
            + ". Léanse con reserva.</div>"
        )
    else:
        out.append("<div class='note'>Las tres reglas de pronóstico coinciden dentro de "
                   "la banda muestral en todos los indicadores: el resultado no depende "
                   "de cuál se elija.</div>")

    if s.get("risks"):
        out.append("<h3 style='font-size:13px;margin:16px 0 4px'>Riesgos declarados</h3><ul>")
        for r in s["risks"]:
            out.append(f"<li><b>{_e(r['risk'])}.</b> {_e(r['detail'])}</li>")
        out.append("</ul>")
    out.append("</section>")
    return "".join(out)


_STRENGTH_TAG = {"confirmada": ("t-ok", "Confirmada"),
                 "marginal": ("t-mid", "En el filo"),
                 "contextual": ("t-gray", "Contexto")}


def _render_vigilance(v: Dict[str, Any]) -> str:
    out = ["<section><div class='kicker'>S5 · Panel de vigilancia</div>",
           "<h2>Qué se movió desde la última entrega</h2>"]
    if not v.get("available"):
        return "".join(out) + _empty(v.get("reason")) + "</section>"

    out.append(f"<p class='lede'>{_e(v.get('note'))}</p>")
    labels = {"forecast": "Pronóstico", "tracker": "Tracker",
              "decision": "Decisiones", "macro": "Entorno macro"}
    any_row = False
    out.append("<table><thead><tr><th>Fuente</th><th>Señal</th><th>Lectura</th>"
               "<th>Fuerza</th></tr></thead><tbody>")
    for src in ("forecast", "tracker", "decision", "macro"):
        for sig_row in v["signals"].get(src, []):
            any_row = True
            cls, lbl = _STRENGTH_TAG.get(sig_row["strength"], ("t-gray", sig_row["strength"]))
            out.append(
                f"<tr><td>{_e(labels[src])}</td><td>{_e(sig_row['label'])}</td>"
                f"<td class='mono'>{_e(sig_row['reading'])}</td>"
                f"<td><span class='tag {cls}'>{_e(lbl)}</span></td></tr>"
            )
    out.append("</tbody></table>")
    if not any_row:
        out.append(_empty("Ninguna señal superó su umbral en el período."))

    confirmed = sum(
        1 for src in ("tracker", "forecast")
        for r in v["signals"].get(src, []) if r["strength"] == "confirmada"
    )
    if not confirmed:
        out.append(
            "<div class='note'>Ningún indicador del tracker superó su umbral detectable "
            "en esta transición de olas. La ausencia de movimiento confirmado es, en sí, "
            "una lectura: el trimestre fue de continuidad.</div>"
        )
    out.append("</section>")
    return "".join(out)


def _render_ticket(t: Dict[str, Any]) -> str:
    out = ["<section><div class='kicker'>S2 · Contexto económico</div>",
           "<h2>El ticket en pesos constantes</h2>"]
    if not t.get("available"):
        return "".join(out) + _empty(t.get("reason")) + "</section>"

    out.append("<table><thead><tr><th>Ola</th><th class='num'>Nominal</th>"
               "<th class='num'>Real</th></tr></thead><tbody>")
    for r in t["series"]:
        out.append(f"<tr><td>{_e(r['label'])}</td>"
                   f"<td class='num'>{_fmt(r['nominal'], '', 0)}</td>"
                   f"<td class='num'>{_fmt(r['real'], '', 0)}</td></tr>")
    out.append("</tbody></table>")

    if not t.get("deflated"):
        out.append(f"<div class='note red'>{_e(t.get('reason'))}</div>")
    else:
        chg = t.get("change_from_peak_pct")
        if chg is not None:
            out.append(
                f"<div class='note{' red' if chg < 0 else ''}'>Variación real desde el "
                f"máximo de la serie: <b>{_fmt(chg)}</b>. En términos nominales, la misma "
                f"serie se leería como estabilidad.</div>"
            )
        out.append(f"<div class='note'>{_e(t.get('deflator_note'))}</div>")
    out.append("</section>")
    return "".join(out)


def _render_forecast(s: Dict[str, Any]) -> str:
    bt, tr = s["forecast_backtest"], s["forecast_track_record"]
    out = ["<section><div class='kicker'>S4 · Proyección</div>",
           "<h2>Regla de pronóstico y track record</h2>"]
    if bt.get("available"):
        out.append("<table><thead><tr><th>Regla</th><th class='num'>Error medio</th>"
                   "<th class='num'>Series</th></tr></thead><tbody>")
        for i, r in enumerate(bt["ranking"]):
            cls = " class='focal'" if i == 0 else ""
            out.append(f"<tr{cls}><td>{_e(r['rule'])}</td>"
                       f"<td class='num'>{_fmt(r['mae'], ' pp', 2)}</td>"
                       f"<td class='num'>{r['n_series']}</td></tr>")
        out.append("</tbody></table>")
        out.append(f"<div class='note'>{_e(bt.get('note'))}</div>")
    else:
        out.append(_empty(bt.get("reason")))

    if tr.get("available"):
        out.append(
            f"<div class='note'>Track record en vivo: <b>{tr['n']}</b> pronósticos "
            f"puntuados, <b>{tr['hit_rate']:.0f}%</b> dentro de banda, error medio "
            f"{tr['mae']:.2f} pp.</div>"
        )
    else:
        out.append(f"<div class='note'>{_e(tr.get('reason'))}</div>")
    out.append("</section>")
    return "".join(out)


def _render_signal(sf: Dict[str, Any]) -> str:
    out = ["<section><div class='kicker'>S5 · Filtro de señal</div>",
           "<h2>Qué movimiento puede sostener una decisión</h2>"]
    if not sf.get("available"):
        return "".join(out) + _empty(sf.get("reason")) + "</section>"
    out.append(f"<p class='lede'>{_e(sf.get('note'))}</p>")
    out.append("<table><thead><tr><th>Indicador</th><th>Corte</th><th class='num'>Valor</th>"
               "<th class='num'>Base</th><th class='num'>Umbral</th><th>Estado</th>"
               "</tr></thead><tbody>")
    for r in sf["rows"]:
        tag = ("<span class='tag t-ok'>Utilizable</span>" if r["publishable"]
               else "<span class='tag t-no'>Base insuficiente</span>")
        out.append(f"<tr><td>{_e(r['label'])}</td><td>{_e(r['segment'])}</td>"
                   f"<td class='num'>{_fmt(r['value'])}</td>"
                   f"<td class='num'>{_e(r['base_n'] or '—')}</td>"
                   f"<td class='num'>{_fmt(r['threshold'], ' pp')}</td><td>{tag}</td></tr>")
    out.append("</tbody></table></section>")
    return "".join(out)


_STATUS_TAG = {
    "achieved": ("t-ok", "Logrado"),
    "worsened": ("t-no", "Empeoró"),
    "not_detectable": ("t-mid", "No detectable"),
    "unevaluable": ("t-gray", "Inevaluable"),
    "open": ("t-gray", "Abierta"),
}


def _render_decisions(d: Dict[str, Any]) -> str:
    out = ["<section><div class='kicker'>S5 · Ledger de decisiones</div>",
           "<h2>Seguimiento de las decisiones del cliente</h2>"]
    rows = d.get("decisions") or []
    if not rows:
        return "".join(out) + _empty(
            "Aún no hay decisiones registradas. Cada decisión requiere métrica, línea "
            "base, ventana de evaluación, umbral de éxito y responsable.") + "</section>"

    s = d["summary"]
    out.append(f"<p class='lede'>{s['total']} decisión(es) registrada(s): "
               f"{s['achieved']} lograda(s), {s['worsened']} con retroceso, "
               f"{s['inconclusive']} no concluyente(s), {s['unevaluable']} inevaluable(s), "
               f"{s['open']} abierta(s).</p>")
    out.append("<table><thead><tr><th>Decisión</th><th>Métrica</th>"
               "<th class='num'>Δ</th><th class='num'>Umbral</th><th>Veredicto</th>"
               "</tr></thead><tbody>")
    for r in rows:
        cls, lbl = _STATUS_TAG.get(r["status"], ("t-gray", r["status"]))
        out.append(
            f"<tr><td>{_e(r['title'])}"
            + (f"<br><span style='color:#6B7A8F;font-size:11px'>{_e(r['note'])}</span>"
               if r.get("note") else "")
            + f"</td><td>{_e(r['label'])}</td>"
            f"<td class='num'>{_fmt(r['observed_delta'], ' pp')}</td>"
            f"<td class='num'>{_fmt(r['detectable_threshold'], ' pp')}</td>"
            f"<td><span class='tag {cls}'>{_e(lbl)}</span></td></tr>"
        )
    out.append("</tbody></table></section>")
    return "".join(out)


def _render_method_sources_limits(p: Dict[str, Any]) -> str:
    out = ["<section><div class='kicker'>Anexo</div>",
           "<h2>Metodología, fuentes y límites</h2>"]
    if p["methodology"]:
        out.append("<h3 style='font-size:13px;margin:14px 0 4px'>Metodología</h3><ul>")
        for m in p["methodology"]:
            out.append(f"<li><b>{_e(m['title'])}.</b> {_e(m['text'])}</li>")
        out.append("</ul>")
    if p["sources"]:
        out.append("<h3 style='font-size:13px;margin:16px 0 4px'>Fuentes</h3><ul>")
        for s in p["sources"]:
            out.append(f"<li>{_e(s['name'])} — {_e(s['provider'])}</li>")
        out.append("</ul>")
    out.append("<h3 style='font-size:13px;margin:16px 0 4px'>Límites declarados</h3><ul>")
    for lim in p["limits"]:
        out.append(f"<li>{_e(lim)}</li>")
    out.append("</ul></section>")
    return "".join(out)
