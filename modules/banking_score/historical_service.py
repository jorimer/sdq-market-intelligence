"""Servicio de la vista *Histórico* (Cronología SB): cohorte de quiebras + forense por entidad.

Sirve a la página analítica del front (no es un producto del catálogo comercial: por decisión
del dueño, el histórico es motor de backtest/contexto, no un SKU). Lee ``SibHistoricalFinancials``
(derivado del ledger, ver el crosswalk) y reusa ``sib_historical_backtest`` para el timeline de
Alerta Temprana. Todo dato real de fuente pública.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from modules.banking_score import sib_historical_backtest as bt


def _f(x) -> Optional[float]:
    return float(x) if x is not None else None


def _by_name(db) -> Dict[str, Dict]:
    """Índice {entidad_nombre: {fecha: row}} de un solo scan (para backtest con contexto de pares)."""
    from modules.banking_score.models.models import SibHistoricalFinancials
    out: Dict[str, Dict] = {}
    for f in db.query(SibHistoricalFinancials).all():
        if f.entidad_nombre:
            out.setdefault(f.entidad_nombre, {})[f.fecha] = f
    return out


def list_entities(db, *, only_exited: bool = False) -> List[Dict]:
    """Entidades disponibles en el histórico, con su rango y si siguen reportando.

    ``only_exited`` filtra a las que salieron del sistema (útil para el foco forense)."""
    from sqlalchemy import func
    from modules.banking_score.models.models import SibHistoricalFinancials as F

    rows = (db.query(F.entidad_nombre, F.tipo_entidad,
                     func.min(F.fecha), func.max(F.fecha), func.count(F.id))
            .filter(F.entidad_nombre.isnot(None))
            .group_by(F.entidad_nombre, F.tipo_entidad).all())
    system_max = db.query(func.max(F.fecha)).scalar()
    out = []
    for nombre, tipo, primer, ultimo, n in rows:
        exited = bool(system_max and ultimo and ultimo < system_max)
        if only_exited and not exited:
            continue
        out.append({
            "nombre": nombre, "tipo_entidad": tipo,
            "primer": primer.isoformat() if primer else None,
            "ultimo": ultimo.isoformat() if ultimo else None,
            "n_periodos": n, "salio_del_sistema": exited,
        })
    out.sort(key=lambda e: (not e["salio_del_sistema"], e["nombre"]))
    return out


def cohort_backtest(db) -> Dict:
    """Backtest de Alerta Temprana sobre la cohorte de quiebras (la validación con dato real)."""
    results = bt.backtest_cohort(db)
    found = [r for r in results if r.get("found")]
    return {
        "cohort": results,
        "n_found": len(found),
        "leads": {r["nombre"]: r.get("lead_months") for r in found},
    }


def forensic_package(db, nombre: str) -> Optional[Dict]:
    """Paquete forense de UNA entidad: trayectoria mensual de ratios + timeline de alertas.

    Keyea por ``entidad_nombre`` (no por código: el código es un slot de linaje que mezcla la
    quebrada con su sucesor). Devuelve ``None`` si no hay dato para ese nombre."""
    by_name = _by_name(db)
    series_rows = by_name.get(nombre)
    if not series_rows:
        return None

    dates = sorted(series_rows)
    series: List[Dict] = []
    prev_dep = None
    for d in dates:
        r = series_rows[d]
        dep = _f(r.depositos_totales)
        dep_mom = round(100 * (dep / prev_dep - 1), 1) if (dep and prev_dep) else None
        series.append({
            "fecha": d.isoformat(),
            "activos_totales": _f(r.activos_totales),
            "morosidad_pct": _f(r.morosidad_pct),
            "cobertura_pct": _f(r.cobertura_pct),
            "apalancamiento_pct": _f(r.apalancamiento_pct),
            "depositos": dep,
            "dep_mom_pct": dep_mom,
            "patrimonio": _f(r.patrimonio),
            "utilidad_neta": _f(r.utilidad_neta),
        })
        if dep:
            prev_dep = dep

    # Fecha de salida conocida si está en la cohorte; si no, el último período reportado.
    salida = next((c.get("salida") for c in bt.FAILED_COHORT if c["nombre"] == nombre), None)
    backtest = bt.backtest_entity(series_rows, all_series=by_name, salida=salida)
    last = series_rows[dates[-1]]
    system_max = max((max(v) for v in by_name.values()), default=None)
    return {
        "meta": {
            "nombre": nombre, "tipo_entidad": last.tipo_entidad, "sector": last.sector,
            "primer": dates[0].isoformat(), "ultimo": dates[-1].isoformat(),
            "n_periodos": len(dates),
            "salio_del_sistema": bool(system_max and dates[-1] < system_max),
        },
        "series": series,
        "backtest": backtest,
    }
