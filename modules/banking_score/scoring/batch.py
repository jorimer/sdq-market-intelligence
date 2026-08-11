"""Batch scoring — reusable scoring of every entity in one or more periods.

This is the single source of truth for *persisting* ratings. Both the
``/run-all`` API endpoint and the post-sync recalculation (SIB backfill) call
``score_period`` / ``score_all_periods`` so the math and the rating-action
detection stay identical regardless of who triggers them.

Automated callers (the SIB sync) pass ``created_by=None`` — the column is
nullable. Interactive callers (the API) pass the requesting user's id.
"""
import logging
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from modules.banking_score.events import overlay_outlook
from modules.banking_score.models.models import (
    ActionType,
    Bank,
    BankingData,
    DataSource,
    ModelType,
    Outlook,
    RatingAction,
    RatingResult,
)
from modules.banking_score.scoring.engine import run_scoring
from modules.banking_score.scoring.ttm import attach_ttm

logger = logging.getLogger("sdq.banking.scoring.batch")


def _delta_eje(previo, nuevo):
    """Δ de un eje, o None si falta cualquiera de los dos extremos (brecha declarada)."""
    if previo is None or nuevo is None:
        return None
    return round(float(nuevo) - float(previo), 2)


def detect_rating_action(
    db: Session,
    bank_id: str,
    period_end: date,
    scoring_result: Dict[str, Any],
    user_id: Optional[str],
) -> Optional[Dict]:
    """Compare current scoring with the previous period and create a
    RatingAction if applicable. Returns a summary dict, or None if there's no
    prior period to compare against.
    """
    previous = (
        db.query(RatingResult)
        .filter(RatingResult.bank_id == bank_id, RatingResult.period_end < period_end)
        .order_by(RatingResult.period_end.desc())
        .first()
    )
    if not previous:
        return None

    score_delta = round(float(scoring_result["overall_score"]) - float(previous.overall_score), 2)
    prev_tier = previous.rating_tier
    new_tier = scoring_result["rating_tier"]

    # ¿El cambio viene de la METODOLOGÍA o de la entidad? Si la versión de modelo difiere,
    # el movimiento no es deterioro ni mejora del banco: es que la vara cambió. El
    # `action_type` sigue siendo el real, pero la marca evita que una recalibración se lea
    # en el histórico como 44 downgrades simultáneos.
    metodologica = bool(previous.model_version
                        and scoring_result.get("model_version")
                        and previous.model_version != scoring_result["model_version"])

    if new_tier != prev_tier:
        action_type = (
            ActionType.upgrade
            if scoring_result["overall_score"] > float(previous.overall_score)
            else ActionType.downgrade
        )
    elif abs(score_delta) >= 2.0:
        action_type = ActionType.observacion
    else:
        action_type = ActionType.confirmacion

    base_outlook = (
        Outlook.positiva if score_delta > 3 else (Outlook.negativa if score_delta < -3 else Outlook.estable)
    )
    # IRMP overlay: the macro-political environment biases the outlook, not the score.
    ov = overlay_outlook(base_outlook.value, "DO")
    outlook = Outlook(ov["outlook"])

    action = RatingAction(
        bank_id=bank_id,
        period_end=period_end,
        action_type=action_type,
        previous_period_end=previous.period_end,
        previous_score=previous.overall_score,
        previous_tier=prev_tier,
        new_score=scoring_result["overall_score"],
        new_tier=new_tier,
        score_delta=score_delta,
        # La acción POR EJE nace junto con la del tier, no se rellena después: sin esto,
        # cada período nuevo volvería a necesitar el re-etiquetado retroactivo.
        banda_ejecucion_previa=previous.banda_ejecucion,
        banda_ejecucion_nueva=scoring_result.get("banda_ejecucion"),
        banda_resiliencia_previa=previous.banda_resiliencia,
        banda_resiliencia_nueva=scoring_result.get("banda_resiliencia"),
        ejecucion_delta=_delta_eje(previous.ejecucion_score,
                                   scoring_result.get("ejecucion")),
        resiliencia_delta=_delta_eje(previous.resiliencia_score,
                                     scoring_result.get("resiliencia")),
        outlook=outlook,
        previous_sub_components={
            "solidez": float(previous.solidez_score or 0),
            "calidad": float(previous.calidad_score or 0),
            "eficiencia": float(previous.eficiencia_score or 0),
            "liquidez": float(previous.liquidez_score or 0),
            "diversificacion": float(previous.diversificacion_score or 0),
        },
        new_sub_components=scoring_result["sub_components"],
        metodologica=metodologica,
        created_by=user_id,
    )
    db.add(action)

    return {
        "action_type": action_type.value,
        "metodologica": metodologica,
        "previous_tier": prev_tier,
        "new_tier": new_tier,
        "score_delta": score_delta,
        "outlook": outlook.value,
        "outlook_irmp_band": ov["irmp_band"],
        "outlook_adjusted_by_irmp": ov["adjusted"],
    }


def _persistir_perfil_del_periodo(db: Session, period_end: date) -> int:
    """Calcula y persiste los dos ejes de Perfil SDQ para el panel de un período.

    Se llama una vez terminado el scoring del período completo: los cortes de Ejecución son
    los cuartiles de las entidades del MISMO tipo y período, así que no existen mientras el
    panel esté a medio escorear.
    """
    from modules.banking_score.scoring.perfil_sdq import perfil_panel

    filas = (db.query(RatingResult)
             .filter(RatingResult.period_end == period_end,
                     RatingResult.model_type == ModelType.deterministic).all())
    if not filas:
        return 0
    tipos = {b.id: b.bank_type for b in db.query(Bank).all()}

    def _f(v):
        return float(v) if v is not None else None

    entradas = [{"_row": r, "entity_type": tipos.get(r.bank_id), "sub_scores": {
        "solidez": _f(r.solidez_score), "calidad": _f(r.calidad_score),
        "eficiencia": _f(r.eficiencia_score), "liquidez": _f(r.liquidez_score),
        "diversificacion": _f(r.diversificacion_score)}} for r in filas]
    for e in perfil_panel(entradas)["entidades"]:
        row = e["_row"]
        row.ejecucion_score = e["ejecucion"]
        row.resiliencia_score = e["resiliencia"]
        row.banda_ejecucion = e["banda_ejecucion"]
        row.banda_resiliencia = e["banda_resiliencia"]
    db.commit()
    return len(entradas)


def _upsert_rating(
    db: Session,
    bank_id: str,
    period_end: date,
    result: Dict[str, Any],
    user_id: Optional[str],
) -> None:
    """Insert or update the deterministic RatingResult for (bank, period)."""
    existing = (
        db.query(RatingResult)
        .filter_by(bank_id=bank_id, period_end=period_end, model_type=ModelType.deterministic)
        .first()
    )
    subs = result["sub_components"]
    if existing:
        existing.overall_score = result["overall_score"]
        existing.rating_tier = result["rating_tier"]
        existing.solidez_score = subs["solidez"]
        existing.calidad_score = subs["calidad"]
        existing.eficiencia_score = subs["eficiencia"]
        existing.liquidez_score = subs["liquidez"]
        existing.diversificacion_score = subs["diversificacion"]
        existing.indicator_details = result["indicators"]
        existing.model_version = result["model_version"]
    else:
        db.add(RatingResult(
            bank_id=bank_id,
            period_end=period_end,
            overall_score=result["overall_score"],
            rating_tier=result["rating_tier"],
            solidez_score=subs["solidez"],
            calidad_score=subs["calidad"],
            eficiencia_score=subs["eficiencia"],
            liquidez_score=subs["liquidez"],
            diversificacion_score=subs["diversificacion"],
            indicator_details=result["indicators"],
            model_type=ModelType.deterministic,
            model_version=result["model_version"],
            created_by=user_id,
        ))


def score_period(
    db: Session,
    period_end: date,
    created_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Score every entity that has data in *period_end*, persist the ratings and
    rating actions, and commit. Returns a summary (scored count, per-bank
    results, errors, rating-action tallies).
    """
    # Never score synthetic seed data (source=manual): it must never produce a
    # rating, even if a residue survives. Real sources only (sib_api/simbad/csv).
    records = (
        db.query(BankingData)
        .filter(BankingData.period_end == period_end,
                BankingData.source != DataSource.manual)
        .all()
    )
    results: List[Dict] = []
    errors: List[Dict] = []

    for record in records:
        try:
            bank = db.query(Bank).filter_by(id=record.bank_id).first()
            entity_type = bank.bank_type.value if bank and bank.bank_type else None
            # Ventana móvil de 12 meses (ROA/ROE). Ver scoring/ttm.
            attach_ttm(db, record)
            scoring_result = run_scoring(record, entity_type=entity_type)
            _upsert_rating(db, record.bank_id, period_end, scoring_result, created_by)
            action_info = detect_rating_action(db, record.bank_id, period_end, scoring_result, created_by)
            results.append({
                "bank_id": record.bank_id,
                "bank_name": bank.name if bank else "Desconocido",
                "overall_score": scoring_result["overall_score"],
                "rating_tier": scoring_result["rating_tier"],
                "rating_action": action_info,
            })
        except Exception as e:  # noqa: BLE001 — one bad record must not abort the batch
            errors.append({"bank_id": record.bank_id, "error": str(e)})

    db.commit()

    # Perfil SDQ se calcula sobre el PANEL COMPLETO del período, no entidad por entidad: los
    # cortes de Ejecución salen de los cuartiles de las entidades de su mismo tipo, así que no
    # existen hasta que todas están escoreadas. Por eso va acá y no dentro de `_upsert_rating`.
    try:
        _persistir_perfil_del_periodo(db, period_end)
    except Exception as e:  # noqa: BLE001 — Perfil SDQ nunca debe tumbar el scoring
        logger.warning("Perfil SDQ no persistido para %s: %s", period_end, e)

    summary = {"upgrades": 0, "downgrades": 0, "confirmaciones": 0, "observaciones": 0}
    for r in results:
        act = r.get("rating_action")
        if act:
            key = act.get("action_type", "")
            if key == "upgrade":
                summary["upgrades"] += 1
            elif key == "downgrade":
                summary["downgrades"] += 1
            elif key == "confirmacion":
                summary["confirmaciones"] += 1
            elif key == "observacion":
                summary["observaciones"] += 1

    return {
        "period_end": str(period_end),
        "scored": len(results),
        "errors": errors,
        "results": results,
        "rating_actions_summary": summary,
    }


def score_all_periods(
    db: Session,
    only_sib: bool = True,
    created_by: Optional[str] = None,
    on_progress: Optional[Callable[[int, int, date], None]] = None,
) -> Dict[str, Any]:
    """Score every period that has data, oldest-first (so rating-action deltas
    build chronologically).

    *only_sib* restricts to periods that contain at least one real (non-``manual``)
    record — i.e. skips purely synthetic/seed periods while keeping SIMBAD and
    CSV-upload periods (both real sources). *on_progress(i, total, period)* is
    called before each period for visible progress reporting.
    """
    q = db.query(BankingData.period_end).distinct()
    if only_sib:
        q = q.filter(BankingData.source != DataSource.manual)
    # Never score quarters that haven't closed yet — their data is partial.
    today = date.today()
    periods = sorted(pe for (pe,) in q.all() if pe <= today)

    total_scored = 0
    per_period: List[Dict] = []
    for i, pe in enumerate(periods, 1):
        if on_progress:
            on_progress(i, len(periods), pe)
        res = score_period(db, pe, created_by=created_by)
        total_scored += res["scored"]
        per_period.append({"period_end": res["period_end"], "scored": res["scored"], "errors": len(res["errors"])})

    ratings_total = db.query(func.count(RatingResult.id)).scalar() or 0
    logger.info("Batch scoring: %d periods, %d ratings written, %d total ratings",
                len(periods), total_scored, ratings_total)
    return {
        "periods_scored": len(periods),
        "ratings_written": total_scored,
        "ratings_total": ratings_total,
        "per_period": per_period,
    }
