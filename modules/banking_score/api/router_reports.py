"""Banking Score — Reports & Rating Actions endpoints.

prefix: /api/v1/banking-score/reports
Extracted from monolith router_banking_scoring.py.
"""
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User
from shared.database.session import get_db
from shared.narrative.claude_engine import NarrativeDegradedError, degraded_sections
from modules.banking_score.scoring.benchmarks import panel_benchmarks
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

# Reportes de cliente cuyo VALOR es la narrativa (el "SDQ Rating" / deep dive de la entidad):
# si el análisis IA se degradó a fallback estático, NO deben marcarse `completed`. Los boletines
# de sistema (wire/datawatch/sector_outlook/communique/criteria) no se gatean aquí.
_PREMIUM_REPORT_TYPES = {"full_rating", "scorecard"}
_NARRATIVE_DEGRADED_MSG = (
    "El análisis de este informe no está disponible en este momento por un límite temporal "
    "del servicio de generación. Reintente en unos minutos."
)

# Informes de SISTEMA: no cuelgan de una entidad (``bank_id`` NULL). Describen la
# metodología (criteria) o el sistema entero (wire/datawatch/sector_outlook).
_SYSTEM_REPORT_TYPES = {"criteria", "wire", "datawatch", "sector_outlook"}

# Boletines de sistema que se NARRAN con IA y cuyo único insumo son las cifras del sector.
# `criteria` no está: es determinista, se genera del motor y no consume benchmarks.
_NARRATED_SYSTEM_TYPES = {"wire", "datawatch", "sector_outlook"}


def _attach_pdf(report: Report, file_path: str, narratives: dict,
                model: Optional[str] = None) -> None:
    """Marca el reporte completado y guarda los bytes del PDF en la DB.

    El archivo en disco vive en el FS EFÍMERO del contenedor y desaparece en cada
    redeploy; sin el blob la fila sobrevive pero la re-descarga da 404. ``file_path`` se
    conserva por compatibilidad y para derivar el nombre de archivo.
    """
    from pathlib import Path

    pdf_bytes = Path(file_path).read_bytes()
    report.status = ReportStatus.completed
    report.file_path = file_path
    report.file_blob = pdf_bytes
    report.file_size = len(pdf_bytes)
    report.completed_at = datetime.now(timezone.utc)
    # `model` explícito para el documento determinista: registrar "claude" en un texto que
    # ningún modelo escribió sería una traza falsa de procedencia.
    report.narrative_model = model or ("claude" if narratives else "none")


async def _generate_system_report(
    *,
    report_type: str,
    scope_name: str,
    period: str,
    db: Session,
    current_user: User,
    benchmarks: dict | None = None,
    extra: dict | None = None,
) -> dict:
    """Genera y PERSISTE un informe de sistema, devolviendo un ``report_id`` descargable.

    Estos boletines antes solo devolvían ``file_path``: sin fila ``Report`` no existía
    ``GET /reports/download/{report_id}`` para ellos, y el PDF moría con el FS efímero
    del contenedor. Ahora siguen el mismo contrato que el endpoint por banco.
    """
    from modules.banking_score.reports.narrative import generate_report_narratives
    from modules.banking_score.reports.pdf_generator import generate_pdf_report

    pe = None
    if period:
        try:
            pe = date.fromisoformat(period)
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Formato de fecha inválido. Use YYYY-MM-DD")

    report = Report(
        bank_id=None,
        period_end=pe,
        report_type=ReportType(report_type),
        status=ReportStatus.generating,
        narrative_model="pending",
        generated_by=current_user.id,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    scoring_result: Dict[str, Any] = {
        "overall_score": 0, "banda_ejecucion": None, "banda_resiliencia": None,
        "sub_components": {}, "indicators": {},
    }
    # Un boletín NARRADO de sistema sin benchmarks no tiene NADA que analizar: su único
    # insumo son las cifras del sector. `wire` se generó siempre sin ellos —datawatch y
    # sector_outlook sí los pasaban— y el modelo, correctamente, respondía que no había
    # cifras sectoriales; esa negativa quedaba impresa como cuerpo del PDF. Se resuelven acá
    # y no en cada endpoint para que el próximo boletín no pueda nacer con el mismo hueco.
    if benchmarks is None and report_type in _NARRATED_SYSTEM_TYPES:
        benchmarks = panel_benchmarks(db, pe)
    try:
        if report_type == "criteria":
            # El documento de criterios es la METODOLOGÍA: determinista, no varía por
            # corrida. Se GENERA de la configuración del motor (pesos, escala, registro de
            # indicadores, backtest vivo) para que no pueda desviarse de cómo se califica
            # realmente. Antes se pedía a la IA narrar una plantilla por-banco con un
            # scoring_result vacío: el estándar epistémico se negaba —correctamente— a
            # fabricar, y ese rechazo terminaba impreso en el PDF de cliente.
            from modules.banking_score.reports.criteria_doc import build_criteria_document
            narratives = build_criteria_document(db)
        else:
            narratives = await generate_report_narratives(
                report_type=report_type, bank_name=scope_name,
                scoring_result=scoring_result, period=period, benchmarks=benchmarks,
            )
        file_path = await generate_pdf_report(
            report_type=report_type, bank_name=scope_name,
            scoring_result=scoring_result, period=period, narratives=narratives,
        )
        _attach_pdf(report, file_path, narratives,
                    model="deterministic" if report_type == "criteria" else None)
    except Exception as e:
        logger.error("%s generation failed: %s", report_type, e)
        report.status = ReportStatus.error
        report.error_message = str(e)
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))

    db.commit()
    logger.info("Informe de sistema %s generado | ID=%s | %d bytes",
                report_type, report.id, report.file_size or 0)

    return {
        "success": True,
        "report_id": report.id,
        "report_type": report_type,
        "period_end": period or None,
        "status": report.status.value,
        "file_path": report.file_path,
        **(extra or {}),
    }


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

    # Un informe de sistema no tiene banco ni, en el caso de `criteria`, período: el
    # nombre se arma con las partes que existen para no emitir "..._None.pdf".
    bank = db.query(Bank).filter_by(id=report.bank_id).first() if report.bank_id else None
    scope = (bank.name if bank else "Sistema").replace(" ", "_")
    parts = [f"SDQ_{report.report_type.value}", scope]
    if report.period_end:
        parts.append(str(report.period_end))
    filename = "_".join(parts) + ".pdf"

    # Primary: serve the PDF bytes from the DB (durable, survives redeploys).
    if report.file_blob:
        return Response(
            content=report.file_blob,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # Fallback: legacy reports with only a disk path (pre-blob). These vanish on
    # redeploy of the ephemeral FS, so this may 404 — surface a clear message.
    if report.file_path:
        from pathlib import Path
        file_path = Path(report.file_path)
        if file_path.exists():
            return FileResponse(
                path=str(file_path),
                media_type="application/pdf",
                filename=filename,
            )

    raise HTTPException(
        status_code=404,
        detail="Archivo de reporte no disponible. Vuelva a generar el reporte.",
    )


# ─── List System Reports ────────────────────────────────────────

@router.get(
    "/system/list",
    summary="Listar informes de sistema",
    description="Lista los informes transversales (criteria/wire/datawatch/sector_outlook), "
                "que no cuelgan de una entidad.",
)
async def list_system_reports(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Contraparte de ``/{bank_id}/list`` para los informes sin banco.

    Sin esto no eran DESCUBRIBLES: el listado por banco filtra por ``bank_id`` y estos lo
    tienen NULL, así que el ``report_id`` solo existía en la respuesta de la generación —
    si se perdía, el informe quedaba inalcanzable salvo por consulta directa a la BD.
    """
    reports = (
        db.query(Report)
        .filter(Report.bank_id.is_(None))
        .order_by(Report.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "reports": [
            {
                "id": r.id,
                "report_type": r.report_type.value if r.report_type else None,
                "period_end": str(r.period_end) if r.period_end else None,
                "status": r.status.value if r.status else None,
                "created_at": str(r.created_at) if r.created_at else None,
                "file_size": r.file_size,
            }
            for r in reports
        ],
        "count": len(reports),
    }


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
        # El comunicado se redacta sobre los DOS EJES, no sobre el símbolo retirado.
        "banda_ejecucion": action.banda_ejecucion_nueva,
        "banda_resiliencia": action.banda_resiliencia_nueva,
        "transicion_ejecucion": transicion(_s(action.banda_ejecucion_previa),
                                           _s(action.banda_ejecucion_nueva)),
        "transicion_resiliencia": transicion(_s(action.banda_resiliencia_previa),
                                             _s(action.banda_resiliencia_nueva)),
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
        # Mismo defecto que tenían las rutas estáticas: sin el blob la fila sobrevive al
        # redeploy pero la descarga da 404 (el FS del contenedor es efímero).
        _attach_pdf(report, file_path, narratives)
    except Exception as e:
        logger.error("Communiqué PDF failed: %s", e)
        report.status = ReportStatus.error
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
    return await _generate_system_report(
        report_type="wire", scope_name="Sistema Bancario", period=period_end,
        db=db, current_user=current_user,
    )


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
    return await _generate_system_report(
        report_type="datawatch", scope_name="Sistema Bancario", period=period_end,
        db=db, current_user=current_user,
    )


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
    return await _generate_system_report(
        report_type="sector_outlook", scope_name=f"Sector: {sector}", period=period_end,
        db=db, current_user=current_user,
        extra={"sector": sector},
    )


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
    return await _generate_system_report(
        report_type="criteria", scope_name="SDQ Rating", period="",
        db=db, current_user=current_user,
    )


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
            "ejecucion": float(rating.ejecucion_score) if rating.ejecucion_score is not None else None,
            "banda_ejecucion": rating.banda_ejecucion,
            "resiliencia": float(rating.resiliencia_score) if rating.resiliencia_score is not None else None,
            "banda_resiliencia": rating.banda_resiliencia,
            "sub_components": {
                "solidez": float(rating.solidez_score or 0),
                "calidad": float(rating.calidad_score or 0),
                "eficiencia": float(rating.eficiencia_score or 0),
                "liquidez": float(rating.liquidez_score or 0),
                "diversificacion": float(rating.diversificacion_score or 0),
            },
            "indicators": rating.indicator_details or {},
            # Tipo de entidad: acota la comparación a SU grupo de pares —
            # medir un banco múltiple contra agentes de cambio es ruido.
            "entity_type": bank.bank_type.value if bank.bank_type else None,
        }
    else:
        scoring_result = {
            "overall_score": 0,
            "ejecucion": None, "banda_ejecucion": None,
            "resiliencia": None, "banda_resiliencia": None,
            "sub_components": {},
            "indicators": {},
        }

    try:
        from modules.banking_score.reports.narrative import generate_report_narratives
        from modules.banking_score.reports.pdf_generator import generate_pdf_report
        # Benchmarks MEDIDOS del panel en el MISMO corte del informe: comparar un Q1
        # contra una constante ANUAL invertía la conclusión (ver scoring/benchmarks).
        benchmarks = panel_benchmarks(db, pe)
        narratives = await generate_report_narratives(
            report_type=report_type,
            bank_name=bank.name,
            scoring_result=scoring_result,
            period=period_end,
            benchmarks=benchmarks,
        )
        # GATE DE DEGRADACIÓN: en un reporte premium (SDQ Rating / deep dive de la entidad)
        # una sola sección de análisis caída a fallback estático produce un PDF hueco. Se
        # detecta ANTES de renderizar (no se desperdicia el render) y se aborta como `error`
        # con un mensaje de reintento — nunca `completed`. La causa (outage/429 o presupuesto)
        # es indistinta: el marcador `static_fallback` la cubre por igual.
        degraded = degraded_sections(narratives, list(narratives.keys()))
        if degraded and report_type in _PREMIUM_REPORT_TYPES:
            from shared.narrative.degradation_events import emit_narrative_degraded
            emit_narrative_degraded(
                surface="banking_legacy", sector_key="banking", tier=report_type,
                sections=degraded, blocked=True, scope=bank.name, period=period_end)
            raise NarrativeDegradedError(degraded)
        file_path = await generate_pdf_report(
            report_type=report_type,
            bank_name=bank.name,
            scoring_result=scoring_result,
            period=period_end,
            narratives=narratives,
        )
        _attach_pdf(report, file_path, narratives)
    except NarrativeDegradedError as d:
        # No es un fallo de código: es degradación transitoria del servicio de narrativa.
        # Se marca `error` (con las secciones afectadas) y se responde 503 (reintento).
        report.status = ReportStatus.error
        report.narrative_model = "static_fallback"
        report.error_message = (
            "Narrativa IA no disponible por límite temporal; reintente. "
            f"Secciones afectadas: {', '.join(d.sections)}")
        report.completed_at = None
        db.commit()
        logger.warning("Reporte %s premium para %s con %d sección(es) degradada(s): "
                       "no se completa (%s).", report_type, bank.name, len(d.sections), d.sections)
        raise HTTPException(status_code=503, detail=_NARRATIVE_DEGRADED_MSG)
    except Exception as e:
        logger.error("PDF generation failed: %s", e)
        report.status = ReportStatus.error
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

from modules.banking_score.scoring.acciones_por_eje import transicion  # noqa: E402


def _s(v) -> Optional[str]:
    """Columna → str|None. SQLAlchemy las tipa como Column[str] en el modelo."""
    return None if v is None else str(v)


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
        # Un movimiento de tier causado por un cambio de METODOLOGÍA, no de la entidad.
        # Sin exponerlo, quien lea las acciones no puede distinguir un deterioro real de
        # una recalibración — y el `action_type` por sí solo dice "downgrade" en ambos casos.
        "metodologica": bool(action.metodologica),
        # Perfil SDQ: la acción POR EJE. `previous_tier`/`new_tier` quedan como LINAJE del
        # dato hasta que la superficie termine de migrar (§9) — la lectura primaria son
        # estas dos transiciones, que el símbolo único no podía expresar por separado.
        "banda_ejecucion_previa": action.banda_ejecucion_previa,
        "banda_ejecucion_nueva": action.banda_ejecucion_nueva,
        "banda_resiliencia_previa": action.banda_resiliencia_previa,
        "banda_resiliencia_nueva": action.banda_resiliencia_nueva,
        "ejecucion_delta": float(action.ejecucion_delta) if action.ejecucion_delta is not None else None,
        "resiliencia_delta": float(action.resiliencia_delta) if action.resiliencia_delta is not None else None,
        "transicion_ejecucion": transicion(_s(action.banda_ejecucion_previa),
                                           _s(action.banda_ejecucion_nueva)),
        "transicion_resiliencia": transicion(_s(action.banda_resiliencia_previa),
                                             _s(action.banda_resiliencia_nueva)),
        "created_at": str(action.created_at) if action.created_at else None,
    }
