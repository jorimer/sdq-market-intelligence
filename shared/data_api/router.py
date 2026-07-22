"""Rutas de la Data API — ``/api/data/v1``.

Namespace SEPARADO de ``/api/v1`` a propósito: ``/api/v1`` es el contrato de la SPA,
cambia con el frontend y no puede quedar congelado por clientes de terceros. Acá el
contrato es público y su versión es explícita.

Ninguna ruta nombra una serie ni un indicador: todas toman la clave como parámetro y la
resuelven contra el manifiesto (``manifest.py``). Por eso el inventario crece sin tocar
este archivo — que es exactamente lo que pide la decisión de auto-extensión.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, status

from shared.data_api.dependencies import ApiContext, api_error, require_api_key
from shared.data_api.manifest import ExposedAsset, build_manifest
from shared.data_api.quota import record_usage
from shared.products.registry import get_product

logger = logging.getLogger("sdq.data_api")

router = APIRouter()

MAX_LIMIT = 5000
DEFAULT_LIMIT = 1000


def _visible_assets(ctx: ApiContext, *, include_quarantined: bool) -> List[ExposedAsset]:
    """Activos que ESTA llave puede ver.

    El filtro de sector va primero: un activo de un sector al que la llave no tiene
    acceso no aparece en absoluto — ni siquiera como cuarentena. No se revela la
    existencia de lo que no se puede leer (misma doctrina que el 404 de la web)."""
    # El uso declarado de la llave decide si puede recibir series de fuentes con
    # licencia no-comercial o share-alike: un consumidor que ANALIZA no redistribuye.
    manifest = build_manifest(ctx.db, allow_restricted=ctx.allows_restricted_sources)
    readable = {
        a.sector_key for a in manifest.assets if ctx.can_read_sector(a.sector_key)
    }
    out = [a for a in manifest.assets if a.sector_key in readable]
    if not include_quarantined:
        out = [a for a in out if a.exposed]
    return out


@router.get("/catalog", summary="Inventario visible para esta llave")
async def catalog(
    ctx: ApiContext = Depends(require_api_key),
    include_quarantined: bool = Query(
        False,
        description="Incluir los activos retenidos, con su razón de cuarentena.",
    ),
    kind: Optional[str] = Query(None, description="Filtrar por tipo: series | score | index"),
    sector: Optional[str] = Query(None, description="Filtrar por sector."),
) -> Dict[str, Any]:
    """Qué puede consultar esta llave, hoy.

    Es el endpoint que hace usable la auto-extensión: un cliente que automatiza descubre
    acá los activos nuevos, en vez de enterarse por correo.
    """
    started = time.perf_counter()
    assets = _visible_assets(ctx, include_quarantined=include_quarantined)
    if kind:
        assets = [a for a in assets if a.kind == kind]
    if sector:
        assets = [a for a in assets if a.sector_key == sector]

    payload = {
        "meta": {
            **ctx.meta(),
            "resource": "catalog",
            "count": len(assets),
            "include_quarantined": include_quarantined,
        },
        "data": [a.to_dict() for a in assets],
        "caveats": [
            {
                "code": "auto_extension",
                "message": (
                    "Este inventario se deriva del registro de productos: los activos "
                    "nuevos aparecen solos. Un activo marcado stability='thin' tiene "
                    "historia corta — verificar antes de usarlo en un modelo."
                ),
            }
        ],
    }
    record_usage(
        ctx.db, ctx.key, resource="catalog", status_code=status.HTTP_200_OK,
        rows=len(assets), latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return payload


@router.get("/series", summary="Observaciones de una serie canónica normalizada")
async def series(
    ctx: ApiContext = Depends(require_api_key),
    code: str = Query(..., description="Código canónico de la serie (ver /catalog)."),
    sector: Optional[str] = Query(
        None, description="Sector, si el mismo código existe en más de uno."
    ),
    start: Optional[str] = Query(None, description="Período inicial inclusive, p.ej. 2020-Q1."),
    end: Optional[str] = Query(None, description="Período final inclusive."),
    as_of: Optional[str] = Query(
        None,
        description=(
            "Point-in-time: devuelve solo lo publicado en o antes de esta fecha (ISO). "
            "Requiere que la serie tenga fecha de publicación en su linaje."
        ),
    ),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
) -> Dict[str, Any]:
    """Serve una serie canónica con su linaje. Los faltantes viajan como ``null`` con
    razón — nunca interpolados, nunca en cero."""
    started = time.perf_counter()

    candidates = [
        a for a in _visible_assets(ctx, include_quarantined=False)
        if a.code == code and a.kind == "series" and (not sector or a.sector_key == sector)
    ]
    if not candidates:
        # 404 uniforme: no se distingue "no existe" de "existe pero no lo podés leer" ni
        # de "está en cuarentena" — cualquiera de las tres revelaría el catálogo interno.
        record_usage(
            ctx.db, ctx.key, resource="series", asset_key=code,
            status_code=status.HTTP_404_NOT_FOUND, as_of=as_of,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        raise api_error(
            status.HTTP_404_NOT_FOUND, "series_not_found",
            f"No hay una serie disponible con el código '{code}'.",
            f"No available series with code '{code}'.",
        )
    if len(candidates) > 1:
        raise api_error(
            status.HTTP_400_BAD_REQUEST, "ambiguous_code",
            (f"El código '{code}' existe en varios sectores: "
             f"{', '.join(sorted(a.sector_key for a in candidates))}. Precise 'sector'."),
            (f"Code '{code}' exists in several sectors: "
             f"{', '.join(sorted(a.sector_key for a in candidates))}. Specify 'sector'."),
        )

    asset = candidates[0]
    product = get_product(asset.sector_key, ctx.db)
    reader = getattr(product, "series_observations", None)
    if not callable(reader):
        # No debería pasar (el manifiesto pone en cuarentena lo que no tiene lector),
        # pero si pasa se responde honesto en vez de con una lista vacía que el cliente
        # leería como "no hay datos".
        raise api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE, "reader_unavailable",
            "La serie está declarada pero su lector no está disponible.",
            "The series is declared but its reader is unavailable.",
        )

    try:
        observations = list(
            reader(asset.code, start=start, end=end, as_of=as_of, limit=limit) or ()
        )
    except ValueError as exc:
        # El lector rechaza un as_of que no puede honrar: se propaga tal cual en vez de
        # devolver datos que fingirían ser point-in-time.
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "as_of_unsupported", str(exc), str(exc)
        )

    caveats: List[Dict[str, str]] = []
    missing = sum(1 for o in observations if getattr(o, "value", None) is None)
    if missing:
        caveats.append({
            "code": "missing_observations",
            "message": (f"{missing} de {len(observations)} observaciones no tienen dato. "
                        "Se devuelven como null: no se interpola ni se asume cero."),
        })
    if asset.stability == "thin":
        caveats.append({
            "code": "thin_history",
            "message": f"La serie tiene {asset.n_obs} observaciones; historia corta.",
        })
    if as_of:
        caveats.append({
            "code": "point_in_time",
            "message": (f"Corte point-in-time al {as_of}: refleja lo publicado hasta esa "
                        "fecha, no la revisión posterior."),
        })

    payload = {
        "meta": {
            **ctx.meta(),
            "resource": "series",
            "series": asset.to_dict(),
            "as_of": as_of,
            "count": len(observations),
        },
        "data": [
            {
                "period": o.period,
                "value": o.value,
                "unit": getattr(o, "unit", None) or asset.unit,
                "source": getattr(o, "source", None) or asset.source,
                "published_at": getattr(o, "published_at", None),
                "reason": getattr(o, "reason", None),
            }
            for o in observations
        ],
        "caveats": caveats,
    }
    record_usage(
        ctx.db, ctx.key, resource="series", asset_key=asset.key,
        status_code=status.HTTP_200_OK, rows=len(observations), as_of=as_of,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return payload
