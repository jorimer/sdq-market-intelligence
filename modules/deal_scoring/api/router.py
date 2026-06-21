"""Deal Scoring — registro de deals (cosecha del dataset de entrenamiento).

Module-local: lee/escribe SOLO `HistoricalDeal` (su propia tabla), sin acople
cross-módulo. El scorer cross-eje vive aparte en `app/deal_scoring_api.py`.
  - POST /import    — carga masiva por CSV (admin) del set validado, sin versionar datos.
  - POST /deals     — guarda un deal scoreado (cosecha going-forward).
  - GET  /deals     — lista el registro.
  - GET  /learning-curve — ¿ya vale la pena el modelo entrenado? (CV-AUC + IC).
"""
import csv
import io
import logging
from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User, UserRole
from shared.database.session import get_db
from modules.deal_scoring.models.models import (
    DealStage, DealType, HistoricalDeal, LabelConfidence, Sector,
)

logger = logging.getLogger("sdq.deal_scoring.registry")

router = APIRouter()


def _enum(enum_cls, val, default=None):
    v = (str(val).strip().lower() if val is not None else "")
    try:
        return enum_cls(v) if v else default
    except ValueError:
        return default


def _bool(val) -> Optional[bool]:
    s = str(val).strip().lower()
    if s in ("1", "true", "sí", "si", "yes", "cerrado"):
        return True
    if s in ("0", "false", "no", "perdido"):
        return False
    return None


def _num(val):
    s = str(val).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


@router.post("/import", summary="Cargar deals por CSV (admin)")
async def import_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Upsert por `deal_name`. Columnas: deal_name, deal_type, sector, country,
    deal_size_usd, equity_required_pct, deal_stage, closed_successfully,
    label_confidence, source_folder, note (las 4 señales de analista opcionales)."""
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Se requiere rol admin")
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    inserted = updated = skipped = 0
    for row in reader:
        name = (row.get("deal_name") or "").strip()
        dt = _enum(DealType, row.get("deal_type"))
        sec = _enum(Sector, row.get("sector"))
        if not name or dt is None or sec is None:
            skipped += 1
            continue
        country = (row.get("country") or "").strip().upper()[:2] or "DO"
        d = db.query(HistoricalDeal).filter_by(deal_name=name).one_or_none()
        is_new = d is None
        if is_new:
            d = HistoricalDeal(deal_name=name)
        d.deal_type = dt
        d.sector = sec
        d.country = country
        d.deal_size_usd = _num(row.get("deal_size_usd"))
        d.equity_required_pct = _num(row.get("equity_required_pct"))
        d.deal_stage = _enum(DealStage, row.get("deal_stage"))
        d.closed_successfully = _bool(row.get("closed_successfully"))
        for c in ("promoter_track_record", "financial_quality", "market_validation",
                  "regulatory_readiness", "days_since_first_contact"):
            v = _num(row.get(c))
            if v is not None:
                setattr(d, c, int(v))
        d.label_confidence = _enum(LabelConfidence, row.get("label_confidence"),
                                   default=LabelConfidence.baja)
        d.source_folder = (row.get("source_folder") or "").strip() or None
        d.note = (row.get("note") or "").strip() or None
        if is_new:
            db.add(d)
            inserted += 1
        else:
            updated += 1
    db.commit()
    return {"inserted": inserted, "updated": updated, "skipped": skipped,
            "total": db.query(HistoricalDeal).count()}


@router.post("/deals", summary="Guardar un deal en el registro (cosecha)")
async def save_deal(
    body: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    name = (body.get("deal_name") or "").strip()
    dt = _enum(DealType, body.get("deal_type"))
    sec = _enum(Sector, body.get("sector"))
    if not name or dt is None or sec is None:
        raise HTTPException(status_code=400, detail="Se requiere deal_name, deal_type y sector válidos.")
    if db.query(HistoricalDeal).filter_by(deal_name=name).first():
        raise HTTPException(status_code=409, detail="Ya existe un deal con ese nombre.")
    d = HistoricalDeal(
        deal_name=name, deal_type=dt, sector=sec,
        country=(body.get("country") or "DO").strip().upper()[:2] or "DO",
        deal_size_usd=_num(body.get("deal_size_usd")),
        equity_required_pct=_num(body.get("equity_required_pct")),
        deal_stage=_enum(DealStage, body.get("deal_stage")),
        closed_successfully=_bool(body.get("closed_successfully")) if body.get("closed_successfully") not in (None, "") else None,
        label_confidence=LabelConfidence.baja,
        note=(body.get("note") or "").strip() or None,
    )
    for c in ("promoter_track_record", "financial_quality", "market_validation", "regulatory_readiness"):
        v = _num(body.get(c))
        if v is not None:
            setattr(d, c, int(max(0, min(100, v))))
    od = _num(body.get("days_since_first_contact"))
    if od is not None:
        d.days_since_first_contact = int(od)
    if d.closed_successfully is not None:
        d.outcome_date = date.today()
    db.add(d)
    db.commit()
    return {"saved": True, "deal_name": name, "total": db.query(HistoricalDeal).count()}


@router.get("/deals", summary="Listar el registro de deals")
async def list_deals(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    rows = db.query(HistoricalDeal).order_by(HistoricalDeal.created_at.desc()).all()
    n_labeled = sum(1 for d in rows if d.closed_successfully is not None)
    return {
        "count": len(rows), "n_labeled": n_labeled,
        "deals": [{
            "deal_name": d.deal_name, "deal_type": d.deal_type.value if d.deal_type else None,
            "sector": d.sector.value if d.sector else None, "country": d.country,
            "deal_stage": d.deal_stage.value if d.deal_stage else None,
            "closed_successfully": d.closed_successfully,
            "label_confidence": d.label_confidence.value if d.label_confidence else None,
        } for d in rows],
    }


@router.get("/learning-curve", summary="Estado del modelo: ¿rúbrica o entrenado? (CV-AUC + IC)")
async def learning_curve(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    from modules.deal_scoring.validation.learning_curve import build_report
    return build_report(db)
