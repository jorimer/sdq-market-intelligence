"""Market Brief — síntesis económica cross-eje de República Dominicana.

Raíz de composición (app/): lee el último estado persistido de cada eje a través
del **getter de servicio PÚBLICO** de cada módulo (nunca tablas ajenas en crudo),
genera un brief sintetizado con Claude y cachea {snapshot, brief, generated_at} en
AppSetting. Se registra como **Operación agendable** (Gate F) → un brief
semanal/diario puede correr headless desde la Consola de Operación.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation
from shared.settings.models import AppSetting

logger = logging.getLogger("sdq.market_brief")

MARKET_BRIEF_KEY = "market_brief_report"

RD_IRMP = "DO"    # ISO-2 de RD en el panel IRMP
RD_ESG = "DOM"    # ISO-3 de RD en el panel IRC


def _round(x: Any, n: int = 1) -> Optional[float]:
    return round(float(x), n) if x is not None else None


def assemble_snapshot(db) -> Dict[str, Any]:
    """Snapshot cross-eje desde el getter de servicio público de cada eje.

    Cada eje produce un bloque {eje, available, ...}. Un eje sin dato queda
    available=False (se excluye del prompt de IA — anti-fabricación).
    """
    axes: List[Dict[str, Any]] = []

    # ── Financiero (banking) ──
    try:
        from modules.banking_score.models.models import Bank, ModelType, RatingResult
        rows = db.query(RatingResult).filter(
            RatingResult.model_type == ModelType.deterministic
        ).all()
        cur = []
        if rows:
            latest = max(r.period_end for r in rows if r.period_end)
            cur = [r for r in rows if r.period_end == latest]
        if cur:
            names = {b.id: b.name for b in db.query(Bank).all()}
            scores = [float(r.overall_score) for r in cur if r.overall_score is not None]
            ranked = sorted(cur, key=lambda r: float(r.overall_score or 0), reverse=True)
            top, bot = ranked[0], ranked[-1]
            axes.append({
                "eje": "Financiero", "available": True, "period": str(latest),
                "headline": f"{len(cur)} entidades calificadas",
                "score": _round(sum(scores) / len(scores)) if scores else None,
                "score_label": "score promedio del sector",
                "detail": {
                    "n_entidades": len(cur),
                    "lider": {"nombre": names.get(top.bank_id, "?"),
                              "score": _round(top.overall_score), "rating": top.rating_tier},
                    "rezagado": {"nombre": names.get(bot.bank_id, "?"),
                                 "score": _round(bot.overall_score), "rating": bot.rating_tier},
                },
            })
        else:
            axes.append({"eje": "Financiero", "available": False})
    except Exception as e:  # noqa: BLE001
        logger.warning("brief: financiero no disponible: %s", e)
        axes.append({"eje": "Financiero", "available": False})

    # ── Macro & fiscal (contrato macro→sectorial: factores con lectura) ──
    try:
        from modules.macro_monitor.macro_context import build_macro_context
        ctx = build_macro_context(db)
        factors = [
            {"label": f.label, "value": _round(f.value, 2), "unit": f.unit,
             "direction": f.direction, "magnitude": f.magnitude, "reading": f.reading}
            for f in (ctx.factors or []) if f.value is not None
        ]
        axes.append({
            "eje": "Macro & fiscal", "available": bool(factors), "period": ctx.period,
            "headline": f"{len(factors)} factores macro con dato",
            "detail": {"factores": factors[:8]},
        })
    except Exception as e:  # noqa: BLE001
        logger.warning("brief: macro no disponible: %s", e)
        axes.append({"eje": "Macro & fiscal", "available": False})

    # ── Regulatorio & político (IRMP) — RD ──
    try:
        from modules.macro_political_risk import service as irmp_svc
        snap = irmp_svc.get_latest(db, RD_IRMP)
        if snap and snap.irmp_score is not None:
            axes.append({
                "eje": "Regulatorio & político", "available": True,
                "period": str(snap.period_end),
                "headline": "IRMP República Dominicana",
                "score": _round(snap.irmp_score),
                "score_label": "IRMP (mayor score = menor riesgo)",
                "band": snap.risk_band.value if snap.risk_band else None,
            })
        else:
            axes.append({"eje": "Regulatorio & político", "available": False})
    except Exception as e:  # noqa: BLE001
        logger.warning("brief: irmp no disponible: %s", e)
        axes.append({"eje": "Regulatorio & político", "available": False})

    # ── Comercio ──
    try:
        from modules.trade_intel import service as trade_svc
        ts = trade_svc.get_latest_score(db)
        if ts and ts.resilience_score is not None:
            axes.append({
                "eje": "Comercio", "available": True, "period": ts.period,
                "headline": "Resiliencia comercial",
                "score": _round(ts.resilience_score),
                "score_label": "índice de resiliencia",
                "detail": {"hhi_exportaciones": _round(ts.hhi_exports, 3),
                           "diversificacion_export": _round(ts.export_diversification)},
            })
        else:
            axes.append({"eje": "Comercio", "available": False})
    except Exception as e:  # noqa: BLE001
        logger.warning("brief: comercio no disponible: %s", e)
        axes.append({"eje": "Comercio", "available": False})

    # ── Social (IDM) — promedio + extremos regionales ──
    try:
        from modules.social_dev import service as social_svc
        rows = [r for r in social_svc.get_scores(db) if r.development_score is not None]
        if rows:
            latest = max(r.period for r in rows)
            cur = [r for r in rows if r.period == latest]
            vals = [float(r.development_score) for r in cur]
            ranked = sorted(cur, key=lambda r: float(r.development_score), reverse=True)
            axes.append({
                "eje": "Social", "available": True, "period": latest,
                "headline": f"IDM · {len(cur)} regiones",
                "score": _round(sum(vals) / len(vals)),
                "score_label": "IDM promedio regional",
                "detail": {
                    "n_regiones": len(cur),
                    "mejor": {"region": ranked[0].entity_key, "idm": _round(ranked[0].development_score)},
                    "peor": {"region": ranked[-1].entity_key, "idm": _round(ranked[-1].development_score)},
                    "dispersion": _round(max(vals) - min(vals)),
                },
            })
        else:
            axes.append({"eje": "Social", "available": False})
    except Exception as e:  # noqa: BLE001
        logger.warning("brief: social no disponible: %s", e)
        axes.append({"eje": "Social", "available": False})

    # ── ESG & clima (IRC) — RD ──
    try:
        from modules.esg_climate import service as esg_svc
        s = esg_svc.get_latest(db, RD_ESG)
        if s and s.esg_score is not None:
            axes.append({
                "eje": "ESG & clima", "available": True, "period": s.period,
                "headline": "IRC República Dominicana",
                "score": _round(s.esg_score),
                "score_label": "resiliencia climática",
                "band": s.band,
            })
        else:
            axes.append({"eje": "ESG & clima", "available": False})
    except Exception as e:  # noqa: BLE001
        logger.warning("brief: esg no disponible: %s", e)
        axes.append({"eje": "ESG & clima", "available": False})

    # ── Sectorial (IAI) — top/bottom ──
    try:
        from modules.sector_intel import service as sector_svc
        scores = [s for s in sector_svc.get_latest_scores(db) if s.iai_score is not None]
        if scores:
            names = {s.code: s.name for s in sector_svc.get_sectors(db)}
            def _row(s):
                return {"sector": names.get(s.sector_code, s.sector_code), "iai": _round(s.iai_score)}
            axes.append({
                "eje": "Sectorial", "available": True, "period": scores[0].period,
                "headline": f"IAI · {len(scores)} sectores",
                "detail": {
                    "n_sectores": len(scores),
                    "mas_atractivos": [_row(s) for s in scores[:3]],
                    "menos_atractivos": [_row(s) for s in scores[-3:]],
                },
            })
        else:
            axes.append({"eje": "Sectorial", "available": False})
    except Exception as e:  # noqa: BLE001
        logger.warning("brief: sectorial no disponible: %s", e)
        axes.append({"eje": "Sectorial", "available": False})

    return {"pais": "República Dominicana", "axes": axes}


def _generate_brief_text(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Run the (async) narrative engine in this thread (operations run in a worker
    thread with no event loop, so asyncio.run is safe)."""
    from shared.narrative.claude_engine import narrative_engine
    res = asyncio.run(narrative_engine.generate(ctx, template="market_brief", mode="detailed"))
    return {"text": res.text, "model_used": res.model_used, "from_cache": res.from_cache}


def _run_market_brief(params, user_id, set_phase) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        set_phase("ensamblando snapshot cross-eje")
        snapshot = assemble_snapshot(db)
        available = [a for a in snapshot["axes"] if a.get("available")]
        if not available:
            return {"error": "sin datos en ningún eje; corre los syncs primero",
                    "errors": ["sin datos"]}
        set_phase(f"generando brief con IA ({len(available)} ejes con dato)")
        brief = None
        try:
            brief = _generate_brief_text({"pais": snapshot["pais"], "ejes": available})
        except Exception as e:  # noqa: BLE001 — el snapshot se cachea aunque la IA falle
            logger.warning("brief: narrativa IA no disponible: %s", e)
        report = {
            "snapshot": snapshot,
            "brief": brief,
            "n_ejes_con_dato": len(available),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        row = db.query(AppSetting).filter(AppSetting.key == MARKET_BRIEF_KEY).first()
        payload = json.dumps(report, ensure_ascii=False, default=str)
        if row:
            row.value = payload
        else:
            db.add(AppSetting(key=MARKET_BRIEF_KEY, value=payload, is_secret=False))
        db.commit()
        return {"n_ejes_con_dato": len(available),
                "ai": (brief or {}).get("model_used", "no disponible"), "errors": []}
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "market-brief", "Generar Market Brief",
        "Ensambla el estado de los 7 ejes (financiero, macro-fiscal, regulatorio, "
        "comercio, social, ESG, sectorial) y genera un brief de mercado ejecutivo de "
        "RD con Claude. Cachea el resultado; agendable para un brief recurrente.",
        _run_market_brief, default_interval_hours=168,  # semanal
    ))


register()
