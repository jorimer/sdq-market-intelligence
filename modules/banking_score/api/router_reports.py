"""Banking Score — Reports & Rating Actions endpoints.

prefix: /api/v1/banking-score/reports
Extracted from monolith router_banking_scoring.py.
"""
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User
from shared.database.session import get_db
from modules.banking_score.models.models import (
    Bank,
    RatingAction,
    RatingResult,
    Report,
    ReportStatus,
    ReportType,
)

logger = logging.getLogger("sdq.api.reports")

router = APIRouter()


# ═══════════════════════════════════════════════════════════════
# STATIC ROUTES — must come BEFORE /{bank_id}/* dynamic routes
# ═══════════════════════════════════════════════════════════════


# ─── Download Report ─────────────────────────────────────────────

@router.get(
    "/download/{report_id}",
    summary="Descargar PDF",
    description="Descarga un reporte PDF generado previamente.",
)
async def download_report(
    report_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    report = db.query(Report).filter_by(id=report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail=f"Reporte {report_id} no encontrado")

    if report.status != ReportStatus.completed:
        raise HTTPException(
            status_code=400,
            detail=f"Reporte no completado (estado: {report.status.value})",
        )

    if not report.file_path:
        raise HTTPException(
            status_code=404,
            detail="Archivo de reporte no disponible aún. Generación PDF en Paso 5.",
        )

    from pathlib import Path
    file_path = Path(report.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Archivo de reporte no encontrado en disco")

    bank = db.query(Bank).filter_by(id=report.bank_id).first()
    bank_name = (bank.name if bank else "entity").replace(" ", "_")
    filename = f"SDQ_{report.report_type.value}_{bank_name}_{report.period_end}.pdf"

    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=filename,
    )


# ─── All Rating Actions (cross-bank) ────────────────────────────

@router.get(
    "/rating-actions/all",
    summary="Todas las acciones de rating",
    description="Lista todas las acciones de rating de todos los bancos.",
)
async def list_all_rating_actions(
    period_end: str = Query(None, description="Filtro por período (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(RatingAction, Bank).join(Bank, Bank.id == RatingAction.bank_id)

    if period_end:
        try:
            pe = date.fromisoformat(period_end)
            query = query.filter(RatingAction.period_end == pe)
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de fecha inválido")

    results = query.order_by(RatingAction.created_at.desc()).limit(limit).all()

    actions = [
        {**_action_to_dict(a), "bank_name": bank.name}
        for a, bank in results
    ]
    return {"actions": actions, "count": len(actions)}


# ─── Generate Communiqué ─────────────────────────────────────────

@router.post(
    "/rating-actions/{action_id}/communique",
    summary="Generar communiqué PDF",
    description="Genera un communiqué PDF para una acción de rating específica.",
)
async def generate_communique(
    action_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    action = db.query(RatingAction).filter_by(id=action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail=f"Acción de rating {action_id} no encontrada")

    bank = db.query(Bank).filter_by(id=action.bank_id).first()

    report = Report(
        bank_id=action.bank_id,
        period_end=action.period_end,
        report_type=ReportType.communique,
        status=ReportStatus.generating,
        narrative_model="pending",
        generated_by=current_user.id,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    scoring_result = {
        "overall_score": float(action.new_score),
        "rating_tier": action.new_tier,
        "tier_color": "",
        "sub_components": {},
        "indicators": {},
    }

    try:
        from modules.banking_score.reports.narrative import generate_report_narratives
        from modules.banking_score.reports.pdf_generator import generate_pdf_report

        narratives = await generate_report_narratives(
            report_type="communique",
            bank_name=bank.name if bank else "Entity",
            scoring_result=scoring_result,
            period=str(action.period_end),
        )
        file_path = await generate_pdf_report(
            report_type="communique",
            bank_name=bank.name if bank else "Entity",
            scoring_result=scoring_result,
            period=str(action.period_end),
            narratives=narratives,
        )
        report.status = ReportStatus.completed
        report.file_path = file_path
    except Exception as e:
        logger.error("Communiqué PDF failed: %s", e)
        report.status = ReportStatus.failed
        report.error_message = str(e)

    action.communique_report_id = report.id
    db.commit()

    return {
        "report_id": report.id,
        "action_id": action_id,
        "bank_name": bank.name if bank else None,
        "action_type": action.action_type.value,
        "status": report.status.value,
        "file_path": report.file_path,
    }


# ─── Wire ────────────────────────────────────────────────────────

@router.post(
    "/wire/generate",
    summary="Generar SDQ Wire",
    description="Genera un boletín crediticio SDQ Wire con narrativa AI.",
)
async def generate_wire(
    period_end: str = Query(..., description="Fecha fin del período (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        from modules.banking_score.reports.narrative import generate_report_narratives
        from modules.banking_score.reports.pdf_generator import generate_pdf_report

        scoring_result = {"overall_score": 0, "rating_tier": "N/A", "sub_components": {}, "indicators": {}}
        narratives = await generate_report_narratives(
            report_type="wire", bank_name="Sistema Bancario",
            scoring_result=scoring_result, period=period_end,
        )
        file_path = await generate_pdf_report(
            report_type="wire", bank_name="Sistema Bancario",
            scoring_result=scoring_result, period=period_end, narratives=narratives,
        )
        return {"success": True, "file_path": file_path, "period_end": period_end}
    except Exception as e:
        logger.error("Wire generation failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ─── DataWatch ───────────────────────────────────────────────────

@router.post(
    "/datawatch/generate",
    summary="Generar DataWatch",
    description="Genera un reporte DataWatch con análisis comparativo del sistema bancario.",
)
async def generate_datawatch(
    period_end: str = Query(..., description="Fecha fin del período (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        from modules.banking_score.reports.narrative import generate_report_narratives
        from modules.banking_score.reports.pdf_generator import generate_pdf_report
        from modules.banking_score.external.sib_client import sib_client

        benchmarks = sib_client.get_sector_benchmarks()
        scoring_result = {"overall_score": 0, "rating_tier": "N/A", "sub_components": {}, "indicators": {}}
        narratives = await generate_report_narratives(
            report_type="datawatch", bank_name="Sistema Bancario",
            scoring_result=scoring_result, period=period_end, benchmarks=benchmarks,
        )
        file_path = await generate_pdf_report(
            report_type="datawatch", bank_name="Sistema Bancario",
            scoring_result=scoring_result, period=period_end, narratives=narratives,
        )
        return {"success": True, "file_path": file_path, "period_end": period_end}
    except Exception as e:
        logger.error("DataWatch generation failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ─── Sector Outlook ──────────────────────────────────────────────

@router.post(
    "/sector-outlook/generate",
    summary="Generar Sector Outlook",
    description="Genera un reporte de perspectivas del sector con narrativa AI.",
)
async def generate_sector_outlook(
    sector: str = Query("banking", description="Sector (e.g. banking)"),
    period_end: str = Query(..., description="Fecha fin del período (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        from modules.banking_score.reports.narrative import generate_report_narratives
        from modules.banking_score.reports.pdf_generator import generate_pdf_report
        from modules.banking_score.external.sib_client import sib_client

        benchmarks = sib_client.get_sector_benchmarks()
        scoring_result = {"overall_score": 0, "rating_tier": "N/A", "sub_components": {}, "indicators": {}}
        narratives = await generate_report_narratives(
            report_type="sector_outlook", bank_name=f"Sector: {sector}",
            scoring_result=scoring_result, period=period_end, benchmarks=benchmarks,
        )
        file_path = await generate_pdf_report(
            report_type="sector_outlook", bank_name=f"Sector: {sector}",
            scoring_result=scoring_result, period=period_end, narratives=narratives,
        )
        return {"success": True, "file_path": file_path, "period_end": period_end, "sector": sector}
    except Exception as e:
        logger.error("Sector Outlook generation failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ─── Criteria ────────────────────────────────────────────────────

@router.post(
    "/criteria/generate",
    summary="Generar Criteria",
    description="Genera un documento de criterios y metodología SDQ Rating.",
)
async def generate_criteria(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        from modules.banking_score.reports.narrative import generate_report_narratives
        from modules.banking_score.reports.pdf_generator import generate_pdf_report

        scoring_result = {"overall_score": 0, "rating_tier": "N/A", "sub_components": {}, "indicators": {}}
        narratives = await generate_report_narratives(
            report_type="criteria", bank_name="SDQ Rating",
            scoring_result=scoring_result, period="",
        )
        file_path = await generate_pdf_report(
            report_type="criteria", bank_name="SDQ Rating",
            scoring_result=scoring_result, period="", narratives=narratives,
        )
        return {"success": True, "file_path": file_path}
    except Exception as e:
        logger.error("Criteria generation failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# DYNAMIC ROUTES — /{bank_id}/* patterns
# ═══════════════════════════════════════════════════════════════


# ─── Generate Report ─────────────────────────────────────────────

@router.post(
    "/{bank_id}/generate",
    summary="Generar reporte",
    description="Genera un reporte PDF para un banco y período. Tipos: full_rating, scorecard, communique, datawatch, wire, criteria, sector_outlook.",
)
async def generate_report(
    bank_id: str,
    period_end: str = Query(..., description="Fecha fin del período (YYYY-MM-DD)"),
    report_type: str = Query("full_rating", description="Tipo de reporte"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    bank = db.query(Bank).filter_by(id=bank_id).first()
    if not bank:
        raise HTTPException(status_code=404, detail=f"Banco {bank_id} no encontrado")

    try:
        pe = date.fromisoformat(period_end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido. Use YYYY-MM-DD")

    # Validate report_type
    valid_types = [rt.value for rt in ReportType]
    if report_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de reporte inválido. Opciones: {', '.join(valid_types)}",
        )

    # Check that a rating exists for this bank/period
    rating = db.query(RatingResult).filter_by(bank_id=bank_id, period_end=pe).first()
    if not rating and report_type in ("full_rating", "scorecard"):
        raise HTTPException(
            status_code=400,
            detail=f"No existe rating para {bank.name} en {period_end}. Ejecute scoring primero.",
        )

    # Create report record
    report = Report(
        bank_id=bank_id,
        period_end=pe,
        report_type=ReportType(report_type),
        status=ReportStatus.generating,
        narrative_model="pending",
        generated_by=current_user.id,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    logger.info("Reporte creado: %s para %s | %s | ID=%s", report_type, bank.name, period_end, report.id)

    # Build scoring result for the PDF
    from modules.banking_score.scoring.rating_scale import get_tier_color

    scoring_result = None
    if rating:
        scoring_result = {
            "overall_score": float(rating.overall_score),
            "rating_tier": rating.rating_tier,
            "tier_color": get_tier_color(rating.rating_tier),
            "sub_components": {
                "solidez": float(rating.solidez_score or 0),
                "calidad": float(rating.calidad_score or 0),
                "eficiencia": float(rating.eficiencia_score or 0),
                "liquidez": float(rating.liquidez_score or 0),
                "diversificacion": float(rating.diversificacion_score or 0),
            },
            "indicators": rating.indicator_details or {},
        }
    else:
        scoring_result = {
            "overall_score": 0,
            "rating_tier": "N/A",
            "tier_color": "#6B7280",
            "sub_components": {},
            "indicators": {},
        }

    try:
        from modules.banking_score.reports.narrative import generate_report_narratives
        from modules.banking_score.reports.pdf_generator import generate_pdf_report
        from modules.banking_score.external.sib_client import sib_client

        benchmarks = sib_client.get_sector_benchmarks()
        narratives = await generate_report_narratives(
            report_type=report_type,
            bank_name=bank.name,
            scoring_result=scoring_result,
            period=period_end,
            benchmarks=benchmarks,
        )
        file_path = await generate_pdf_report(
            report_type=report_type,
            bank_name=bank.name,
            scoring_result=scoring_result,
            period=period_end,
            narratives=narratives,
        )
        report.status = ReportStatus.completed
        report.file_path = file_path
        report.narrative_model = "claude" if narratives else "none"
    except Exception as e:
        logger.error("PDF generation failed: %s", e)
        report.status = ReportStatus.failed
        report.error_message = str(e)

    db.commit()

    return {
        "report_id": report.id,
        "bank_id": bank_id,
        "bank_name": bank.name,
        "period_end": period_end,
        "report_type": report_type,
        "status": report.status.value,
        "file_path": report.file_path,
    }


# ─── List Reports for a bank ────────────────────────────────────

@router.get(
    "/{bank_id}/list",
    summary="Listar reportes de un banco",
    description="Lista todos los reportes generados para un banco.",
)
async def list_reports(
    bank_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    reports = (
        db.query(Report)
        .filter_by(bank_id=bank_id)
        .order_by(Report.created_at.desc())
        .all()
    )
    return {
        "bank_id": bank_id,
        "reports": [
            {
                "id": r.id,
                "report_type": r.report_type.value if r.report_type else None,
                "period_end": str(r.period_end) if r.period_end else None,
                "status": r.status.value if r.status else None,
                "created_at": str(r.created_at) if r.created_at else None,
                "file_path": r.file_path,
            }
            for r in reports
        ],
        "count": len(reports),
    }


# ─── Rating Actions (per bank) ──────────────────────────────────

@router.get(
    "/{bank_id}/rating-actions",
    summary="Historial de acciones de rating",
    description="Lista las acciones de rating (upgrade/downgrade/confirmación) de un banco.",
)
async def list_bank_rating_actions(
    bank_id: str,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    actions = (
        db.query(RatingAction)
        .filter_by(bank_id=bank_id)
        .order_by(RatingAction.period_end.desc())
        .limit(limit)
        .all()
    )
    bank = db.query(Bank).filter_by(id=bank_id).first()
    return {
        "bank_id": bank_id,
        "bank_name": bank.name if bank else None,
        "actions": [_action_to_dict(a) for a in actions],
        "count": len(actions),
    }


# ─── Helpers ─────────────────────────────────────────────────────

def _action_to_dict(action: RatingAction) -> dict:
    return {
        "id": action.id,
        "bank_id": action.bank_id,
        "period_end": str(action.period_end),
        "action_type": action.action_type.value if action.action_type else None,
        "previous_period_end": str(action.previous_period_end) if action.previous_period_end else None,
        "previous_score": float(action.previous_score) if action.previous_score else None,
        "previous_tier": action.previous_tier,
        "new_score": float(action.new_score),
        "new_tier": action.new_tier,
        "score_delta": float(action.score_delta) if action.score_delta else None,
        "outlook": action.outlook.value if action.outlook else None,
        "created_at": str(action.created_at) if action.created_at else None,
    }
