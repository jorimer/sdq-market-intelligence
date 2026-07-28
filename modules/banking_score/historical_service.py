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


def _at(series: List[Dict], fecha: Optional[str], key: str) -> Optional[float]:
    if not fecha:
        return None
    return next((p[key] for p in series if p["fecha"] == fecha), None)


def forensic_narrative_context(pkg: Dict) -> Dict:
    """Contexto compacto para la narrativa forense (template ``banking_forensic``).

    Trae SOLO cifras reales del paquete —onset, anticipación, morosidad/cobertura en el
    punto de inflexión y en el pico, la peor fuga de depósitos, fechas— para que el guardrail
    numérico pueda respaldar cada número que cite la prosa. Los superlativos y las cifras que
    no estén aquí no deben aparecer en el texto."""
    meta, bt, series = pkg["meta"], pkg["backtest"], pkg["series"]
    onset = bt.get("onset_cluster")
    moras = [p["morosidad_pct"] for p in series if p["morosidad_pct"] is not None]
    deps = [p["dep_mom_pct"] for p in series if p["dep_mom_pct"] is not None]
    peor_fuga = min(deps) if deps else None
    peor_fuga_fecha = next((p["fecha"] for p in series if p["dep_mom_pct"] == peor_fuga), None)
    onset_alerts: list = next((t["alerts"] for t in bt.get("timeline", []) if t["period"] == onset), [])
    return {
        "entidad": meta["nombre"],
        "tipo_entidad": meta["tipo_entidad"],
        "salio_del_sistema": meta["salio_del_sistema"],
        "periodo_dato": f"{meta['primer']} → {meta['ultimo']}",
        "colapso_fecha": bt.get("exit_date"),
        "onset_deterioro": onset,
        "anticipacion_meses": bt.get("lead_months"),
        "meses_en_alerta": bt.get("n_high_months"),
        "morosidad_en_onset_pct": _at(series, onset, "morosidad_pct"),
        "cobertura_en_onset_pct": _at(series, onset, "cobertura_pct"),
        "morosidad_maxima_pct": max(moras) if moras else None,
        "peor_fuga_depositos_pct": peor_fuga,
        "peor_fuga_fecha": peor_fuga_fecha,
        "cluster_en_onset": [a["code"] for a in onset_alerts if a["severity"] == "alta"],
        "fuente": "Superintendencia de Bancos — Cronología SB (estados financieros mensuales, dato real)",
        "nota": ("Capital regulatorio Basilea NO existe en el balance contable pre-2004 (no citar "
                 "solvencia Basel); apalancamiento patrimonio/activos es proxy. Informe "
                 "retrospectivo/forense, no una calificación emitida en su momento."),
    }


async def forensic_narrative(db, nombre: str) -> Optional[Dict]:
    """Genera la LECTURA FORENSE (prosa SCQA) de una entidad vía el cerebro. ``None`` si no
    hay dato. Best-effort: si el motor IA no está disponible, devuelve narrativa vacía."""
    pkg = forensic_package(db, nombre)
    if pkg is None:
        return None
    from shared.narrative.claude_engine import narrative_engine
    ctx = forensic_narrative_context(pkg)
    narrativa, degraded = "", False
    try:
        res = await narrative_engine.generate(
            context=ctx, template="banking_forensic", mode="deep",
            axis="banking", audience="comite_credito")
        if res.model_used != "static_fallback":
            narrativa = (res.text or "").strip()
        else:
            degraded = True
    except Exception:  # noqa: BLE001 — la lectura nunca rompe el endpoint
        degraded = True
    return {"nombre": nombre, "context": ctx, "narrative": narrativa, "degraded": degraded}


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
