"""Banking Score — Data management endpoints.

prefix: /api/v1/banking-score/data
Extracted from monolith router_banking_scoring.py.
"""
import csv
import io
import logging
from datetime import date
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User, UserRole, role_satisfies
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
    summary="Seed del catálogo de entidades dominicanas",
    description="Crea (idempotente) las entidades reguladas por la SIB. Solo el "
    "catálogo: NO siembra datos financieros (esos vienen de fuentes reales: SIB/"
    "SIMBAD/CSV). Requiere rol admin.",
)
async def seed_banks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_satisfies(current_user.role, UserRole.admin):
        raise HTTPException(status_code=403, detail="Se requiere rol admin")

    try:
        from modules.banking_score.seed.banking_seed import seed_banks as do_seed
        result = do_seed()
        return {"success": True, "detail": result}
    except Exception as e:
        logger.error(f"Error en seed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── SIB Backfill (replace synthetic data with real SIB data) ────

@router.post(
    "/sib-backfill",
    summary="Backfill histórico desde SIB",
    description="Reemplaza datos sintéticos con datos reales de la API SIB (en segundo plano). Requiere rol admin y clave SIB configurada.",
)
async def sib_backfill(
    force: bool = Query(False, description="Forzar re-ejecución aunque ya existan datos SIB"),
    tipos: Optional[str] = Query(None, description="Re-ingesta dirigida: lista de tipos separados por coma (p.ej. 'BAC,AAP'). Omite los demás tipos y el fallback SIMBAD."),
    skip_carteras: bool = Query(False, description="Omite la agregación del cubo de carteras (el cuello de botella de 504s). Re-ingesta income/balance/indicadores/solvencia y preserva las métricas de carteras existentes. Útil para recalibraciones que solo tocan el estado de resultados (p.ej. cost-to-income)."),
    current_user: User = Depends(get_current_user),
):
    if not role_satisfies(current_user.role, UserRole.admin):
        raise HTTPException(status_code=403, detail="Se requiere rol admin")
    from modules.banking_score.sib_sync import start_backfill_background
    only_tipos = [t.strip() for t in tipos.split(",") if t.strip()] if tipos else None
    return start_backfill_background(force=force, only_tipos=only_tipos, skip_carteras=skip_carteras)


# Backward-compatible alias for /sib-sync → triggers the same backfill.
@router.post("/sib-sync", summary="Sincronizar con API SIB", include_in_schema=False)
async def sync_from_sib(
    force: bool = Query(False, description="Forzar re-ingesta aunque ya haya datos / un backfill reciente (admin override)"),
    tipos: Optional[str] = Query(None, description="Re-ingesta dirigida: lista de tipos separados por coma (p.ej. 'BAC,AAP')."),
    skip_carteras: bool = Query(False, description="Omite la agregación del cubo de carteras (504s). Re-ingesta income/balance/indicadores/solvencia y preserva las métricas de carteras existentes."),
    current_user: User = Depends(get_current_user),
):
    if not role_satisfies(current_user.role, UserRole.admin):
        raise HTTPException(status_code=403, detail="Se requiere rol admin")
    from modules.banking_score.sib_sync import start_backfill_background
    only_tipos = [t.strip() for t in tipos.split(",") if t.strip()] if tipos else None
    return start_backfill_background(force=force, only_tipos=only_tipos, skip_carteras=skip_carteras)


# ─── Rescore (recompute ratings from existing data, no re-ingest) ─

@router.post(
    "/rescore",
    summary="Recalcular ratings desde los datos existentes",
    description="Recalcula y persiste los ratings de todos los períodos con datos, sin volver a descargar del SIB. Útil tras cargar datos o ajustar pesos. Requiere rol admin.",
)
async def rescore(
    only_sib: bool = Query(True, description="Solo períodos con datos del SIB (omite datos sintéticos)"),
    current_user: User = Depends(get_current_user),
):
    if not role_satisfies(current_user.role, UserRole.admin):
        raise HTTPException(status_code=403, detail="Se requiere rol admin")
    from shared import operations
    return operations.trigger("rescore", origin="manual", user_id=current_user.id,
                              params={"only_sib": only_sib})


@router.post(
    "/prune-future",
    summary="Eliminar trimestres no cerrados (futuros)",
    description="Borra datos y ratings de períodos cuyo trimestre aún no cerró (period_end > hoy). El SIB devuelve el trimestre en curso con datos parciales que distorsionan el ranking. Se regeneran al cerrar el trimestre. Requiere rol admin.",
)
async def prune_future(
    current_user: User = Depends(get_current_user),
):
    if not role_satisfies(current_user.role, UserRole.admin):
        raise HTTPException(status_code=403, detail="Se requiere rol admin")
    from shared import operations
    return operations.trigger("prune-future", origin="manual", user_id=current_user.id)


# ─── Sync Status ─────────────────────────────────────────────────

@router.get(
    "/sync-status",
    summary="Estado de sincronización",
    description="Estado de la sincronización con la API SIB (para la tarjeta 'Sincronización SIB').",
)
async def sync_status(
    current_user: User = Depends(get_current_user),
):
    from modules.banking_score.sib_sync import get_sync_status
    st = get_sync_status()
    # Keep the legacy keys the frontend already reads, plus the richer fields.
    st["next_scheduled"] = st.get("next_scheduled")
    return st


# Operation-console status/schedule endpoints moved to the platform router
# (shared/operations/router.py, prefix /api/v1/operations). The per-operation
# triggers below stay for back-compat; the console uses /operations/{name}/run.


# ─── SIB raw page diagnostic (test pagination semantics) ─────────

@router.get("/sib-page-test", include_in_schema=False)
async def sib_page_test(
    endpoint: str = Query("estados/resultados/eif"),
    tipo: str = Query("BM"),
    periodo_inicial: str = Query("2024-01"),
    periodo_final: str = Query("2024-12"),
    paginas: int = Query(1),
    registros: int = Query(100),
    grep: str = Query("", description="Filtrar filas crudas cuyo path de concepto contenga este término"),
    entidad: str = Query("", description="Filtrar por código de entidad (en vez de tipo). Aísla un banco."),
    current_user: User = Depends(get_current_user),
):
    """Single raw page from the SIB API — to learn if `paginas`/`registros` are
    honored (compare pages, try big registros). Returns count + a fingerprint."""
    if not role_satisfies(current_user.role, UserRole.admin):
        raise HTTPException(status_code=403, detail="Se requiere rol admin")
    from modules.banking_score.external.sib_data_client import get_sib_data_client, _norm
    import httpx as _httpx

    client = get_sib_data_client(force_new=True)
    if client is None:
        raise HTTPException(status_code=400, detail="SIB no configurada.")
    url = f"{client.base_url}/{endpoint.lstrip('/')}"
    # The SIB API takes EITHER entidad OR tipoEntidad — entidad isolates one bank.
    params = {
        "periodoInicial": periodo_inicial, "periodoFinal": periodo_final,
        "paginas": paginas, "registros": registros,
    }
    params["entidad" if entidad else "tipoEntidad"] = entidad or tipo
    data = client._get_with_retry(_httpx, url, params, endpoint, paginas)
    if isinstance(data, dict):
        data = data.get("data", data.get("registros", [data]))
    if not isinstance(data, list):
        return {"count": 0, "raw": str(data)[:300]}

    def _fp(r):
        return {k: r.get(k) for k in ("entidad", "periodo", "conceptoNivel1", "conceptoNivel2", "indicador", "componente", "valor") if k in r}

    # Distinct concept inventory (conceptoNivel1 → sorted set of conceptoNivel2),
    # to design the EIC parser against verified concepts instead of guessing.
    concepts: Dict[str, set] = {}
    entities = set()
    for r in data:
        entities.add(str(r.get("entidad") or ""))
        n1 = str(r.get("conceptoNivel1") or "")
        n2 = str(r.get("conceptoNivel2") or "")
        if n1:
            concepts.setdefault(n1, set()).add(n2)
    concept_inv = {k: sorted(v) for k, v in sorted(concepts.items())}

    # Distinct flat field values (for indicator/solvency endpoints, which use
    # `indicador`/`componente`/`tipoIndicador` instead of the concept tree).
    flat: Dict[str, set] = {}
    for r in data:
        for f in ("indicador", "componente", "tipoIndicador"):
            v = r.get(f)
            if v:
                flat.setdefault(f, set()).add(str(v))
    flat_inv = {k: sorted(v) for k, v in sorted(flat.items())}

    # Raw record shape (for endpoints whose fields we don't yet know, e.g. carteras).
    sample_keys = sorted(data[0].keys()) if data else []
    # Distinct values of any non-numeric dimension fields (to learn breakdowns).
    dims: Dict[str, set] = {}
    skip = {"entidad", "periodo", "valor", "Valor"}
    for r in data[:5000]:
        for k, v in r.items():
            if k not in skip and isinstance(v, str):
                dims.setdefault(k, set()).add(v)
    dim_inv = {k: sorted(v)[:40] for k, v in sorted(dims.items())}

    # Compact raw-row dump (concept levels + valor) to inspect hierarchical trees
    # like the income statement — to verify the real subtotal convention instead of
    # guessing. Optional `grep` filters rows whose concept path contains the term.
    grep_norm = _norm(grep) if grep else ""
    levels = ("conceptoNivel1", "conceptoNivel2", "conceptoNivel3",
              "conceptoNivel4", "conceptoNivel5", "conceptoNivel6", "conceptoNivel7")

    def _row(r):
        return {**{k: r.get(k) for k in levels if r.get(k) is not None},
                "valor": r.get("valor")}

    rows = []
    for r in data:
        if grep_norm and not any(grep_norm in _norm(r.get(k)) for k in levels):
            continue
        rows.append(_row(r))
        if len(rows) >= 250:
            break

    return {
        "params": params,
        "count": len(data),
        "entities": sorted(e for e in entities if e),
        "concepts": concept_inv,
        "fields": flat_inv,
        "sample_keys": sample_keys,
        "dimensions": dim_inv,
        "sample": data[0] if data else None,
        "rows": rows,
        "first": _fp(data[0]) if data else None,
        "last": _fp(data[-1]) if data else None,
    }


# ─── SIB explorer (discover supervised entity universe, live) ────

@router.get(
    "/sib-explore",
    summary="Explorar entidades supervisadas (API SIB en vivo)",
    description="Lista los tipos de entidad y nombres que devuelve la API del SIB, para mapear la cobertura. Requiere rol admin y SIB configurado.",
)
async def sib_explore(
    period: str = Query("2024-12", description="Período YYYY-MM a consultar"),
    tipos: str = Query("", description="Códigos tipoEntidad a probar (coma). Vacío = lista por defecto."),
    current_user: User = Depends(get_current_user),
):
    if not role_satisfies(current_user.role, UserRole.admin):
        raise HTTPException(status_code=403, detail="Se requiere rol admin")
    from modules.banking_score.external.sib_data_client import get_sib_data_client

    client = get_sib_data_client(force_new=True)
    if client is None:
        raise HTTPException(status_code=400, detail="SIB no configurada (clave/proxy).")

    result: Dict[str, object] = {"period": period}

    def _entities(records):
        out = set()
        for r in records:
            out.add(str(r.get("entidad") or r.get("nombreEntidad") or r.get("nombre") or "?"))
        return sorted(out)[:60]

    # Probe each financial-statement endpoint with candidate tipoEntidad codes to
    # find which ones return data (and the entity names) for the as-yet-uncovered
    # types: corporaciones de crédito, agentes de cambio, fiduciarias.
    candidates = [c.strip() for c in (tipos or "").split(",") if c.strip()] or [
        "BM", "BAyC", "AAyP", "BAC", "AAP", "CC", "CCR", "CORP", "AC", "ARC",
        "EIC", "AGC", "FID", "FI", "EF",
    ]
    probes: Dict[str, object] = {}
    for endpoint in ("estados/situacion/eif", "estados/situacion/eic"):
        for code in candidates:
            label = f"{endpoint}?tipoEntidad={code}"
            try:
                recs = client._get(endpoint, {
                    "periodoInicial": period, "periodoFinal": period, "tipoEntidad": code,
                })
                if recs:
                    probes[label] = {"count": len(recs), "entities": _entities(recs),
                                     "fields": list(recs[0].keys())}
            except Exception as e:  # noqa: BLE001
                probes[label] = {"error": str(e)[:120]}
    result["probes"] = probes
    return result


# ─── Data overview stats (for the "Base de Datos Bancaria" card) ─

@router.get(
    "/overview",
    summary="Resumen de la base de datos bancaria",
    description="Conteos de entidades, registros, calificaciones y rango de períodos.",
)
async def data_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from modules.banking_score.sib_sync import bank_data_stats
    return bank_data_stats(db)


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


# ─── Fiduciary PDF diagnostic (admin) ────────────────────────────
# Validates the audited-PDF AI extraction end-to-end before wiring persistence.

@router.get(
    "/fiduciaria-pdf-test",
    summary="Diagnóstico: extraer un PDF de fiduciaria/fideicomiso",
    include_in_schema=False,
)
async def fiduciaria_pdf_test(
    slug: str = Query("fiduciaria-reservas", description="Slug de la fiduciaria"),
    year: int = Query(None, description="Año del estado de la entidad (p.ej. 2024)"),
    trust: str = Query(None, description="Nombre del fideicomiso (en vez de la entidad)"),
    current_user: User = Depends(get_current_user),
):
    if not role_satisfies(current_user.role, UserRole.admin):
        raise HTTPException(status_code=403, detail="Requiere rol de administrador.")

    import os as _os

    from modules.banking_score.external import fiduciaria_pdf_client as fc
    from shared.pdf.audited_extractor import AuditedPdfExtractor

    try:
        disco = fc.discover_pdfs(slug)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"No se pudo leer la ficha del portal: {e}")

    is_trust = bool(trust)
    if is_trust:
        match = next((u for n, u in disco["trusts"] if trust.lower() in n.lower()), None)
        if not match:
            raise HTTPException(
                status_code=404,
                detail=f"Fideicomiso '{trust}' no encontrado. Disponibles: "
                + ", ".join(n for n, _ in disco["trusts"]),
            )
    else:
        ents = disco["entity"]
        if year is not None:
            match = next((u for y, u in ents if y == year), None)
        else:
            match = ents[0][1] if ents else None
        if not match:
            yrs = [y for y, _ in ents]
            raise HTTPException(status_code=404, detail=f"Sin estado de entidad para ese año. Años: {yrs}")

    path = None
    try:
        path = fc.download_pdf(match)
        extractor = AuditedPdfExtractor()
        statements = extractor.extract_statements(path)
        fields = fc.map_trust_fields(statements) if is_trust else fc.map_entity_fields(statements)
        return {
            "source_url": match,
            "kind": "trust" if is_trust else "entity",
            "company_info": statements.get("company_info", {}),
            "n_balance_items": len(statements.get("balance_general", [])),
            "n_income_items": len(statements.get("estado_resultados", [])),
            "mapped_fields": fields,
        }
    except Exception as e:  # noqa: BLE001
        logger.exception("fiduciaria-pdf-test falló")
        raise HTTPException(status_code=500, detail=f"Extracción falló: {e}")
    finally:
        if path and _os.path.exists(path):
            _os.remove(path)


# ─── Fiduciary ingestion (admin) ─────────────────────────────────

@router.post(
    "/fiduciaria-sync",
    summary="Sincronizar fiduciarias (PDFs auditados de la SIB)",
    include_in_schema=False,
)
async def fiduciaria_sync(
    include_trusts: bool = Query(True, description="Ingerir también los fideicomisos públicos"),
    include_entities: bool = Query(True, description="Ingerir las entidades fiduciarias"),
    only_latest: bool = Query(False, description="Solo el último año por entidad (más rápido)"),
    current_user: User = Depends(get_current_user),
):
    if not role_satisfies(current_user.role, UserRole.admin):
        raise HTTPException(status_code=403, detail="Requiere rol de administrador.")
    from modules.banking_score.fiduciaria_sync import start_fiduciaria_sync_background

    return start_fiduciaria_sync_background(
        include_trusts=include_trusts, only_latest=only_latest, include_entities=include_entities,
    )


@router.get(
    "/fiduciaria-sync-status",
    summary="Estado de la sincronización de fiduciarias",
    include_in_schema=False,
)
async def fiduciaria_sync_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from modules.banking_score.fiduciaria_sync import get_fiduciaria_status

    return get_fiduciaria_status(db)


@router.post(
    "/recompute-carteras",
    summary="Recomputar métricas de cartera (Mayores Deudores, A, vencida) de un trimestre",
    include_in_schema=False,
)
async def recompute_carteras(
    period: str = Query(..., description="Trimestre YYYY-MM (p. ej. 2025-12)"),
    current_user: User = Depends(get_current_user),
):
    if not role_satisfies(current_user.role, UserRole.admin):
        raise HTTPException(status_code=403, detail="Requiere rol de administrador.")
    from shared import operations
    return operations.trigger("recompute-carteras", origin="manual",
                              user_id=current_user.id, params={"period": period})
