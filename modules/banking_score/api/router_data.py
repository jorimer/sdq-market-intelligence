"""Banking Score — Data management endpoints.

prefix: /api/v1/banking-score/data
Extracted from monolith router_banking_scoring.py.
"""
import csv
import io
import logging
from datetime import date
from typing import Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User, UserRole
from shared.database.session import get_db
from modules.banking_score.models.models import (
    Bank,
    BankingData,
    DataSource,
)

logger = logging.getLogger("sdq.api.data")

router = APIRouter()

# Template columns — matches BankingData model fields
TEMPLATE_COLUMNS = [
    "bank_name", "period_end", "period_type",
    "patrimonio_tecnico", "apr", "capital_primario", "exposicion_total",
    "capital_tier1", "contingentes", "riesgo_mercado",
    "provisiones", "cartera_vencida_90d", "activos_totales",
    "cartera_bruta", "cartera_categoria_a", "cartera_total",
    "suma_top10", "hhi_sectorial_raw", "castigos",
    "exposicion_re", "cartera_a_prev",
    "utilidad_neta", "activos_promedio", "patrimonio_promedio",
    "ingresos_financieros", "gastos_financieros", "activos_productivos_avg",
    "gastos_operacionales", "ingresos_operacionales",
    "caja_valores", "pasivos_cp", "cartera_neta", "depositos_totales",
    "activos_liquidos", "pasivos_exigibles",
    "hhi_ingresos_raw",
]

NUMERIC_FIELDS = [c for c in TEMPLATE_COLUMNS if c not in ("bank_name", "period_end", "period_type")]


# ─── CSV Template Download ───────────────────────────────────────

@router.get(
    "/template",
    summary="Descargar template CSV",
    description="Descarga un archivo CSV con las 33 columnas requeridas para datos bancarios.",
)
async def download_template(
    current_user: User = Depends(get_current_user),
):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(TEMPLATE_COLUMNS)
    # Example row
    writer.writerow([
        "Banco Popular Dominicano", "2024-12-31", "quarterly",
        "45000000000", "280000000000", "35000000000", "310000000000",
        "35000000000", "5000000000", "2000000000",
        "8500000000", "4200000000", "450000000000",
        "250000000000", "220000000000", "250000000000",
        "35000000000", "1800", "1200000000",
        "95000000000", "215000000000",
        "12000000000", "440000000000", "42000000000",
        "28000000000", "8000000000", "200000000000",
        "15000000000", "25000000000",
        "35000000000", "120000000000", "240000000000", "300000000000",
        "85000000000", "180000000000",
        "2800",
    ])
    csv_bytes = output.getvalue().encode("utf-8")

    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sdq_banking_template.csv"},
    )


# ─── Upload Banking Data ─────────────────────────────────────────

@router.post(
    "/upload",
    summary="Subir datos bancarios (CSV/Excel)",
    description="Sube un archivo CSV o Excel con datos financieros de un banco.",
)
async def upload_banking_data(
    file: UploadFile = File(...),
    bank_id: str = Query(..., description="ID del banco al que asociar los datos"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    bank = db.query(Bank).filter_by(id=bank_id).first()
    if not bank:
        raise HTTPException(status_code=404, detail=f"Banco {bank_id} no encontrado")

    content = await file.read()
    filename = file.filename or "upload.csv"

    if filename.endswith(".csv"):
        rows = _parse_csv(content)
    elif filename.endswith((".xlsx", ".xls")):
        rows = _parse_excel(content)
    else:
        raise HTTPException(status_code=400, detail="Formato no soportado. Use CSV o Excel.")

    if not rows:
        raise HTTPException(status_code=400, detail="No se encontraron filas de datos en el archivo")

    required = {"period_end"}
    first_row_keys = set(rows[0].keys())
    missing = required - first_row_keys
    if missing:
        raise HTTPException(status_code=400, detail=f"Columnas requeridas faltantes: {', '.join(missing)}")

    created = 0
    updated = 0
    errors: List[str] = []

    for i, row in enumerate(rows):
        try:
            period_end_str = row.get("period_end", "").strip()
            if not period_end_str:
                errors.append(f"Fila {i + 2}: falta period_end")
                continue

            pe = date.fromisoformat(period_end_str)
            period_type = row.get("period_type", "quarterly").strip()

            existing = db.query(BankingData).filter_by(bank_id=bank_id, period_end=pe).first()
            record = existing or BankingData(bank_id=bank_id, period_end=pe)

            for field in NUMERIC_FIELDS:
                val = row.get(field, "").strip() if row.get(field) else ""
                if val:
                    try:
                        setattr(record, field, float(val))
                    except (ValueError, TypeError):
                        pass

            record.period_type = period_type
            record.source = DataSource.csv_upload
            record.uploaded_by = current_user.id

            if not existing:
                db.add(record)
                created += 1
            else:
                updated += 1
        except Exception as e:
            errors.append(f"Fila {i + 2}: {str(e)}")

    db.commit()

    return {
        "success": True,
        "bank_id": bank_id,
        "bank_name": bank.name,
        "records_created": created,
        "records_updated": updated,
        "total_rows": len(rows),
        "errors": errors[:10],
    }


# ─── Raw data for a bank ─────────────────────────────────────────

@router.get(
    "/{bank_id}/raw",
    summary="Ver datos crudos de un banco",
    description="Lista todos los períodos de datos financieros cargados para un banco.",
)
async def get_raw_data(
    bank_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    records = (
        db.query(BankingData)
        .filter_by(bank_id=bank_id)
        .order_by(BankingData.period_end.desc())
        .all()
    )
    return {
        "bank_id": bank_id,
        "periods": [
            {
                "id": r.id,
                "period_end": str(r.period_end),
                "period_type": r.period_type.value if r.period_type else "quarterly",
                "source": r.source.value if r.source else "manual",
                "created_at": str(r.created_at) if r.created_at else None,
            }
            for r in records
        ],
        "count": len(records),
    }


# ─── Seed Banks ──────────────────────────────────────────────────

@router.post(
    "/seed-banks",
    summary="Seed 35 bancos dominicanos",
    description="Crea las 35 entidades reguladas por la SIB y 5 años de datos históricos. Requiere rol admin.",
)
async def seed_banks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Se requiere rol admin")

    try:
        from modules.banking_score.seed.banking_seed import seed_banks as do_seed
        result = do_seed()
        return {"success": True, "detail": result}
    except Exception as e:
        logger.error(f"Error en seed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── SIB Sync ────────────────────────────────────────────────────

@router.post(
    "/sib-sync",
    summary="Sincronizar con API SIB",
    description="Sincroniza datos bancarios desde la API de la Superintendencia de Bancos. Requiere SIB_API_KEY.",
)
async def sync_from_sib(
    period_end: str = Query("", description="Período final YYYY-MM (vacío = mes actual)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Se requiere rol admin")

    # SIB client stub — will be implemented in PASO 5
    return {
        "success": False,
        "message": "Cliente SIB pendiente de implementación en Paso 5",
    }


# ─── SIB Backfill ────────────────────────────────────────────────

@router.post(
    "/sib-backfill",
    summary="Backfill histórico desde SIB",
    description="Reemplaza datos sintéticos con datos reales de la API SIB. Requiere rol admin.",
)
async def sib_backfill(
    force: bool = Query(False, description="Forzar re-ejecución aunque ya existan datos SIB"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Se requiere rol admin")

    # SIB backfill stub — will be implemented in PASO 5
    return {
        "success": False,
        "message": "Backfill SIB pendiente de implementación en Paso 5",
    }


# ─── Sync Status ─────────────────────────────────────────────────

@router.get(
    "/sync-status",
    summary="Estado de sincronización",
    description="Retorna el estado de sincronización con la API SIB.",
)
async def get_sync_status(
    current_user: User = Depends(get_current_user),
):
    # Stub — will be implemented in PASO 5
    return {
        "is_running": False,
        "last_sync": None,
        "next_scheduled": None,
        "alerts": [],
    }


# ─── Helpers ─────────────────────────────────────────────────────

def _parse_csv(content: bytes) -> List[Dict[str, str]]:
    """Parse CSV content into list of dicts (handles BOM)."""
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def _parse_excel(content: bytes) -> List[Dict[str, str]]:
    """Parse Excel content using openpyxl."""
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(
            status_code=400,
            detail="openpyxl no está instalado. Use CSV en su lugar.",
        )
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    headers = [str(h).strip().lower() if h else "" for h in next(rows_iter)]
    result = []
    for row in rows_iter:
        d = {}
        for h, v in zip(headers, row):
            if h:
                d[h] = str(v).strip() if v is not None else ""
        result.append(d)
    wb.close()
    return result
