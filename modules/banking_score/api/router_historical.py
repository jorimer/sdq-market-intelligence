"""API de la vista *Histórico* (Cronología SB): cohorte de quiebras + forense por entidad.

prefix: /api/v1/banking-score/historical

Alimenta la página analítica del front. Solo lectura, gateada por sesión (cualquier usuario
autenticado). El dato es real y de fuente pública; no es un producto del catálogo comercial.
"""
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User
from shared.database.session import get_db
from shared.products.filenames import content_disposition, report_filename
from modules.banking_score import historical_service as svc
from modules.banking_score.products import SECTOR_KEY

logger = logging.getLogger("sdq.api.banking.historical")

router = APIRouter()


@router.get("/entities", summary="Entidades del histórico SIB (1947→) con su rango")
async def historical_entities(
    only_exited: bool = Query(False, description="Solo entidades que salieron del sistema (foco forense)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return {"entities": svc.list_entities(db, only_exited=only_exited)}


@router.get("/cohort", summary="Backtest de Alerta Temprana sobre la cohorte de quiebras")
async def historical_cohort(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """La validación del motor con dato real: cuántos meses antes del colapso se habría
    encendido la primera alerta de cluster para cada entidad quebrada."""
    return svc.cohort_backtest(db)


@router.get("/forensic", summary="Paquete forense de una entidad histórica")
async def historical_forensic(
    nombre: str = Query(..., description="Nombre exacto de la entidad (entidad_nombre)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trayectoria mensual de ratios (morosidad, cobertura, apalancamiento, fuga de depósitos)
    + timeline de alertas de Alerta Temprana para una entidad."""
    pkg = svc.forensic_package(db, nombre)
    if pkg is None:
        raise HTTPException(status_code=404, detail=f"Sin dato histórico para '{nombre}'.")
    return pkg


@router.get("/forensic/narrative", summary="Lectura forense (narrativa IA) de una entidad")
async def historical_forensic_narrative(
    nombre: str = Query(..., description="Nombre exacto de la entidad (entidad_nombre)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Genera la prosa forense ('anatomía de una quiebra') vía el cerebro, sobre el dato real."""
    res = await svc.forensic_narrative(db, nombre)
    if res is None:
        raise HTTPException(status_code=404, detail=f"Sin dato histórico para '{nombre}'.")
    return res


@router.get("/forensic/report", summary="Informe forense branded (PDF o Word descargable)")
async def historical_forensic_report(
    nombre: str = Query(..., description="Nombre exacto de la entidad (entidad_nombre)"),
    fmt: str = Query("pdf", description="Formato del informe: 'pdf' o 'docx' (Word)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Documento forense branded (portada SDQ·MIP + gráficos del dato real + lectura +
    fuentes) — la versión 'informe' descargable de la vista Histórico. ``fmt=pdf`` (default)
    o ``fmt=docx`` para el Word editable con la misma anatomía."""
    pkg = svc.forensic_package(db, nombre)
    if pkg is None:
        raise HTTPException(status_code=404, detail=f"Sin dato histórico para '{nombre}'.")
    narr = await svc.forensic_narrative(db, nombre)
    narrative = (narr or {}).get("narrative", "")
    degraded = bool((narr or {}).get("degraded"))
    # Mismo esquema que el resto de las descargas. El forense no tiene un corte único (es una
    # serie histórica), así que el período del nombre es la FECHA DE GENERACIÓN: sin ella,
    # dos corridas de la misma entidad producen el mismo archivo y la segunda pisa a la primera.
    def _nombre(ext: str) -> str:
        return report_filename(
            sector_key=SECTOR_KEY, naturaleza="Forense", sujeto=nombre,
            periodo=date.today().isoformat(), fmt=ext)

    if fmt == "docx":
        from modules.banking_score.reports.forensic_docx import render_forensic_docx
        data = render_forensic_docx(pkg, narrative, degraded=degraded)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": content_disposition(_nombre("docx"))})

    from modules.banking_score.reports.forensic_pdf import render_forensic_pdf
    pdf = render_forensic_pdf(pkg, narrative, degraded=degraded)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": content_disposition(_nombre("pdf"))})
