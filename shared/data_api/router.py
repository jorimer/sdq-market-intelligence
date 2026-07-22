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
from shared.data_api.ledger import changes_since, record_manifest
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

    # Registrar el inventario visto: es lo que hace consultable /catalog/changes.
    # Se registra SIEMPRE el manifiesto completo del sector visible, no la vista
    # filtrada, para que un filtro del cliente no marque bajas falsas.
    record_manifest(ctx.db, _visible_assets(ctx, include_quarantined=True))

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


@router.get("/catalog/changes", summary="Altas y bajas del inventario desde una fecha")
async def catalog_changes(
    ctx: ApiContext = Depends(require_api_key),
    since: str = Query(..., description="Fecha ISO desde la cual listar cambios."),
) -> Dict[str, Any]:
    """Qué entró y qué salió del catálogo desde ``since``.

    Es la contraparte necesaria de la auto-extensión: el inventario crece solo, y un
    cliente que corre sin supervisión se entera por acá — no por correo. Las bajas
    viajan igual que las altas: una serie que dejó de publicarse rompe un modelo en
    silencio si nadie la reporta."""
    started = time.perf_counter()
    visible = {a.key for a in _visible_assets(ctx, include_quarantined=True)}
    try:
        result = changes_since(ctx.db, since, visible_keys=visible)
    except ValueError as exc:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_since", str(exc), str(exc)
        )

    payload = {
        "meta": {
            **ctx.meta(), "resource": "catalog/changes", "since": result["since"],
            "added": len(result["added"]), "retired": len(result["retired"]),
        },
        "data": {"added": result["added"], "retired": result["retired"]},
        "caveats": [{
            "code": "ledger_scope",
            "message": ("El registro arranca la primera vez que se consultó el catálogo: "
                        "un activo anterior a esa fecha no figura como alta."),
        }],
    }
    record_usage(
        ctx.db, ctx.key, resource="catalog/changes", status_code=status.HTTP_200_OK,
        rows=len(result["added"]) + len(result["retired"]),
        latency_ms=int((time.perf_counter() - started) * 1000),
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


@router.get("/scores/{sector}", summary="Scores e índices propietarios del sector")
async def scores(
    sector: str,
    ctx: ApiContext = Depends(require_api_key),
    code: Optional[str] = Query(None, description="Código del score (ver /catalog kind=score)."),
    subject: Optional[str] = Query(
        None,
        description=("Sujeto exactamente como aparece en `subjects` del descriptor "
                     "(/catalog kind=score): código de país del panel, entidad o slug."),
    ),
    start: Optional[str] = Query(None, description="Período inicial inclusive."),
    end: Optional[str] = Query(None, description="Período final inclusive."),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
) -> Dict[str, Any]:
    """Scores/índices con su desglose dimensional numérico. La narrativa NUNCA viaja
    por acá — es el producto de reporte; el desglose explicable sí."""
    started = time.perf_counter()

    assets = [a for a in _visible_assets(ctx, include_quarantined=False)
              if a.kind == "score" and a.sector_key == sector]
    if code:
        assets = [a for a in assets if a.code == code]
    if not assets:
        record_usage(
            ctx.db, ctx.key, resource="scores", asset_key=f"{sector}:{code or '*'}",
            status_code=status.HTTP_404_NOT_FOUND,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        raise api_error(
            status.HTTP_404_NOT_FOUND, "score_not_found",
            f"No hay un score disponible para '{sector}'"
            + (f" con código '{code}'." if code else "."),
            f"No available score for '{sector}'"
            + (f" with code '{code}'." if code else "."),
        )
    if len(assets) > 1:
        raise api_error(
            status.HTTP_400_BAD_REQUEST, "ambiguous_code",
            (f"El sector '{sector}' publica varios scores: "
             f"{', '.join(sorted(a.code for a in assets))}. Precise 'code'."),
            (f"Sector '{sector}' publishes several scores: "
             f"{', '.join(sorted(a.code for a in assets))}. Specify 'code'."),
        )

    asset = assets[0]
    product = get_product(asset.sector_key, ctx.db)
    reader = getattr(product, "score_observations", None)
    if not callable(reader):
        raise api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE, "reader_unavailable",
            "El score está declarado pero su lector no está disponible.",
            "The score is declared but its reader is unavailable.",
        )

    observations = list(
        reader(asset.code, subject=subject, start=start, end=end, limit=limit) or ()
    )

    caveats: List[Dict[str, str]] = [{
        "code": "derived_asset",
        "message": ("Score de cálculo propietario de SDQ: el desglose dimensional es "
                    "numérico y explicable; la lectura narrativa pertenece al producto "
                    "de reporte y no viaja por la API."),
    }]
    if asset.note:
        caveats.append({"code": "score_direction", "message": asset.note})

    payload = {
        "meta": {
            **ctx.meta(),
            "resource": "scores",
            "score": asset.to_dict(),
            "count": len(observations),
        },
        "data": [
            {
                "subject": o.subject,
                "period": o.period,
                "score": o.score,
                "band": o.band,
                "dimensions": o.dimensions,
                "model_version": o.model_version,
                "reason": o.reason,
            }
            for o in observations
        ],
        "caveats": caveats,
    }
    record_usage(
        ctx.db, ctx.key, resource="scores", asset_key=asset.key,
        status_code=status.HTTP_200_OK, rows=len(observations),
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return payload


@router.get("/signals/{sector}", summary="Señales deterministas de alerta del sector")
async def signals(
    sector: str,
    ctx: ApiContext = Depends(require_api_key),
    limit: int = Query(100, ge=1, le=1000),
) -> Dict[str, Any]:
    """Salida del motor de reglas (alertas tempranas, precursores). Determinista y
    citable; sin narrativa."""
    started = time.perf_counter()

    if not ctx.can_read_sector(sector):
        # Mismo 404 uniforme que el resto: no se revela lo que no se puede leer.
        record_usage(
            ctx.db, ctx.key, resource="signals", asset_key=sector,
            status_code=status.HTTP_404_NOT_FOUND,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        raise api_error(
            status.HTTP_404_NOT_FOUND, "signals_not_found",
            f"No hay señales disponibles para '{sector}'.",
            f"No available signals for '{sector}'.",
        )

    product = get_product(sector, ctx.db)
    reader = getattr(product, "canonical_signals", None)
    items = []
    if callable(reader):
        try:
            items = list(reader(limit=limit) or ())
        except Exception as exc:
            logger.warning("data_api: señales de '%s' fallaron: %s", sector, exc)
            items = []

    payload = {
        "meta": {**ctx.meta(), "resource": "signals", "sector": sector,
                 "count": len(items)},
        "data": [
            {
                "key": s.key, "label": s.label, "severity": s.severity,
                "period": s.period, "subject": s.subject, "detail": s.detail,
            }
            for s in items
        ],
        "caveats": [{
            "code": "deterministic_rules",
            "message": ("Señales del motor de reglas determinista: sin señal activa, la "
                        "lista viaja vacía — la ausencia de alerta es un resultado, no "
                        "un hueco."),
        }],
    }
    record_usage(
        ctx.db, ctx.key, resource="signals", asset_key=sector,
        status_code=status.HTTP_200_OK, rows=len(items),
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return payload


@router.get("/quality/{sector}", summary="Calidad y procedencia del sector")
async def quality(
    sector: str,
    ctx: ApiContext = Depends(require_api_key),
) -> Dict[str, Any]:
    """Readiness, cobertura real ponderada y estado por variable del sector — el mismo
    registro que gobierna el gate de honestidad, servido al cliente. Un consumidor que
    automatiza decide con esto cuánto confiar en cada eje ANTES de usarlo en un modelo."""
    started = time.perf_counter()

    if not ctx.can_read_sector(sector):
        record_usage(
            ctx.db, ctx.key, resource="quality", asset_key=sector,
            status_code=status.HTTP_404_NOT_FOUND,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        raise api_error(
            status.HTTP_404_NOT_FOUND, "quality_not_found",
            f"No hay información de calidad disponible para '{sector}'.",
            f"No available quality information for '{sector}'.",
        )

    from shared.registry.provenance import provenance_paragraph
    from shared.registry.service import build_data_registry

    registry = build_data_registry(ctx.db)
    axis = next((a for a in registry.axes if a.sector_key == sector), None)
    if axis is None or not axis.implemented:
        raise api_error(
            status.HTTP_404_NOT_FOUND, "quality_not_found",
            f"No hay información de calidad disponible para '{sector}'.",
            f"No available quality information for '{sector}'.",
        )

    payload = {
        "meta": {**ctx.meta(), "resource": "quality", "sector": sector},
        "data": {
            "period": axis.period,
            "coverage_real": axis.coverage_real,
            "state_counts": axis.state_counts,
            "degraded": axis.degraded,
            # La MISMA prosa de procedencia que llevan los reportes — generada del
            # registro, nunca escrita a mano (lección Hallazgo 7).
            "provenance": provenance_paragraph(axis),
            "variables": [
                {
                    "key": s.key, "label": s.label, "state": s.state,
                    "dimension": s.dimension, "weight": s.weight, "source": s.source,
                    "cadence": s.cadence, "real_fraction": s.real_fraction,
                    "scope": s.scope, "note": s.note,
                }
                for s in axis.signals
            ],
        },
        "caveats": [],
    }
    record_usage(
        ctx.db, ctx.key, resource="quality", asset_key=sector,
        status_code=status.HTTP_200_OK, rows=len(axis.signals),
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return payload


@router.get("/forecasts/{sector}", summary="Pronósticos con track record verificable")
async def forecasts(
    sector: str,
    ctx: ApiContext = Depends(require_api_key),
    code: Optional[str] = Query(None, description="Código del modelo (ver /catalog kind=forecast)."),
    limit: int = Query(100, ge=1, le=500),
) -> Dict[str, Any]:
    """Pronósticos congelados + su resultado real cuando ya ocurrió.

    El track record acumulado viaja en ``meta.forecast`` — acierto, Brier y la línea base
    contra la cual esas cifras significan algo. Un pronóstico servido sin su historial de
    aciertos sería una opinión con apariencia de medición."""
    started = time.perf_counter()

    assets = [a for a in _visible_assets(ctx, include_quarantined=False)
              if a.kind == "forecast" and a.sector_key == sector]
    if code:
        assets = [a for a in assets if a.code == code]
    if not assets:
        record_usage(
            ctx.db, ctx.key, resource="forecasts", asset_key=f"{sector}:{code or '*'}",
            status_code=status.HTTP_404_NOT_FOUND,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        raise api_error(
            status.HTTP_404_NOT_FOUND, "forecast_not_found",
            f"No hay un modelo de pronóstico disponible para '{sector}'.",
            f"No available forecast model for '{sector}'.",
        )
    if len(assets) > 1:
        raise api_error(
            status.HTTP_400_BAD_REQUEST, "ambiguous_code",
            (f"El sector '{sector}' publica varios modelos: "
             f"{', '.join(sorted(a.code for a in assets))}. Precise 'code'."),
            (f"Sector '{sector}' publishes several models: "
             f"{', '.join(sorted(a.code for a in assets))}. Specify 'code'."),
        )

    asset = assets[0]
    product = get_product(asset.sector_key, ctx.db)
    reader = getattr(product, "forecast_observations", None)
    if not callable(reader):
        raise api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE, "reader_unavailable",
            "El modelo está declarado pero su lector no está disponible.",
            "The model is declared but its reader is unavailable.",
        )

    observations = list(reader(asset.code, limit=limit) or ())
    scored = [o for o in observations if o.status == "scored"]

    caveats: List[Dict[str, str]] = [{
        "code": "prospective_record",
        "message": ("Registro prospectivo: cada pronóstico se congela antes del hecho y "
                    "se puntúa contra la publicación oficial. Nunca se reescribe uno "
                    "pasado."),
    }]
    # Con muestra chica, el acierto es ruidoso. Decirlo es parte del dato.
    if len(scored) < 10:
        caveats.append({
            "code": "small_sample",
            "message": (f"Solo {len(scored)} pronóstico(s) puntuado(s): la tasa de acierto "
                        f"todavía no es estadísticamente informativa. Contrástela con la "
                        f"línea base declarada en meta.forecast."),
        })

    payload = {
        "meta": {
            **ctx.meta(),
            "resource": "forecasts",
            "forecast": asset.to_dict(),
            "count": len(observations),
            "n_scored": len(scored),
        },
        "data": [
            {
                "as_of": o.as_of, "status": o.status, "predicted": o.predicted,
                "probabilities": o.probabilities, "implied_level": o.implied_level,
                "realized": o.realized, "realized_level": o.realized_level,
                "realized_date": o.realized_date, "correct": o.correct,
                "brier": o.brier, "level_abs_error": o.level_abs_error,
                "model_version": o.model_version,
            }
            for o in observations
        ],
        "caveats": caveats,
    }
    record_usage(
        ctx.db, ctx.key, resource="forecasts", asset_key=asset.key,
        status_code=status.HTTP_200_OK, rows=len(observations),
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return payload
